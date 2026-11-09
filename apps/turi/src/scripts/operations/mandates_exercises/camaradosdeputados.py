from logging import Logger

import polars as pl
from config.projectsettings.settings import (
    NUMERIC_HASH_SEED,
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
    SDS_BASE_URL,
)
from infra.datascript.DataScript import DataScript


CD_MANDATE_EXERCISES_RAW_PARQUETS = (
    BASE_DIR
    / "downloads"
    / "sds"
    / "federal_deputies_history"
    / "*.parquet"
)
CD_MANDATE_EXERCISES_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_mandate_exercises"
    / "camaradosdeputados.parquet"
)

class CamaradosdeputadosMandateExercisesDataScript(DataScript):
    script_id = "camaradosdeputados_mandate_exercises"
    lifetime = "0 6 * * *"

    source = "Câmara dos Deputados; SDS"
    source_url = f"{SDS_BASE_URL}/public/datasets/historico_deputados_federais/historico.json"
    description = (
        "Períodos de exercício dos mandatos dos deputados federais."
    )

    input_paths = [
        CD_MANDATE_EXERCISES_RAW_PARQUETS,
    ]
    output_paths = [
        CD_MANDATE_EXERCISES_OUTPUT_PARQUETS,
    ]

    dependencies = []
    tags = []

    def process_data(self, logger: Logger):
        logger.info("process data")

        sds_deputies_history = (
            pl.scan_parquet(CD_MANDATE_EXERCISES_RAW_PARQUETS)
            .select(
                pl.col("dados").list.explode()
            ).unnest("dados")
            .filter(
                pl.col("descricaoStatus").str.starts_with("Entrada") | pl.col("descricaoStatus").str.starts_with("Saída")
            )
            .with_columns(
                pl.col("dataHora").str.strptime(pl.Datetime).alias("dataHora")
            )
            .sort(
                by=["id", "dataHora"]
            )
            .with_columns(
                (
                    pl.struct(pl.all())
                    .hash(seed=NUMERIC_HASH_SEED)
                ).alias("exercisehash_id")
            )
            .with_columns(
                pl.col("dataHora").shift(-1).over("id").alias("next_dataHora"),
                pl.col("descricaoStatus").shift(-1).over("id").alias("next_descricaoStatus")
            )
            .filter(
                pl.col("descricaoStatus").str.starts_with("Entrada")
            )
        )

        exercises_op = sds_deputies_history.select(
            pl.col("exercisehash_id").alias("id"),
            (pl.struct(
                pl.col("id"),
                pl.col("idLegislatura"),
                pl.lit("cd")
            ).hash(seed=NUMERIC_HASH_SEED)).alias("mandato_id"),
            pl.col("dataHora").alias("data_inicio"),
            pl.when(
                pl.col("next_descricaoStatus").str.starts_with("Saída")
            ).then(pl.col("next_dataHora")).otherwise(pl.lit(None, dtype=pl.Datetime)).alias("data_fim")
        ).sort(
            by=[
                "data_inicio",
                "mandato_id"
            ]
        )

        CD_MANDATE_EXERCISES_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True, parents=True)
        exercises_op.sink_parquet(CD_MANDATE_EXERCISES_OUTPUT_PARQUETS, compression="snappy")

        logger.info("done")


script_instance = CamaradosdeputadosMandateExercisesDataScript()
