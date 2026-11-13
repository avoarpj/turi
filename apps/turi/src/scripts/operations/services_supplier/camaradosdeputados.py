from logging import Logger

import polars as pl
from avoar.core.opendata.suppliers.domain import TipoDocumentoFornecedor
from config.projectsettings.settings import (
    NUMERIC_HASH_SEED,
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
)
from infra.datascript.DataScript import DataScript
from infra.parquet_staging import staged_nested_parquets


CD_SERVICES_SUPPLIER_RAW_PARQUETS = (
    BASE_DIR
    / "downloads"
    / "camaradosdeputados"
    / "ceaps"
    / "*.parquet"
)
CD_SERVICES_SUPPLIER_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_services_supplier"
    / "camaradosdeputados.parquet"
)
CD_SERVICES_SUPPLIER_NAMES_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_services_supplier_names"
    / "camaradosdeputados.parquet"
)

class CamaradosdeputadosServicesSupplierDataScript(DataScript):
    script_id = "camaradosdeputados_services_supplier"
    lifetime = "0 6 * * *"

    source = "Câmara dos Deputados"
    source_url = "https://www.camara.leg.br/cotas/"
    description = (
        "Fornecedores e seus nomes registrados nas despesas da cota parlamentar."
    )

    input_paths = [
        CD_SERVICES_SUPPLIER_RAW_PARQUETS,
    ]
    output_paths = [
        CD_SERVICES_SUPPLIER_OUTPUT_PARQUETS,
        CD_SERVICES_SUPPLIER_NAMES_OUTPUT_PARQUETS,
    ]

    dependencies = []
    tags = []

    def process_data(self, logger: Logger):
        with staged_nested_parquets(
            CD_SERVICES_SUPPLIER_RAW_PARQUETS,
            work_directory=CD_SERVICES_SUPPLIER_OUTPUT_PARQUETS.parent,
            columns=["cnpjCPF", "fornecedor"],
        ) as raw_ceaps:
            self._process_data(raw_ceaps, logger)

    def _process_data(self, raw_ceaps: pl.LazyFrame, logger: Logger):
        logger.info("process data")

        cd_ceaps = (
            raw_ceaps

            # document and name normalization
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

            .filter(
                pl.col("document_clean").str.len_chars() != 14
            )

            # document type
            .with_columns([
                (
                    pl.when(pl.col("document_clean").str.len_chars() == 11)
                    .then(pl.lit(TipoDocumentoFornecedor.CPF.value))
                    .otherwise(pl.lit(TipoDocumentoFornecedor.DESCONHECIDO.value))
                ).cast(pl.Int32).alias("tipo_documento")
            ])

            .with_columns([
                pl.when(pl.col("tipo_documento") != TipoDocumentoFornecedor.DESCONHECIDO.value)
                .then(pl.col("document_clean"))
                .otherwise(pl.col("name_clean"))
                .alias("supplier_key")
            ])

            .with_columns([
                pl.col("supplier_key")
                .hash(seed=NUMERIC_HASH_SEED)
                .alias("fornecedor_id"),

                pl.col("name_clean")
                .hash(seed=NUMERIC_HASH_SEED)
                .alias("name_id"),
            ])
        )

        services_supplier_op = (
            cd_ceaps
            .select([
                pl.col("fornecedor_id").alias("id"),

                pl.when(pl.col("tipo_documento") != TipoDocumentoFornecedor.DESCONHECIDO.value)
                .then(pl.col("document_clean"))
                .otherwise(pl.lit(None))
                .alias("documento"),

                pl.col("tipo_documento"),
            ])
            .unique(subset=["id"])
            .sort(
                by=[
                    "tipo_documento",
                    "documento"
                ]
            )
        )

        known_docs = (
            cd_ceaps
            .filter(pl.col("tipo_documento") != TipoDocumentoFornecedor.DESCONHECIDO.value)
            .select([
                pl.col("name_id").alias("id"),
                pl.col("name_clean").alias("nome"),
                pl.col("fornecedor_id"),
                pl.lit("cd").alias("coletado_de_orgao_id"),
            ])
            .unique(subset=["id", "fornecedor_id"])
        )

        unknown_docs = (
            cd_ceaps
            .filter(pl.col("tipo_documento") == TipoDocumentoFornecedor.DESCONHECIDO.value)
            .select([
                pl.col("name_id").alias("id"),
                pl.col("name_clean").alias("nome"),
                pl.col("fornecedor_id"),
                pl.lit("cd").alias("coletado_de_orgao_id"),
            ])
            .unique(subset=["id"])
        )

        services_supplier_name_op = (
            pl.concat(
                [
                    known_docs.with_columns(pl.lit(1).alias("priority")),
                    unknown_docs.with_columns(pl.lit(2).alias("priority"))
                ]
            )
            .with_columns(
                pl.lit(None, dtype=pl.String).alias("coletado_de_fonte_bruta")
            )
            .sort(["id", "priority"])
            .unique(subset=["id"], keep="first")
            .drop("priority")
            .sort(
                by=[
                    "fornecedor_id",
                    "nome"
                ]
            )
        )

        CD_SERVICES_SUPPLIER_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True)
        CD_SERVICES_SUPPLIER_NAMES_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True)

        services_supplier_op.sink_parquet(CD_SERVICES_SUPPLIER_OUTPUT_PARQUETS, compression="snappy")
        services_supplier_name_op.sink_parquet(CD_SERVICES_SUPPLIER_NAMES_OUTPUT_PARQUETS, compression="snappy")

        logger.info("end")


script_instance = CamaradosdeputadosServicesSupplierDataScript()
