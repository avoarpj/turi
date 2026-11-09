from logging import Logger

import polars as pl
import polars.selectors as cs

from config.projectsettings.settings import (
    NUMERIC_HASH_SEED,
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
)
from infra.datascript.DataScript import DataScript


GOV_AMENDMENTS_RAW_PARQUETS = BASE_DIR / "downloads" / "gov" / "amendments" / "*.parquet"
GOV_AMENDMENTS_OUTPUT_DIR = DUMPS_OUTPUT_DIR / "opendata" / "opendata_amendment" / "gov.parquet"

nullish = ["Sem Informação", "Sem informação", "S/I"]

class AmendmentDatascript(DataScript):
    script_id = "gov_amendments"
    lifetime = "0 6 */1 * *"

    source = "Portal da Transparência"
    source_url = "https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares/UNICO"
    description = (
        "Cadastro consolidado das emendas parlamentares."
    )

    input_paths = [
        GOV_AMENDMENTS_RAW_PARQUETS,
    ]
    output_paths = [
        GOV_AMENDMENTS_OUTPUT_DIR,
    ]

    dependencies = []
    tags = []

    def process_data(self, logger: Logger):
        amendments: pl.LazyFrame | None = None

        for file in GOV_AMENDMENTS_RAW_PARQUETS.parent.glob("*.parquet"):
            lf = pl.scan_parquet(file)
            schema = lf.collect_schema().names()

            # column that only exists in "EmendasParlamentares.csv"
            if "Nome Plano Orçamentário" in schema:
                amendments = lf
                break

        if amendments is None:
            logger.error("amendments csv not found")
            return

        items = (
            amendments.filter(
                ~(pl.col("Código da Emenda") == "Sem informação")
            )
            .with_columns(
                pl.col("Código da Emenda").hash(seed=NUMERIC_HASH_SEED).alias("id"),
                pl.col("Ano da Emenda").cast(pl.Int32).alias("Ano da Emenda")
            )
            .select([
                "id",
                "Código da Emenda",
                "Número da emenda",
                "Ano da Emenda",
            ])
            .rename({
                "Código da Emenda": "codigo",
                "Número da emenda": "numero",
                "Ano da Emenda": "ano"
            })
            .unique(
                subset=["id"]
            )
            .sort([
                "ano",
                "codigo",
                "numero"
            ])
            .with_columns(
                cs.string().replace(nullish, None)
            )
        )

        GOV_AMENDMENTS_OUTPUT_DIR.parent.mkdir(parents=True, exist_ok=True)
        items.sink_parquet(GOV_AMENDMENTS_OUTPUT_DIR, compression="snappy")


script_instance = AmendmentDatascript()
