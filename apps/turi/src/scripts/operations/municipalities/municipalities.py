from logging import Logger

import polars as pl
from config.projectsettings.settings import (
    BASE_DIR,
    SDS_BASE_URL,
)
from config.projectsettings.scripts import (
    SDS_MUNICIPALITIES_OUTPUT_PARQUETS,
)
from infra.datascript.DataScript import VENATO_INCLUDED, DataScript


SDS_MUNICIPALITIES_RAW_PARQUETS = BASE_DIR / "downloads" / "sds" / "municipalities_centroid"

class SimpleDataServiceDataScript(DataScript):
    script_id = "sds_municipalities"
    lifetime = "0 5 1 */4 *"

    source = "SDS — centroides municipais"
    source_url = f"{SDS_BASE_URL}/public/datasets/centroides-municipios-brasileiros/centroides.json"
    description = (
        "Municípios brasileiros com código IBGE e coordenadas do centroide."
    )

    input_paths = [
        SDS_MUNICIPALITIES_RAW_PARQUETS,
    ]
    output_paths = [
        SDS_MUNICIPALITIES_OUTPUT_PARQUETS,
    ]

    dependencies = []
    tags = [VENATO_INCLUDED]

    def process_data(self, logger: Logger):
        logger.info("process data")

        municipalities_raw = pl.scan_parquet(SDS_MUNICIPALITIES_RAW_PARQUETS / "*.parquet")
        municipalities_raw = municipalities_raw.with_columns(
            [
                pl.int_range(0, pl.len()).alias("turi_seq"),

                pl.col("nome_municipio")
                .str.normalize("NFD")
                .str.replace_all(r"[\u0300-\u036f]", "")
                .str.replace_all(r" ", "")
                .str.to_lowercase()
                .alias("nome_normalizado")
            ]
        )

        standard_municipalities_op = municipalities_raw.select([
            pl.col("codigo_municipio").alias("codigo_ibge"),
            pl.col("nome_municipio").alias("nome"),
            pl.col("nome_normalizado"),
            pl.col("uf"),
            pl.col("latitude").cast(pl.Decimal(9, 6)),
            pl.col("longitude").cast(pl.Decimal(9, 6))
        ]).sort(
            by=[
                "uf",
                "nome_normalizado"
            ]
        )

        SDS_MUNICIPALITIES_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True, parents=True)
        standard_municipalities_op.sink_parquet(SDS_MUNICIPALITIES_OUTPUT_PARQUETS, compression="snappy")
        logger.info("end")


script_instance = SimpleDataServiceDataScript()
