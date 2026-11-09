"""
Esse script somente cria as relações entre emendas parlamentares e fornecedores.
Para a geração de fornecedores através dos dados, veja: services_supplier/amendments.py
"""

from logging import Logger

import polars as pl

from avoar.core.opendata.suppliers.domain import TipoDocumentoFornecedor
from config.projectsettings.settings import (
    NUMERIC_HASH_SEED,
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
)
from infra.datascript.DataScript import DataScript
from scripts.bricks.parquet_order import FINAL_PARQUET_SORT_KEYS


GOV_AMENDMENTS_TO_SERVICES_SUPPLIER_RAW_PARQUETS = (
    BASE_DIR
    / "downloads"
    / "gov"
    / "amendments"
    / "*.parquet"
)
GOV_AMENDMENTS_TO_SERVICES_SUPPLIER_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_amendment_supplier"
    / "gov.parquet"
)

class AmendmentToSuppliersDatascript(DataScript):
    script_id = "gov_amendments_to_services_supplier"
    lifetime = "0 6 * * *"

    source = "Portal da Transparência"
    source_url = "https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares/UNICO"
    description = (
        "Pagamentos de emendas parlamentares aos fornecedores."
    )

    input_paths = [
        GOV_AMENDMENTS_TO_SERVICES_SUPPLIER_RAW_PARQUETS,
    ]
    output_paths = [
        GOV_AMENDMENTS_TO_SERVICES_SUPPLIER_OUTPUT_PARQUETS,
    ]

    dependencies = []
    tags = []

    def process_data(self, logger: Logger):
        agreements: pl.LazyFrame | None = None

        for file in GOV_AMENDMENTS_TO_SERVICES_SUPPLIER_RAW_PARQUETS.parent.glob("*.parquet"):
            lf = pl.scan_parquet(file)
            schema = lf.collect_schema().names()

            # column that only exists in "EmendasParlamentaresFavorecido.csv"
            if "Código do Favorecido" in schema:
                agreements = lf
                break

        if agreements is None:
            logger.error("amendments suppliers csv not found")
            return

        items = (
            agreements
            .filter(
                (pl.col("Código da Emenda") != "Sem informação")
                &
                (pl.col("Código da Emenda").is_not_null())
                &
                (pl.col("Código da Emenda") != "")
                &
                (pl.col("Código do Favorecido") != "Sem informação")
                &
                (pl.col("Código do Favorecido").is_not_null())
            )
            .with_columns(
                (
                    pl.when(
                        pl.col("Tipo Favorecido") == "Pessoa Jurídica"
                    ).then(
                        pl.lit(TipoDocumentoFornecedor.CNPJ)
                    ).when(
                        pl.col("Tipo Favorecido") == "Pessoa Fisica"
                    ).then(
                        pl.lit(TipoDocumentoFornecedor.CPF)
                    ).when(
                        pl.col("Tipo Favorecido") == "Unidade Gestora"
                    ).then(
                        pl.lit(TipoDocumentoFornecedor.UNIDADE_GESTORA)
                    ).when(
                        (pl.col("Tipo Favorecido") == "Inscrição Genérica") | (pl.col("Tipo Favorecido") == "Inscrição Genéric")
                    ).then(
                        pl.lit(TipoDocumentoFornecedor.INSCRICAO_GENERICA)
                    ).otherwise(TipoDocumentoFornecedor.DESCONHECIDO)
                ).alias("document_type")
            )
            .with_columns(
                (
                    pl.when(
                        pl.col("document_type") == TipoDocumentoFornecedor.CNPJ
                    ).then(
                        pl.col("Código do Favorecido")
                            .str.strip_chars()
                            .str.replace_all(r"\D", "")
                    ).when(
                        pl.col("document_type") == TipoDocumentoFornecedor.CPF
                    ).then(
                        pl.col("Código do Favorecido")
                            .str.strip_chars()
                            .str.replace_all(r"[^\d*]", "")
                    ).otherwise(
                        pl.col("Código do Favorecido")
                    )
                ).alias("document_clean")
            )
            .with_columns(
                pl.when(
                    pl.col("document_type") == TipoDocumentoFornecedor.CNPJ
                ).then(
                    pl.col("document_clean").hash(seed=NUMERIC_HASH_SEED).alias("fornecedor_id")
                ).otherwise(
                    pl.col("document_clean").hash(seed=NUMERIC_HASH_SEED).alias("fornecedor_id")
                ),

                pl.col("Código da Emenda").hash(seed=NUMERIC_HASH_SEED).alias("emenda_id"),
                pl.col("Valor Recebido").str
                    .replace_all(",", ".")
                    .cast(pl.Decimal(18, 2)).alias("valor")
            )
            .rename({
                "document_type": "tipo_documento",
            })
            .select(
                "emenda_id",
                "tipo_documento",
                "fornecedor_id",
                "valor"
            )
        )

        items = items.sort(
            by=FINAL_PARQUET_SORT_KEYS["opendata_amendment_supplier"]
        )

        GOV_AMENDMENTS_TO_SERVICES_SUPPLIER_OUTPUT_PARQUETS.parent.mkdir(parents=True, exist_ok=True)
        items.sink_parquet(GOV_AMENDMENTS_TO_SERVICES_SUPPLIER_OUTPUT_PARQUETS, compression="snappy")


script_instance = AmendmentToSuppliersDatascript()
