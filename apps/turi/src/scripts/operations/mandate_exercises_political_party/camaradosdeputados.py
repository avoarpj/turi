from logging import Logger

import polars as pl
from config.projectsettings.settings import (
    NUMERIC_HASH_SEED,
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
    SDS_BASE_URL,
)
from infra.datascript.DataScript import DataScript


CD_MANDATES_EXERCISES_POLITICAL_PARTY_RAW_PARQUETS = (
    BASE_DIR
    / "downloads"
    / "sds"
    / "federal_deputies_history"
    / "*.parquet"
)
CD_MANDATES_EXERCISES_POLITICAL_PARTY_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_mandate_exercises_political_party"
    / "camaradosdeputados.parquet"
)


class CamaraDosDeputadosMandateExercisesPoliticalPartyDataScript(DataScript):
    script_id = "camaradosdeputados_mandate_exercises_political_party"
    lifetime = "0 6 */7 * *"

    source = "Câmara dos Deputados; SDS"
    source_url = f"{SDS_BASE_URL}/public/datasets/historico_deputados_federais/historico.json"
    description = (
        "Filiações partidárias durante os exercícios dos mandatos da Câmara."
    )

    input_paths = [
        CD_MANDATES_EXERCISES_POLITICAL_PARTY_RAW_PARQUETS,
    ]
    output_paths = [
        CD_MANDATES_EXERCISES_POLITICAL_PARTY_OUTPUT_PARQUETS,
    ]

    dependencies = []
    tags = []

    def process_data(self, logger: Logger):
        logger.info("process data")

        party_timeline = (
            pl.scan_parquet(CD_MANDATES_EXERCISES_POLITICAL_PARTY_RAW_PARQUETS)
            .select(pl.col("dados").list.explode()).unnest("dados")
            .with_columns(
                pl.col("siglaPartido").str.replace_all(r"\*", "").str.strip_chars().str.to_uppercase()
            )
            .with_columns(pl.col("dataHora").str.strptime(pl.Datetime))
            .sort(["id", "dataHora"])
            .select([
                pl.col("id").alias("deputy_id"),
                pl.col("dataHora").alias("data_associacao"),
                pl.col("siglaPartido").alias("sigla_partido")
            ])
            .drop_nulls("sigla_partido")
            .filter(
                pl.col("sigla_partido") != pl.col("sigla_partido").shift(1).over("deputy_id").fill_null("")
            )
            .with_columns([
                pl.col("data_associacao").shift(-1).over("deputy_id").alias("data_desassociacao")
            ])
        )

        exercises = (
            pl.scan_parquet(CD_MANDATES_EXERCISES_POLITICAL_PARTY_RAW_PARQUETS)
            .select(pl.col("dados").list.explode()).unnest("dados")
            .filter(
                pl.col("descricaoStatus").str.starts_with("Entrada") |
                pl.col("descricaoStatus").str.starts_with("Saída")
            )
            .with_columns(pl.col("dataHora").str.strptime(pl.Datetime))
            .sort(["id", "dataHora"])
            .with_columns([
                (pl.struct(pl.all()).hash(seed=NUMERIC_HASH_SEED)).alias("exercicio_id")
            ])
            .with_columns([
                pl.col("dataHora").shift(-1).over("id").alias("exercise_end_limit")
            ])
            .filter(pl.col("descricaoStatus").str.starts_with("Entrada"))
            .select([
                pl.col("id").alias("deputy_id"),
                "exercicio_id",
                pl.col("dataHora").alias("exercise_start"),
                "exercise_end_limit"
            ])
        )

        matched_parties = (
            exercises.join(party_timeline, on="deputy_id", how="inner")
            .filter(
                (pl.col("data_associacao") <= pl.col("exercise_end_limit").fill_null(pl.datetime(2100, 1, 1)))
                &
                (pl.col("data_desassociacao").fill_null(pl.datetime(2100, 1, 1)) > pl.col("exercise_start"))
            )
        )

        standard_exercise_parties_op = matched_parties.select([
            (
                pl.struct("exercicio_id", "sigla_partido", "data_associacao")
                .hash(seed=NUMERIC_HASH_SEED)
                .cast(pl.UInt64)
            ).alias("id"),
            "sigla_partido",
            pl.col("exercicio_id").cast(pl.UInt64),
            "data_associacao",
            "data_desassociacao"
        ])

        standard_exercise_parties_op = standard_exercise_parties_op.sort(
            by=["sigla_partido", "exercicio_id", "data_associacao"]
        )

        CD_MANDATES_EXERCISES_POLITICAL_PARTY_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True, parents=True)
        standard_exercise_parties_op.sink_parquet(CD_MANDATES_EXERCISES_POLITICAL_PARTY_OUTPUT_PARQUETS, compression="snappy")

        logger.info("done")


script_instance = CamaraDosDeputadosMandateExercisesPoliticalPartyDataScript()
