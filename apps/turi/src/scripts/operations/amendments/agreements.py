from logging import Logger

import polars as pl
import polars.selectors as cs

from config.projectsettings.settings import (
    NUMERIC_HASH_SEED,
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
)
from infra.datascript.DataScript import DataScript
from scripts.bricks.parquet_order import FINAL_PARQUET_SORT_KEYS


GOV_AMENDMENTS_AGREEMENTS_RAW_PARQUETS = (
    BASE_DIR
    / "downloads"
    / "gov"
    / "amendments"
    / "*.parquet"
)
GOV_AMENDMENTS_AGREEMENTS_OUTPUT_DIR = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_amendment_agreement"
    / "gov.parquet"
)

nullish = ["Sem Informação", "Sem informação", "S/I"]

class AmendmentAgreementDatascript(DataScript):
    script_id = "gov_amendments_agreements"
    lifetime = "0 6 */1 * *"

    source = "Portal da Transparência"
    source_url = "https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares/UNICO"
    description = (
        "Convênios associados às emendas parlamentares."
    )

    input_paths = [
        GOV_AMENDMENTS_AGREEMENTS_RAW_PARQUETS,
    ]
    output_paths = [
        GOV_AMENDMENTS_AGREEMENTS_OUTPUT_DIR,
    ]

    dependencies = []
    tags = []

    def process_data(self, logger: Logger):
        agreements: pl.LazyFrame | None = None

        for file in GOV_AMENDMENTS_AGREEMENTS_RAW_PARQUETS.parent.glob("*.parquet"):
            lf = pl.scan_parquet(file)
            schema = lf.collect_schema().names()

            # column that only exists in "EmendasParlamentaresConvenios.csv"
            if "Número Convênio" in schema:
                agreements = lf
                break

        if agreements is None:
            logger.error("amendments agreements csv not found")
            return

        items = (
            agreements.filter(
                ~(pl.col("Número Convênio") == "Sem informação")
            )
            .unique(
                subset=["Número Convênio"]
            )
            .with_columns(
                pl.col("Número Convênio").hash(seed=NUMERIC_HASH_SEED).alias("id"),
                pl.col("Data Publicação Convênio").str.to_date("%d/%m/%Y").alias("data_publicacao"),
                pl.col("Valor Convênio").str
                    .replace_all(",", ".")
                    .cast(pl.Decimal(18, 2))
                    .alias("valor")
            )
            .with_columns(
                cs.string().replace(nullish, None)
            )
            .rename({
                "Número Convênio": "numero",
                "Código Função": "codigo_funcao",
                "Código Subfunção": "codigo_subfuncao",
                "Convenente": "convenente",
                "Objeto Convênio": "objeto"
            })
            .select(
                "id",
                "numero",
                "codigo_funcao",
                "codigo_subfuncao",
                "data_publicacao",
                "convenente",
                "objeto",
                "valor"
            )
        )

        items = items.sort(
            by=FINAL_PARQUET_SORT_KEYS["opendata_amendment_agreement"]
        )

        GOV_AMENDMENTS_AGREEMENTS_OUTPUT_DIR.parent.mkdir(parents=True, exist_ok=True)
        items.sink_parquet(GOV_AMENDMENTS_AGREEMENTS_OUTPUT_DIR, compression="snappy")


script_instance = AmendmentAgreementDatascript()
