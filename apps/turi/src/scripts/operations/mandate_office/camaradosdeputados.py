from logging import Logger

import polars as pl
import glob
from config.projectsettings.settings import (
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
    SDS_BASE_URL,
)
from config.projectsettings.scripts import (
    PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS,
    CD_MANDATES_OUTPUT_PARQUETS,
)
from infra.datascript.DataScript import DataScript
from scripts.checkers.dump_dependencies import check_for_dumps_dependencies


CD_MANDATE_OFFICE_RAW_PARQUETS = (
    BASE_DIR
    / "downloads"
    / "sds"
    / "federal_deputies_detailed"
    / "*.parquet"
)
CD_MANDATE_OFFICE_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_mandate_office"
    / "camaradosdeputados.parquet"
)

files = glob.glob(str(CD_MANDATE_OFFICE_RAW_PARQUETS))
dependencies = [PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS, CD_MANDATES_OUTPUT_PARQUETS]

class CamaradosdeputadosMandateOfficeDataScript(DataScript):
    script_id = "camaradosdeputados_mandate_office"
    lifetime = "0 6 */7 * *"

    source = "Câmara dos Deputados; SDS"
    source_url = f"{SDS_BASE_URL}/public/datasets/historico_deputados_federais/historico.json"
    description = (
        "Gabinetes dos mandatos dos deputados federais."
    )

    input_paths = [
        CD_MANDATE_OFFICE_RAW_PARQUETS,
        PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS,
        CD_MANDATES_OUTPUT_PARQUETS,
    ]
    output_paths = [
        CD_MANDATE_OFFICE_OUTPUT_PARQUETS,
    ]

    dependencies = [
        "camaradosdeputados_mandate",
        "public_people",
    ]
    tags = []

    def process_data(self, logger: Logger):
        logger.info("process data")
        check_for_dumps_dependencies(dependencies)

        public_people_identificators = pl.read_parquet(
            PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS
        ).filter(pl.col("fonte") == "camaradosdeputados")
        mandates = pl.read_parquet(CD_MANDATES_OUTPUT_PARQUETS).filter(pl.col("orgao_id") == "cd")

        sds_deputies_detailed = (
            pl.read_parquet(files)
            .select(
                pl.col("Deputados").list.explode()
            ).unnest("Deputados")
        )

        sds_deputies_detailed = (
            sds_deputies_detailed
            .join(
                public_people_identificators.select("pessoa_publica_id", "identificador"),
                left_on=pl.col("ideCadastro").cast(pl.String),
                right_on="identificador",
                how="inner"
            )
        )

        sds_deputies_detailed = (
            sds_deputies_detailed
            .join(
                mandates,
                left_on=["pessoa_publica_id", "numLegislatura"],
                right_on=["pessoa_publica_id", "legislatura_id"],
                suffix="_mandate"
            )
        )

        standard_offices_op = sds_deputies_detailed.with_columns([
            pl.concat_list(
                pl.col("gabinete").struct.field("telefone")
            )
            .list.drop_nulls()
            .alias("telefones"),

            pl.col("gabinete").struct.field("numero").alias("numero_gabinete"),
            pl.col("gabinete").struct.field("anexo").alias("anexo_gabinete")
        ]).select(
            pl.col("telefones").cast(pl.List(pl.String)),

            pl.col("numero_gabinete").cast(pl.String),
            pl.col("anexo_gabinete").cast(pl.String),
            pl.col("email"),
            pl.col("id").alias("mandato_id")
        )

        standard_offices_op = standard_offices_op.sort(
            by=[
                "anexo_gabinete",
                "numero_gabinete",
                "mandato_id"
            ]
        )

        CD_MANDATE_OFFICE_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True)
        standard_offices_op.write_parquet(CD_MANDATE_OFFICE_OUTPUT_PARQUETS, compression="snappy")
        logger.info("done")


script_instance = CamaradosdeputadosMandateOfficeDataScript()
