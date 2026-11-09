from logging import Logger
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import polars as pl
import pyarrow.parquet as pq
from config.projectsettings.settings import (
    NUMERIC_HASH_SEED,
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
)
from config.projectsettings.scripts import (
    CANDIDATURES_OUTPUT_PARQUETS,
    ELECTIONS_OUTPUT_PARQUETS,
    ELECTIONS_ROUNDS_OUTPUT_PARQUETS,
    TSE_MUNICIPALITIES_RAW_PARQUETS,
)
from scripts.bricks.evm_bulletin_vote_type_expr import tse_evm_bulletin_vote_type_expr
from infra.datascript.DataScript import DataScript
from infra.parquet_sort import write_sorted_parquets
from scripts.bricks.tse_bulletin_schema import normalize_tse_bulletin
from scripts.bricks.candidature_identity import (
    candidature_id_expr, election_lookup, with_electoral_locality, election_round_id_expr,
)
from scripts.bricks.validated_lookup import validated_lookup


EVM_BULLETIN_ITEMS_RAW_PARQUETS = BASE_DIR / "downloads" / "tse" / "evm_bulletin"
EVM_BULLETIN_ITEMS_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_evm_bulletin_item"
    / "opendata_evm_bulletin_item.parquet"
)


SORT_KEYS = ["tipo", "quantidade", "boletim_id"]

class EvmBulletinItemDataScript(DataScript):
    script_id = "evm_bulletin_items"
    lifetime = "0 6 18 * *"

    source = "Tribunal Superior Eleitoral"
    source_url = "https://dadosabertos.tse.jus.br/"
    description = (
        "Votos dos boletins de urna por candidatura, cargo, seção e turno."
    )

    input_paths = [
        EVM_BULLETIN_ITEMS_RAW_PARQUETS,
        CANDIDATURES_OUTPUT_PARQUETS,
        ELECTIONS_OUTPUT_PARQUETS,
        ELECTIONS_ROUNDS_OUTPUT_PARQUETS,
        TSE_MUNICIPALITIES_RAW_PARQUETS,
    ]
    output_paths = [
        EVM_BULLETIN_ITEMS_OUTPUT_PARQUETS,
    ]

    dependencies = [
        "candidatures",
        "elections",
    ]
    tags = []

    def process_data(self, logger: Logger):
        files = sorted(EVM_BULLETIN_ITEMS_RAW_PARQUETS.glob("*.parquet"))
        global_schema = _scan_tse_bulletins_dynamic(logger).collect_schema()
        lookups = _prepare_lookups(
            pl.scan_parquet(TSE_MUNICIPALITIES_RAW_PARQUETS / "*.parquet"),
            election_lookup(
                pl.scan_parquet(ELECTIONS_ROUNDS_OUTPUT_PARQUETS),
                pl.scan_parquet(ELECTIONS_OUTPUT_PARQUETS),
            ),
            pl.scan_parquet(CANDIDATURES_OUTPUT_PARQUETS),
        )

        root = Path(os.getenv("TURI_UNIQUE_TEMP_DIRECTORY", ".turi_unique_tmp")).resolve()
        root.mkdir(parents=True, exist_ok=True)

        with TemporaryDirectory(prefix="bulletin-items-", dir=root) as directory:
            work = Path(directory)
            parts = work / "parts"
            parts.mkdir()
            total_rows = 0
            total_votes = 0
            schema = None

            for number, file in enumerate(files, 1):
                logger.info("Bulletin items file %d/%d: %s", number, len(files), file.name)
                raw = normalize_tse_bulletin(pl.scan_parquet(file, low_memory=True))
                available = raw.collect_schema().names()
                raw = raw.select(
                    (
                        pl.col(name).cast(dtype)
                        if name in available else pl.lit(None, dtype=dtype).alias(name)
                    )
                    for name, dtype in global_schema.items()
                ).filter(~pl.col("tipo_eleicao_normalizado").is_in(["2"]))

                expected = raw.select(
                    pl.len().alias("rows"),
                    pl.col("QT_VOTOS").cast(pl.Int64).sum().alias("votes"),
                ).collect(engine="streaming").row(0, named=True)

                part = parts / f"{number:04d}.parquet"
                processed = _process_with_lookups(raw, *lookups)
                processed.sink_parquet(
                    part, compression="zstd", row_group_size=16_384, engine="streaming",
                )
                actual = pl.scan_parquet(part).select(
                    pl.len().alias("rows"),
                    pl.col("quantidade").cast(pl.Int64).sum().alias("votes"),
                ).collect(engine="streaming").row(0, named=True)

                if actual != expected:
                    raise ValueError(
                        f"Bulletin rows/votes changed in {file}: {actual} != {expected}"
                    )

                total_rows += actual["rows"]
                total_votes += actual["votes"] or 0
                schema = schema or pq.read_schema(part)
                logger.info(
                    "Bulletin items checked: rows=%d votes=%d",
                    actual["rows"], actual["votes"] or 0,
                )

            write_sorted_parquets(
                str(parts / "*.parquet"),
                EVM_BULLETIN_ITEMS_OUTPUT_PARQUETS,
                SORT_KEYS,
                schema=schema,
                work_directory=work,
                expected_rows=total_rows,
                expected_totals={"quantidade": total_votes},
            )


def _process_data(
    bu_raw: pl.LazyFrame,
    municipalities: pl.LazyFrame,
    elections: pl.LazyFrame,
    candidates: pl.LazyFrame,
) -> pl.LazyFrame:
    lookups = _prepare_lookups(municipalities, elections, candidates)

    return _process_with_lookups(bu_raw, *lookups).sort(by=SORT_KEYS)


