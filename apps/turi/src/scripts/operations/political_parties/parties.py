from logging import Logger

import polars as pl
from config.projectsettings.settings import (
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
)
from infra.datascript.DataScript import DataScript


POLITICAL_PARTIES_RAW_PARQUETS = BASE_DIR / "downloads" / "tse" / "political_parties_directory"
POLITICAL_PARTIES_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_political_party"
    / "tse.parquet"
)

class PoliticalPartiesDataScript(DataScript):
    script_id = "policial_parties"
    lifetime = "0 6 */15 * *"

    source = "Tribunal Superior Eleitoral"
    source_url = "https://cdn.tse.jus.br/estatistica/sead/odsele/orgao_partidario/orgao_partidario.zip"
    description = (
        "Cadastro de partidos políticos consolidado a partir dos diretórios partidários."
    )

    input_paths = [
        POLITICAL_PARTIES_RAW_PARQUETS,
    ]
    output_paths = [
        POLITICAL_PARTIES_OUTPUT_PARQUETS,
    ]

    dependencies = []
    tags = []

    def process_data(self, logger: Logger):
        logger.info("process data")

        parties_directories_raw = (
            pl.scan_parquet(str(POLITICAL_PARTIES_RAW_PARQUETS / "*.parquet"))
            .with_columns(
                pl.col("DT_FIM_VIGENCIA_ORGAO")
                    .str.strptime(pl.Date, "%d/%m/%Y", strict=False)
            ).sort("DT_FIM_VIGENCIA_ORGAO", descending=True)
            .unique(subset=["SG_PARTIDO"], keep="first")
            .with_columns(
                [
                    pl.col("NM_PARTIDO")
                        .str.extract_all(r"\([^)]+\)")
                        .list.eval(pl.element().str.strip_chars("()"))
                        .alias("EX_COMENTARIOS_PARTIDO"),

                    pl.col("NM_PARTIDO")
                        .str.replace_all(r"\(([^)]*)\)", "")
                        .str.strip_chars()
                        .alias("NM_PARTIDO"),
                ]
            )
        )

        standard_parties = parties_directories_raw.select([
            pl.col("NM_PARTIDO").alias("nome"),
            pl.col("SG_PARTIDO").alias("sigla"),
            pl.col("EX_COMENTARIOS_PARTIDO").alias("notas")
        ]).sort(
            by=["sigla"]
        )

        POLITICAL_PARTIES_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True, parents=True)
        standard_parties.sink_parquet(POLITICAL_PARTIES_OUTPUT_PARQUETS, compression="snappy")

        logger.info("done")


script_instance = PoliticalPartiesDataScript()
