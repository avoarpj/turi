from logging import Logger

import polars as pl
import polars.selectors as cs

from config.projectsettings.settings import (
    NUMERIC_HASH_SEED,
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
)
from infra.datascript.DataScript import VENATO_INCLUDED, DataScript
from scripts.bricks.parquet_order import FINAL_PARQUET_SORT_KEYS


RECEITAFEDERAL_BUSINESS_RAW_PARQUETS = (
    BASE_DIR
    / "downloads"
    / "receitafederal"
    / "empresas"
    / "*.parquet"
)
RECEITAFEDERAL_BUSINESS_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_business"
    / "opendata_business.parquet"
)

nullish = [""]

class BusinessDatascript(DataScript):
    script_id = "receitafederal_business"
    lifetime = "0 0 15 */1 *"

    source = "Receita Federal"
    source_url = "https://arquivos.receitafederal.gov.br"
    description = (
        "Cadastro de empresas do CNPJ, identificado pela base de oito dígitos."
    )

    input_paths = [
        RECEITAFEDERAL_BUSINESS_RAW_PARQUETS,
    ]
    output_paths = [
        RECEITAFEDERAL_BUSINESS_OUTPUT_PARQUETS,
    ]

    dependencies = []
    tags = [VENATO_INCLUDED]

    def process_data(self, logger: Logger):
        raw_business = pl.scan_parquet(RECEITAFEDERAL_BUSINESS_RAW_PARQUETS)

        business = (
            raw_business.with_columns(
                pl.col("cnpj_basico").hash(seed=NUMERIC_HASH_SEED).alias("id")
            )
            .rename({
                "cnpj_basico": "base_cnpj",
                "qualificacao_do_responsavel": "qualificacao_responsavel",
                "ente_federativo_responsavel": "ente_federativo"
            })
            .with_columns(
                cs.string().replace(nullish, None)
            )
            .with_columns(
                pl.col("capital_social").str
                    .replace_all(",", ".")
                    .cast(pl.Decimal(precision=18, scale=2))
                .alias("capital_social")
            )
            .select([
                "id",
                "base_cnpj",
                "razao_social",
                "natureza_juridica",
                "qualificacao_responsavel",
                "capital_social",
                "porte",
                "ente_federativo"
            ])
        )

        business = business.sort(
            by=FINAL_PARQUET_SORT_KEYS["opendata_business"]
        )

        RECEITAFEDERAL_BUSINESS_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True)
        business.sink_parquet(RECEITAFEDERAL_BUSINESS_OUTPUT_PARQUETS, compression="zstd")


script_instance = BusinessDatascript()
