from logging import Logger

import polars as pl
import polars.selectors as cs

from avoar.core.opendata.suppliers.domain import TipoDocumentoFornecedor
from config.projectsettings.settings import (
    NUMERIC_HASH_SEED,
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
)
from infra.datascript.DataScript import DataScript
from scripts.bricks.parquet_order import FINAL_PARQUET_SORT_KEYS


GOV_AMENDMENTS_SERVICES_SUPPLIER_RAW_PARQUETS = (
    BASE_DIR
    / "downloads"
    / "gov"
    / "amendments"
    / "*.parquet"
)
GOV_AMENDMENTS_SERVICES_SUPPLIER_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_services_supplier"
    / "gov_amendments.parquet"
)
GOV_AMENDMENTS_SERVICES_SUPPLIER_NAMES_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_services_supplier_names"
    / "gov_amendments.parquet"
)

nullish = ["Sem Informação", "Sem informação", "S/I"]

class AmendmentSuppliersDatascript(DataScript):
    script_id = "gov_amendments_services_supplier"
    lifetime = "0 6 * * *"

    source = "Portal da Transparência"
    source_url = "https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares/UNICO"
    description = (
        "Fornecedores e seus nomes registrados nos pagamentos de emendas."
    )

    input_paths = [
        GOV_AMENDMENTS_SERVICES_SUPPLIER_RAW_PARQUETS,
    ]
    output_paths = [
        GOV_AMENDMENTS_SERVICES_SUPPLIER_OUTPUT_PARQUETS,
        GOV_AMENDMENTS_SERVICES_SUPPLIER_NAMES_OUTPUT_PARQUETS,
    ]

    dependencies = []
    tags = []

    def process_data(self, logger: Logger):
        agreements: pl.LazyFrame | None = None

        for file in GOV_AMENDMENTS_SERVICES_SUPPLIER_RAW_PARQUETS.parent.glob("*.parquet"):
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
            agreements.with_columns(
                pl.col("Favorecido")
                .str.strip_chars()
                .str.to_uppercase()
                .alias("name_clean"),
                (
                    pl.when(
                        pl.col("Tipo Favorecido") == "Pessoa Fisica"
                    ).then(
                        pl.lit(TipoDocumentoFornecedor.CPF.value)
                    ).when(
                        pl.col("Tipo Favorecido") == "Unidade Gestora"
                    ).then(
                        pl.lit(TipoDocumentoFornecedor.UNIDADE_GESTORA.value)
                    ).when(
                        (pl.col("Tipo Favorecido") == "Inscrição Genérica") | (pl.col("Tipo Favorecido") == "Inscrição Genéric")
                    ).then(
                        pl.lit(TipoDocumentoFornecedor.INSCRICAO_GENERICA.value)
                    ).otherwise(None)
                ).cast(pl.Int32).alias("tipo_documento")
            )
            .with_columns(
                (
                    pl.when(
                        pl.col("tipo_documento") == TipoDocumentoFornecedor.CNPJ.value
                    ).then(
                        pl.col("Código do Favorecido")
                            .str.strip_chars()
                            .str.replace_all(r"\D", "")
                    ).when(
                        pl.col("tipo_documento") == TipoDocumentoFornecedor.CPF.value
                    ).then(
                        pl.col("Código do Favorecido")
                            .str.strip_chars()
                            .str.replace_all(r"[^\d*]", "")
                    ).otherwise(
                        pl.col("Código do Favorecido")
                    )
                ).alias("document_clean")
            )
            .filter(
                pl.col("tipo_documento").is_not_null()
            )
            .with_columns(
                cs.string().replace(nullish, None),
                pl.col("name_clean").hash(seed=NUMERIC_HASH_SEED).alias("name_id"),
                pl.col("document_clean").hash(seed=NUMERIC_HASH_SEED).alias("document_id")
            )
            .select(
                "name_id",
                "document_id",
                "name_clean",
                "document_clean",
                "tipo_documento"
            )
        )

        suppliers = (
            items.select(
                "document_id",
                "document_clean",
                "tipo_documento"
            )
            .rename({
                "document_id": "id",
                "document_clean": "documento",
            })
            .unique(
                subset=[
                    "id"
                ]
            )
        )

        names = (
            items.select(
                "name_id",
                "document_id",
                "name_clean"
            )
            .with_columns(
                pl.lit("govbr").alias("coletado_de_fonte_bruta"),
                pl.lit(None, dtype=pl.String).alias("coletado_de_orgao_id")
            )
            .rename({
                "name_id": "id",
                "document_id": "fornecedor_id",
                "name_clean": "nome"
            })
            .unique(
                subset=[
                    "id",
                    "fornecedor_id"
                ]
            )
        )

        suppliers = suppliers.sort(
            by=FINAL_PARQUET_SORT_KEYS["opendata_services_supplier"]
        )

        GOV_AMENDMENTS_SERVICES_SUPPLIER_OUTPUT_PARQUETS.parent.mkdir(parents=True, exist_ok=True)
        names = names.sort(
            by=FINAL_PARQUET_SORT_KEYS["opendata_services_supplier_names"]
        )

        GOV_AMENDMENTS_SERVICES_SUPPLIER_NAMES_OUTPUT_PARQUETS.parent.mkdir(parents=True, exist_ok=True)
        suppliers.sink_parquet(GOV_AMENDMENTS_SERVICES_SUPPLIER_OUTPUT_PARQUETS, compression="snappy")
        names.sink_parquet(GOV_AMENDMENTS_SERVICES_SUPPLIER_NAMES_OUTPUT_PARQUETS)


script_instance = AmendmentSuppliersDatascript()
