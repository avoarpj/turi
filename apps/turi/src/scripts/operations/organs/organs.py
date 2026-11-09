from logging import Logger

import polars as pl

from config.projectsettings.settings import (
    DUMPS_OUTPUT_DIR,
)
from infra.datascript.DataScript import DataScript
from scripts.bricks.parquet_order import FINAL_PARQUET_SORT_KEYS


ORGANS_OUTPUT_PARQUETS = DUMPS_OUTPUT_DIR / "opendata" / "opendata_organ" / "static.parquet"

class OrgansDatascript(DataScript):
    script_id = "organs"
    lifetime = "0 0 1 1 *"

    source = "Avoar"
    source_url = "https://github.com/avoar"
    description = (
        "Catálogo estático dos órgãos públicos referenciados pelos datasets."
    )

    input_paths = [
    ]
    output_paths = [
        ORGANS_OUTPUT_PARQUETS,
    ]

    dependencies = []
    tags = []

    def process_data(self, logger: Logger):
        organs = pl.DataFrame(
            data=[
                {
                    "id": "sf",
                    "nome": "Senado Federal"
                },
                {
                    "id": "cd",
                    "nome": "Câmara dos Deputados"
                },
                {
                    "id": "gov",
                    "nome": "Governo Federal"
                }
            ]
        )

        organs = organs.sort(
            by=FINAL_PARQUET_SORT_KEYS["opendata_organ"]
        )

        ORGANS_OUTPUT_PARQUETS.parent.mkdir(parents=True, exist_ok=True)
        organs.write_parquet(ORGANS_OUTPUT_PARQUETS, compression="zstd")


script_instance = OrgansDatascript()
