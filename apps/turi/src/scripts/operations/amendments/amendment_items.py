from logging import Logger

import polars as pl

from avoar.core.opendata.amendment.domain import TipoItem
from config.projectsettings.settings import (
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
)
from infra.datascript.DataScript import DataScript
from scripts.bricks.parquet_order import FINAL_PARQUET_SORT_KEYS


GOV_AMENDMENTS_ITEMS_RAW_PARQUETS = BASE_DIR / "downloads" / "gov" / "amendments" / "*.parquet"
GOV_AMENDMENTS_ITEMS_OUTPUT_DIR = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_amendment_item"
    / "gov.parquet"
)

class AmendmentItemsDatascript(DataScript):
    script_id = "gov_amendments_items"
    lifetime = "0 6 1 */1 *"

    source = "Portal da Transparência"
    source_url = "https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares/UNICO"
    description = (
        "Itens de execução das emendas parlamentares."
    )

    input_paths = [
        GOV_AMENDMENTS_ITEMS_RAW_PARQUETS,
    ]
    output_paths = [
        GOV_AMENDMENTS_ITEMS_OUTPUT_DIR,
    ]

    dependencies = []
    tags = []

    def process_data(self, logger: Logger):
        amendments: pl.LazyFrame | None = None

        for file in GOV_AMENDMENTS_ITEMS_RAW_PARQUETS.parent.glob("*.parquet"):
            lf = pl.scan_parquet(file)
            schema = lf.collect_schema().names()

            # column that only exists in "EmendasParlamentares.csv"
            if "Nome Plano Orçamentário" in schema:
                amendments = lf
                break

        if amendments is None:
            logger.error("amendments csv not found")
            return

        functions = (
            amendments.unique(
                subset=["Código Função"]
            )
            .with_columns(
                pl.lit(TipoItem.FUNCAO).alias("type")
            )
            .rename({
                "Código Função": "id",
                "Nome Função": "value"
            })
            .select([
                "id",
                "value",
                "type"
            ])
        )

        subfunctions = (
            amendments.unique(
                subset=["Código Subfunção"]
            )
            .with_columns(
                pl.lit(TipoItem.SUBFUNCAO).alias("type")
            )
            .rename({
                "Código Subfunção": "id",
                "Nome Subfunção": "value"
            })
            .select([
                "id",
                "value",
                "type"
            ])
        )

        programs = (
            amendments.unique(
                subset=["Código Programa"]
            )
            .with_columns(
                pl.lit(TipoItem.PROGRAMA).alias("type")
            )
            .rename({
                "Código Programa": "id",
                "Nome Programa": "value"
            })
            .select([
                "id",
                "value",
                "type"
            ])
        )

        actions = (
            amendments.unique(
                subset=["Código Ação"]
            )
            .with_columns(
                pl.lit(TipoItem.ACAO).alias("type")
            )
            .rename({
                "Código Ação": "id",
                "Nome Ação": "value"
            })
            .select([
                "id",
                "value",
                "type"
            ])
        )

        items = (
            pl.concat([
                functions,
                subfunctions,
                programs,
                actions
            ])
        )

        items = items.sort(
            by=FINAL_PARQUET_SORT_KEYS["opendata_amendment_item"]
        )

        GOV_AMENDMENTS_ITEMS_OUTPUT_DIR.parent.mkdir(parents=True, exist_ok=True)
        items.sink_parquet(GOV_AMENDMENTS_ITEMS_OUTPUT_DIR, compression="snappy")


script_instance = AmendmentItemsDatascript()