def _prepare_lookups(
    municipalities: pl.LazyFrame,
    elections: pl.LazyFrame,
    candidates: pl.LazyFrame,
) -> tuple[pl.LazyFrame, pl.LazyFrame, pl.LazyFrame]:
    municipalities = municipalities.select(
        "CD_MUNICIPIO_TSE", "CD_MUNICIPIO_IBGE",
    ).collect(engine="streaming").lazy()
    elections = validated_lookup(elections, ["codigo_tse", "codigo_local"])

    # Ambiguous ballot numbers must not arbitrarily select a person or multiply votes.
    candidates = (
        candidates.with_columns(candidature_id_expr().alias("_chave_candidatura"))
        .group_by("_chave_candidatura")
        .agg(pl.col("id").n_unique().alias("_count"), pl.col("id").first().alias("candidatura_id"))
        .filter(pl.col("_count") == 1)
        .select("_chave_candidatura", "candidatura_id")
    )
    candidates = validated_lookup(candidates, "_chave_candidatura")

    return municipalities, elections, candidates


def _process_with_lookups(
    bu_raw: pl.LazyFrame,
    municipalities: pl.LazyFrame,
    elections: pl.LazyFrame,
    candidates: pl.LazyFrame,
) -> pl.LazyFrame:
    bu_raw = bu_raw.with_columns(pl.col("CD_MUNICIPIO").cast(pl.String))

    bulletins_lazy_op = (
        bu_raw
        .select([
            "SG_UF",
            "CD_PLEITO",
            "CD_ELEICAO",
            "CD_MUNICIPIO",
            "NR_ZONA",
            "NR_SECAO",
            "CD_CARGO_PERGUNTA",
            "CD_TIPO_VOTAVEL",
            "NR_VOTAVEL",
            "NR_URNA_EFETIVADA",
            "NR_TURNO",
            "QT_VOTOS",
            "NR_LOCAL_VOTACAO",
            # hashes
            pl.col("CD_FLASHCARD_URNA_EFETIVADA").alias("hash_flashcard"),
            pl.col("CD_CARGA_1_URNA_EFETIVADA").alias("hash_dados_carga_1"),
            pl.col("CD_CARGA_2_URNA_EFETIVADA").alias("hash_dados_carga_2")
        ])
        .with_columns(
            pl.col("NR_TURNO").cast(pl.Int32).alias("NR_TURNO")
        )
        .with_columns(
            pl.col("NR_URNA_EFETIVADA").hash(seed=NUMERIC_HASH_SEED).alias("urna_id")
        )
        .with_columns(
            pl.struct(["urna_id", "hash_flashcard", "hash_dados_carga_1", "hash_dados_carga_2"]).hash(seed=NUMERIC_HASH_SEED).alias("boletim_id"),
        )
        .with_columns(
            pl.struct(pl.exclude("SG_UF")).hash(seed=NUMERIC_HASH_SEED).alias("id"),
            tse_evm_bulletin_vote_type_expr("NR_VOTAVEL", "CD_TIPO_VOTAVEL").alias("tipo"),
            (
                pl.when(
                    ~pl.col("CD_TIPO_VOTAVEL").is_in(["1", "4"])
                ).then(pl.lit(None))
                .otherwise(pl.col("NR_VOTAVEL"))
            ).alias("valor"),
            pl.col("QT_VOTOS").cast(pl.Int32).alias("quantidade")
        )
    )
    bulletins_lazy_op = with_electoral_locality(
        bulletins_lazy_op, municipalities, "CD_CARGO_PERGUNTA", "CD_MUNICIPIO"
    ).with_columns(
        pl.col("CD_ELEICAO").cast(pl.Int32).alias("codigo_tse"),
        pl.col("CD_CARGO_PERGUNTA").cast(pl.Int32).alias("codigo_cargo_tse"),
        pl.col("NR_VOTAVEL").cast(pl.Int32, strict=False).alias("numero_candidato"),
    ).join(elections, on=["codigo_tse", "codigo_local"], how="left")
    return (
        bulletins_lazy_op.with_columns(
            election_round_id_expr("NR_TURNO").alias("turno_eleicao_id"),
            pl.when(
                (pl.col("CD_TIPO_VOTAVEL") == "1")
                & ~pl.col("NR_VOTAVEL").is_in(["95", "96", "97", "98"])
                & pl.col("eleicao_id").is_not_null()
                & pl.col("codigo_local").is_not_null()
                & pl.col("numero_candidato").is_not_null()
            ).then(candidature_id_expr())
            .otherwise(pl.lit(None, dtype=pl.UInt64))
            .alias("_chave_candidatura")
        )
        .join(candidates, on="_chave_candidatura", how="left")
        .select(
            "id", "boletim_id", "tipo", "valor", "quantidade",
            "eleicao_id", "turno_eleicao_id", "codigo_local", "codigo_cargo_tse", "candidatura_id",
        )
    )

def _scan_tse_bulletins_dynamic(logger: Logger) -> pl.LazyFrame:
    files = sorted(EVM_BULLETIN_ITEMS_RAW_PARQUETS.glob("*.parquet"))
    if not files:
        raise FileNotFoundError("Nenhum arquivo Parquet encontrado")
    logger.info("found %d bulletin files", len(files))
    return pl.concat(
        [normalize_tse_bulletin(pl.scan_parquet(file)) for file in files],
        how="diagonal_relaxed",
    )


script_instance = EvmBulletinItemDataScript()
