from logging import Logger

import polars as pl
from config.projectsettings.settings import (
    NUMERIC_HASH_SEED,
    BASE_DIR,
    SDS_BASE_URL,
)
from config.projectsettings.scripts import (
    CD_MANDATES_OUTPUT_PARQUETS,
    PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS,
    CD_LEGISLATURES_OUTPUT_PARQUETS,
    CANDIDATURES_OUTPUT_PARQUETS,
    ELECTIONS_OUTPUT_PARQUETS,
)
from infra.datascript.DataScript import DataScript
from scripts.checkers.dump_dependencies import check_for_dumps_dependencies
from scripts.bricks.mandate_candidature import link_mandate_candidatures
from scripts.bricks.election_type import ElectionType


CD_MANDATES_RAW_PARQUETS = (
    BASE_DIR
    / "downloads"
    / "sds"
    / "federal_deputies_history"
    / "*.parquet"
)

dependencies = [
    PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS,
    CD_LEGISLATURES_OUTPUT_PARQUETS,
    CANDIDATURES_OUTPUT_PARQUETS,
    ELECTIONS_OUTPUT_PARQUETS,
]

class CamaradosdeputadosMandatesDataScript(DataScript):
    script_id = "camaradosdeputados_mandate"
    lifetime = "0 6 1 * *"

    source = "Câmara dos Deputados; SDS; Tribunal Superior Eleitoral"
    source_url = f"{SDS_BASE_URL}/public/datasets/historico_deputados_federais/historico.json"
    description = (
        "Mandatos da Câmara vinculados às pessoas, legislaturas e candidaturas "
        "eleitorais."
    )

    input_paths = [
        CD_MANDATES_RAW_PARQUETS,
        PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS,
        CD_LEGISLATURES_OUTPUT_PARQUETS,
        CANDIDATURES_OUTPUT_PARQUETS,
        ELECTIONS_OUTPUT_PARQUETS,
    ]
    output_paths = [
        CD_MANDATES_OUTPUT_PARQUETS,
    ]

    dependencies = [
        "camaradosdeputados_legislatures",
        "candidatures",
        "elections",
        "public_people",
    ]
    tags = []

    def process_data(self, logger: Logger):
        logger.info("process data")

        check_for_dumps_dependencies(dependencies)

        public_people_identificators = pl.scan_parquet(
            PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS
        ).filter(pl.col("fonte") == "camaradosdeputados")
        sds_deputies_history = (
            pl.scan_parquet(CD_MANDATES_RAW_PARQUETS)
            .select(
                pl.col("dados").list.explode()
            ).unnest("dados")
            .filter(
                pl.col("descricaoStatus").str.starts_with("Entrada")
            )
            .with_columns(
                pl.col("dataHora").str.strptime(pl.Datetime).alias("dataHora")
            )
            .group_by(["id", "idLegislatura"])
            .agg(
                pl.col("dataHora").min().alias("dataHora")
            )
            .with_columns(
                pl.lit("cd").alias("orgao_id")
            )
        )

        sds_deputies_history = (
            sds_deputies_history
            .join(
                public_people_identificators.select("pessoa_publica_id", "identificador"),
                left_on=pl.col("id").cast(pl.String),
                right_on="identificador",
                how="inner"
            )
        )

        standard_mandates_op = sds_deputies_history.select(
            (pl.struct(
                pl.col("id"),
                pl.col("idLegislatura"),
                pl.lit("cd")
            ).hash(seed=NUMERIC_HASH_SEED)).alias("id"),
            pl.col("pessoa_publica_id"),
            pl.col("idLegislatura").alias("legislatura_id").cast(pl.Int32),
            pl.lit("cd").alias("orgao_id")
        )

        # Electoral context belongs to this source, not to the shared resolver.
        electoral_context = (
            standard_mandates_op.join(
                pl.scan_parquet(CD_LEGISLATURES_OUTPUT_PARQUETS).select(
                    pl.col("id").alias("legislatura_id"), "orgao_id", "data_inicio",
                ), on=["legislatura_id", "orgao_id"], how="left", validate="m:1",
            ).select(
                pl.col("id").alias("mandato_id"),
                (pl.col("data_inicio").dt.year() - 1).alias("ano_eleicao"),
                pl.lit(6, dtype=pl.Int32).alias("codigo_cargo_tse"),
                pl.lit(ElectionType.ORDINARIA.value, dtype=pl.Int32).alias("tipo_eleicao"),
                pl.lit(None, dtype=pl.String).alias("codigo_local"),
            )
        )
        standard_mandates_op = link_mandate_candidatures(
            standard_mandates_op,
            pl.scan_parquet(CANDIDATURES_OUTPUT_PARQUETS),
            pl.scan_parquet(ELECTIONS_OUTPUT_PARQUETS),
            electoral_context,
        ).sort(
            by=[
                "legislatura_id",
                "pessoa_publica_id"
            ]
        )

        CD_MANDATES_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True)
        standard_mandates_op.sink_parquet(CD_MANDATES_OUTPUT_PARQUETS, compression="snappy")

        logger.info("done")


script_instance = CamaradosdeputadosMandatesDataScript()
