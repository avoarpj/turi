from logging import Logger

import polars as pl
from config.projectsettings.settings import (
    BASE_DIR,
)
from config.projectsettings.scripts import (
    CD_LEGISLATURES_OUTPUT_PARQUETS,
)
from infra.datascript.DataScript import DataScript


CD_LEGISLATURES_RAW_PARQUETS = BASE_DIR / "downloads" / "camaradosdeputados" / "legislatures"

class CamaraDosDeputadosLegislaturesDataScript(DataScript):
    script_id = "camaradosdeputados_legislatures"
    lifetime = "0 6 31 12 *"

    source = "Câmara dos Deputados"
    source_url = "https://dadosabertos.camara.leg.br/arquivos/legislaturas/json/legislaturas.json"
    description = (
        "Legislaturas da Câmara dos Deputados e suas datas."
    )

    input_paths = [
        CD_LEGISLATURES_RAW_PARQUETS,
    ]
    output_paths = [
        CD_LEGISLATURES_OUTPUT_PARQUETS,
    ]

    dependencies = []
    tags = []

    def process_data(self, logger: Logger):
        legislatures_raw = pl.scan_parquet(CD_LEGISLATURES_RAW_PARQUETS / "*.parquet")

        legislatures_raw = (
            legislatures_raw
            .select(
                pl.col("dados").list.explode()
            ).unnest("dados")
            .with_columns(
                [
                    pl.col("idLegislatura").cast(pl.String).alias("idLegislatura"),
                    pl.col("dataInicio").str.to_date("%Y-%m-%d").alias("dataInicio"),
                    pl.col("dataFim").str.to_date("%Y-%m-%d").alias("dataFim"),
                ]
            )
        )

        standard_legislatures_op = legislatures_raw.select([
            pl.col("idLegislatura").alias("id").cast(pl.Int32),
            pl.col("dataInicio").alias("data_inicio"),
            pl.col("dataFim").alias("data_fim"),
            pl.lit("cd").alias("orgao_id")
        ]).unique(subset=["id", "orgao_id"])

        standard_legislatures_op = standard_legislatures_op.sort(
            by=["data_inicio"]
        )

        CD_LEGISLATURES_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True, parents=True)
        standard_legislatures_op.sink_parquet(CD_LEGISLATURES_OUTPUT_PARQUETS, compression="snappy")

        logger.info("done")


script_instance = CamaraDosDeputadosLegislaturesDataScript()
