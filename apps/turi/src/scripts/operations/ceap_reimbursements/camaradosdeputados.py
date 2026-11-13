from logging import Logger

import polars as pl
from avoar.core.opendata.suppliers.domain import TipoDocumentoFornecedor
from core.CEAP.camaradosdeputados.reimbursement_types import CEAP_CATEGORIES_STRUCTMAP
from config.projectsettings.settings import NUMERIC_HASH_SEED
from infra.datascript.DataScript import DataScript
from infra.parquet_staging import staged_nested_parquets
from config.projectsettings.settings import (
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
)
from config.projectsettings.scripts import (
    PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS,
    CD_MANDATES_OUTPUT_PARQUETS,
)


CD_CEAPS_RAW_PARQUETS = BASE_DIR / "downloads" / "camaradosdeputados" / "ceaps" / "*.parquet"
CD_CEAPS_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_ceap_reimbursements"
    / "camaradosdeputados.parquet"
)
CD_CEAPS_PROOF_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_ceap_reimbursements_proof"
    / "camaradosdeputados.parquet"
)

class CamaraDosDeputadosCeapsDataScript(DataScript):
    script_id = "camaradosdeputados_ceaps"
    lifetime = "0 6 * * *"

    source = "Câmara dos Deputados"
    source_url = "https://www.camara.leg.br/cotas/"
    description = (
        "Despesas e comprovantes da cota parlamentar vinculados aos mandatos da Câmara."
    )

    input_paths = [
        CD_CEAPS_RAW_PARQUETS,
        PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS,
        CD_MANDATES_OUTPUT_PARQUETS,
    ]
    output_paths = [
        CD_CEAPS_OUTPUT_PARQUETS,
        CD_CEAPS_PROOF_OUTPUT_PARQUETS,
    ]

    dependencies = [
        "camaradosdeputados_mandate",
        "public_people",
    ]
    tags = []

    def process_data(self, logger: Logger):
        with staged_nested_parquets(
            CD_CEAPS_RAW_PARQUETS,
            work_directory=CD_CEAPS_OUTPUT_PARQUETS.parent,
        ) as raw_ceaps:
            self._process_data(raw_ceaps, logger)

    def _process_data(self, raw_ceaps: pl.LazyFrame, logger: Logger):
        identificators = (
            pl.scan_parquet(PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS)
            .filter(pl.col("fonte") == "camaradosdeputados")
            .with_columns(
                pl.col("identificador").cast(pl.String).str.strip_chars()
            )
        )

        mandates = (
            pl.scan_parquet(CD_MANDATES_OUTPUT_PARQUETS)
            .with_columns([
                pl.col("legislatura_id").cast(pl.Int32),
                pl.col("pessoa_publica_id").cast(pl.UInt64)
            ])
        )

        numfiles = sum(1 for _ in CD_CEAPS_RAW_PARQUETS.parent.glob("*.parquet"))
        logger.info("found %d files reading %s", numfiles, str(CD_CEAPS_RAW_PARQUETS.parent))

        cd_ceaps = (
            raw_ceaps
            
            .with_columns([
                pl.col("idDeputado").cast(pl.String).str.strip_chars(),
                pl.col("codigoLegislatura").cast(pl.Int32),
                pl.col("numeroSubCota").cast(pl.Int64),
                pl.col("numeroEspecificacaoSubCota").cast(pl.Int64)
            ])

            .with_columns(
                pl.struct(pl.all()).hash(seed=NUMERIC_HASH_SEED).alias("id")
            )

            .with_columns([
                pl.col("cnpjCPF")
                .str.strip_chars()
                .str.replace_all(r"\D", "")
                .alias("document_clean"),

                pl.col("fornecedor")
                .str.strip_chars()
                .str.to_uppercase()
                .alias("name_clean"),
            ])

            .with_columns([
                (
                    pl.when(pl.col("document_clean").str.len_chars() == 11)
                    .then(pl.lit(TipoDocumentoFornecedor.CPF.value))
                    .when(pl.col("document_clean").str.len_chars() == 14)
                    .then(pl.lit(TipoDocumentoFornecedor.CNPJ.value))
                    .otherwise(pl.lit(TipoDocumentoFornecedor.DESCONHECIDO.value))
                ).cast(pl.Int32).alias("document_type")
            ])

            .with_columns([
                pl.when(pl.col("document_type") != TipoDocumentoFornecedor.DESCONHECIDO.value)
                .then(pl.col("document_clean"))
                .when(
                    pl.col("document_type") == TipoDocumentoFornecedor.CNPJ.value
                ).then(
                    pl.col("document_clean")
                )
                .otherwise(pl.col("name_clean"))
                .alias("supplier_key")
            ])

            .with_columns([
                pl.col("supplier_key")
                .hash(seed=NUMERIC_HASH_SEED)
                .alias("fornecedor_id"),
            ])
        )

        cd_ceaps = cd_ceaps.join(
            identificators,
            left_on="idDeputado",
            right_on="identificador",
            how="inner",
            suffix="_id"
        )

        cd_ceaps = cd_ceaps.join(
            mandates,
            left_on=["pessoa_publica_id", "codigoLegislatura"],
            right_on=["pessoa_publica_id", "legislatura_id"],
            how="inner",
            suffix="_mandate"
        )

        mapping_df = pl.DataFrame(
            [
                {
                    "numeroSubCota": k[0],
                    "numeroEspecificacaoSubCota": k[1],
                    "categoria": v[0],
                    "subcategoria": v[1],
                }
                for k, v in CEAP_CATEGORIES_STRUCTMAP.items()
            ],
            schema={
                "numeroSubCota": pl.Int64,
                "numeroEspecificacaoSubCota": pl.Int64,
                "categoria": pl.Int32,
                "subcategoria": pl.Int32
            }
        ).lazy()

        cd_ceaps = cd_ceaps.join(
            mapping_df,
            on=["numeroSubCota", "numeroEspecificacaoSubCota"],
            how="left"
        )

        ceap_reimbursements_op = cd_ceaps.select(
            pl.col("id").cast(pl.UInt64),
            pl.col("id_mandate").cast(pl.UInt64).alias("mandato_id"),
            pl.col("categoria").cast(pl.Int32).fill_null(0),
            pl.col("subcategoria").cast(pl.Int32).fill_null(0),

            (
                pl.when(pl.col("descricaoEspecificacao").str.len_chars() != 0)
                .then(pl.col("descricaoEspecificacao"))
                .otherwise(pl.lit(None))
            ).cast(pl.String).alias("descricao_especificacao"),

            pl.col("fornecedor_id").cast(pl.UInt64),
            pl.col("document_type").cast(pl.Int32).alias("tipo_documento_fornecedor"),
            pl.col("valorGlosa").fill_null(0).cast(pl.Decimal(precision=18, scale=2)).alias("valor_glosa"),
            pl.col("valorDocumento").fill_null(0).cast(pl.Decimal(precision=18, scale=2)).alias("valor_documento"),
            pl.col("valorLiquido").fill_null(0).cast(pl.Decimal(precision=18, scale=2)).alias("valor_liquido"),
            pl.col("dataEmissao").str.strptime(pl.Datetime, strict=False).cast(pl.Datetime).alias("data_emissao")
        ).unique(subset=["id"])

        ceap_reimbursements_op = ceap_reimbursements_op.sort(
            by=["mandato_id", "categoria", "subcategoria", "data_emissao"]
        )

        ceap_reimbursements_proof_op = (
            cd_ceaps
            .filter(pl.col("urlDocumento").is_not_null() & (pl.col("urlDocumento").str.len_chars() != 0))
            .with_columns(
                pl.col("id").alias("ceap_id")
            )
            .select(
                pl.struct(pl.all(), pl.lit("reimbursement_proof")).hash(seed=NUMERIC_HASH_SEED).cast(pl.UInt64).alias("id"),
                pl.col("urlDocumento").cast(pl.String).alias("fonte"),
                pl.lit(None).cast(pl.String).alias("descricao_adicional"),
                pl.col("ceap_id").cast(pl.UInt64)
            )
        ).unique(subset="id")

        ceap_reimbursements_proof_op = ceap_reimbursements_proof_op.sort(
            by=["ceap_id", "fonte"]
        )

        CD_CEAPS_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True, parents=True)
        CD_CEAPS_PROOF_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True, parents=True)

        ceap_reimbursements_op.sink_parquet(CD_CEAPS_OUTPUT_PARQUETS, compression="snappy")
        ceap_reimbursements_proof_op.sink_parquet(CD_CEAPS_PROOF_OUTPUT_PARQUETS, compression="snappy")
        logger.info("done")


script_instance = CamaraDosDeputadosCeapsDataScript()
