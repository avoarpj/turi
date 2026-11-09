from logging import Logger

import polars as pl
import core.events.events as core_events
from config.projectsettings.settings import (
    NUMERIC_HASH_SEED,
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
    SDS_BASE_URL,
)
from config.projectsettings.scripts import (
    CD_MANDATES_OUTPUT_PARQUETS,
    PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS,
)
from infra.datascript.DataScript import DataScript
from scripts.operations.mandate_events.event_description_parser import (
    extract_event_context_expr,
    extract_event_subcontext_expr,
)
from scripts.checkers.dump_dependencies import check_for_dumps_dependencies


CD_MANDATE_EVENTS_RAW_PARQUETS = (
    BASE_DIR
    / "downloads"
    / "sds"
    / "federal_deputies_history"
    / "*.parquet"
)
CD_MANDATE_EVENTS_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_mandate_events"
    / "camaradosdeputados.parquet"
)

class MandateEventsDataScript(DataScript):
    script_id = "camaradosdeputados_mandate_events"
    lifetime = "0 6 * * *"

    source = "Câmara dos Deputados; SDS"
    source_url = f"{SDS_BASE_URL}/public/datasets/historico_deputados_federais/historico.json"
    description = (
        "Eventos históricos dos mandatos dos deputados federais."
    )

    input_paths = [
        CD_MANDATE_EVENTS_RAW_PARQUETS,
        CD_MANDATES_OUTPUT_PARQUETS,
        PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS,
    ]
    output_paths = [
        CD_MANDATE_EVENTS_OUTPUT_PARQUETS,
    ]

    dependencies = [
        "camaradosdeputados_mandate",
        "public_people",
    ]
    tags = []

    def process_data(self, logger: Logger):
        logger.info("processing data")
        check_for_dumps_dependencies([PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS, CD_MANDATES_OUTPUT_PARQUETS])

        public_people_identificators = pl.scan_parquet(
            PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS
        ).filter(pl.col("fonte") == "camaradosdeputados")
        mandates = pl.scan_parquet(CD_MANDATES_OUTPUT_PARQUETS)

        history_events = (
            pl.scan_parquet(CD_MANDATE_EVENTS_RAW_PARQUETS)
            .select(
                pl.col("dados").list.explode()
            )
            .unnest("dados")

            .with_columns(
                (
                    pl.struct(pl.all(), pl.lit("Câmara dos deputados event"))
                ).hash(seed=NUMERIC_HASH_SEED).alias("event_id"),
                
                pl.col("dataHora").str.strptime(pl.Datetime).alias("dataHora"),

                # event type
                (
                    pl.when(
                        pl.col("descricaoStatus").str.to_lowercase().str.starts_with("entrada -")
                    ).then(pl.lit(core_events.INICIO_EXERCICIO))
                    .when(
                        pl.col("descricaoStatus").str.to_lowercase().str.contains("alteração")
                    ).then(pl.lit(core_events.ALTERACAO))
                    .when(
                        pl.col("descricaoStatus").str.to_lowercase().str.starts_with("saída -")
                    ).then(pl.lit(core_events.FIM_EXERCICIO))
                    .otherwise(pl.lit(core_events.DIVERSO))
                ).alias("tipo_evento").cast(pl.Int32),

                # event context
                (
                    extract_event_context_expr().alias("contexto").cast(pl.Int32)
                ),

                # event sub contexts
                (
                    extract_event_subcontext_expr().alias("subcontexto").cast(pl.Int32)
                )
            )
        )

        history_events = history_events.join(
            public_people_identificators,
            left_on=[pl.col("id").cast(pl.String)],
            right_on=[pl.col("identificador").cast(pl.String)],
            suffix="public_people"
        )

        history_events = history_events.join(
            mandates,
            left_on=["pessoa_publica_id", "idLegislatura"],
            right_on=["pessoa_publica_id", "legislatura_id"],
            suffix="_mandate"
        )

        standard_history_events_op = history_events.select(
            pl.col("event_id").alias("id"),
            pl.col("id_mandate").alias("mandato_id"),
            pl.col("tipo_evento"),
            pl.col("contexto"),
            pl.col("subcontexto"),
            pl.col("descricaoStatus").alias("descricao"),
            pl.col("dataHora").alias("data_relacionada")
        )

        standard_history_events_op = standard_history_events_op.sort(
            by=[
                "mandato_id",
                "tipo_evento",
                "data_relacionada"
            ]
        )

        CD_MANDATE_EVENTS_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True)
        standard_history_events_op.sink_parquet(CD_MANDATE_EVENTS_OUTPUT_PARQUETS, compression="snappy")

        logger.info("done")


script_instance = MandateEventsDataScript()
