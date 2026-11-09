import polars as pl
from config.projectsettings.settings import (
    NUMERIC_HASH_SEED,
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
)
from config.projectsettings.scripts import (
    TSE_MUNICIPALITIES_RAW_PARQUETS,
)
from infra.datascript.DataScript import DataScript
from infra.diskful_unique import diskful_unique, diskful_unique_session
from scripts.bricks.tse_bulletin_schema import normalize_tse_bulletin
from logging import Logger


EVM_BULLETINS_RAW_PARQUETS = BASE_DIR / "downloads" / "tse" / "evm_bulletin"
EVM_BULLETINS_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_evm_bulletin"
    / "opendata_evm_bulletin.parquet"
)

class EvmBulletinDataScript(DataScript):
    script_id = "evm_bulletin"
    lifetime = "0 4 18 * *"

    source = "Tribunal Superior Eleitoral"
    source_url = "https://dadosabertos.tse.jus.br/"
    description = (
        "Boletins físicos de urna e seus metadados de votação e localidade."
    )

    input_paths = [
        EVM_BULLETINS_RAW_PARQUETS,
        TSE_MUNICIPALITIES_RAW_PARQUETS,
    ]
    output_paths = [
        EVM_BULLETINS_OUTPUT_PARQUETS,
    ]

    dependencies = []
    tags = []

    @diskful_unique_session()
    def process_data(self, logger: Logger):
        files = list(EVM_BULLETINS_RAW_PARQUETS.glob("*.parquet"))
        if not files:
            raise FileNotFoundError(f"Nenhum arquivo Parquet encontrado")

        municipalities = pl.scan_parquet(TSE_MUNICIPALITIES_RAW_PARQUETS / "*.parquet")
        lazyframes_op: list[pl.LazyFrame] = []

        for f in files:
            lf = normalize_tse_bulletin(pl.scan_parquet(f))

            lf = _process_data(lf, municipalities)
            lf = diskful_unique(lf)

            lazyframes_op.append(lf)

        final_lf_op = pl.concat(lazyframes_op, how="diagonal_relaxed")
        final_lf_op = _consolidate_bulletins(final_lf_op)

        final_lf_op = final_lf_op.sort(
            by=[
                "zona_eleitoral",
                "local_votacao",
                "secao_eleitoral",
                "data_abertura",
                "urna_id"
            ]
        )

        final_lf_op.sink_parquet(EVM_BULLETINS_OUTPUT_PARQUETS, compression="zstd")



def _consolidate_bulletins(frame: pl.LazyFrame) -> pl.LazyFrame:
    localities = frame.group_by("id").agg(
        pl.when(pl.col("codigo_municipio_ibge").drop_nulls().n_unique() == 1)
        .then(pl.col("codigo_municipio_ibge").drop_nulls().first())
        .otherwise(pl.lit(None, dtype=pl.String))
        .alias("codigo_municipio_ibge")
    )

    bulletins = frame.drop("codigo_municipio_ibge")
    bulletins = diskful_unique(bulletins, "id")

    # Both inputs are unique by id: filesystem deduplication and group_by above.
    # Runtime join validation would force an in-memory fallback in Polars 1.38.
    return bulletins.join(localities, on="id", how="left")

def _parse_tse_datetime(column: str) -> pl.Expr:
    return pl.coalesce(
        pl.col(column).cast(pl.String).str.to_datetime("%d/%m/%Y %H:%M:%S", strict=False),
        pl.col(column).cast(pl.String).str.to_datetime("%d-%m-%Y %H:%M:%S", strict=False),
    )

def _process_data(
    bu_raw: pl.LazyFrame,
    municipalities: pl.LazyFrame | None = None,
) -> pl.LazyFrame:
    if municipalities is not None:
        locality_map = (
            municipalities.select(
                pl.col("CD_MUNICIPIO_TSE").cast(pl.Int32, strict=False).alias("_municipio_tse"),
                pl.col("CD_MUNICIPIO_IBGE").cast(pl.String).alias("codigo_municipio_ibge"),
            )
            .unique()
            .collect(engine="streaming")
        )

        # Validate only the small lookup. validate="m:1" on the large join
        # otherwise materializes the raw BUs in Polars 1.38's streaming engine.
        municipality_keys = locality_map["_municipio_tse"].drop_nulls()
        if municipality_keys.n_unique() != len(municipality_keys):
            raise pl.exceptions.ComputeError("join keys did not fulfill m:1 validation")

        bu_raw = bu_raw.with_columns(
            pl.col("CD_MUNICIPIO").cast(pl.Int32, strict=False).alias("_municipio_tse")
        ).join(locality_map.lazy(), on="_municipio_tse", how="left")
    else:
        bu_raw = bu_raw.with_columns(pl.lit(None, dtype=pl.String).alias("codigo_municipio_ibge"))

    # A physical bulletin contains votes for multiple elections. Its identity
    # and metadata must not depend on a particular office or electoral locality.
    bulletins_lazy_op = (
        bu_raw
        .select([
            "NR_URNA_EFETIVADA",
            "codigo_municipio_ibge",
            # datas
            _parse_tse_datetime("DT_ABERTURA").alias("data_abertura"),
            _parse_tse_datetime("DT_ENCERRAMENTO").alias("data_encerramento"),
            _parse_tse_datetime("DT_EMISSAO_BU").alias("data_emissao"),
            _parse_tse_datetime("DT_BU_RECEBIDO").alias("data_recebimento"),
            # local de votação
            pl.col("NR_ZONA").cast(pl.String).alias("zona_eleitoral"),
            pl.col("NR_SECAO").cast(pl.String).alias("secao_eleitoral"),
            pl.col("NR_LOCAL_VOTACAO").cast(pl.String).alias("local_votacao"),
            # quantitativos
            pl.col("QT_APTOS").cast(pl.Int32).alias("qtd_eleitores_aptos"),
            pl.col("QT_COMPARECIMENTO").cast(pl.Int32).alias("qtd_comparecimento"),
            pl.col("QT_ABSTENCOES").cast(pl.Int32).alias("qtd_abstencoes"),
            # hashes
            pl.col("CD_FLASHCARD_URNA_EFETIVADA").alias("hash_flashcard"),
            pl.col("CD_CARGA_1_URNA_EFETIVADA").alias("hash_dados_carga_1"),
            pl.col("CD_CARGA_2_URNA_EFETIVADA").alias("hash_dados_carga_2")
        ])
        .with_columns(
            pl.col("NR_URNA_EFETIVADA").hash(seed=NUMERIC_HASH_SEED).alias("urna_id")
        )
        .with_columns(
            pl.struct(["urna_id", "hash_flashcard", "hash_dados_carga_1", "hash_dados_carga_2"]).hash(seed=NUMERIC_HASH_SEED).alias("id"),
        )
        .select([
            "id",
            "urna_id",
            "codigo_municipio_ibge",
            # datas
            "data_abertura",
            "data_encerramento",
            "data_emissao",
            "data_recebimento",
            # local de votação
            "zona_eleitoral",
            "secao_eleitoral",
            "local_votacao",
            # quantitativos
            "qtd_eleitores_aptos",
            "qtd_comparecimento",
            "qtd_abstencoes",
            # hashes
            "hash_flashcard",
            "hash_dados_carga_1",
            "hash_dados_carga_2"
        ])
    )

    EVM_BULLETINS_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True, parents=True)

    return bulletins_lazy_op

script_instance = EvmBulletinDataScript()
