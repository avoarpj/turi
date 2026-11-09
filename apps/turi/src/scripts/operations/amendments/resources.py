from logging import Logger

import polars as pl
import polars.selectors as cs

from config.projectsettings.settings import (
    NUMERIC_HASH_SEED,
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
)
from infra.datascript.DataScript import DataScript
from scripts.bricks.parquet_order import FINAL_PARQUET_SORT_KEYS


GOV_AMENDMENTS_RESOURCE_RAW_PARQUETS = (
    BASE_DIR
    / "downloads"
    / "gov"
    / "amendments"
    / "*.parquet"
)
GOV_AMENDMENTS_RESOURCE_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_amendment_resource"
    / "gov.parquet"
)

nullish = ["Sem Informação", "Sem informação", "S/I", "-14"]

UF_MAP = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA",
    "31": "MG", "32": "ES", "33": "RJ", "35": "SP",
    "41": "PR", "42": "SC", "43": "RS",
    "50": "MS", "51": "MT", "52": "GO", "53": "DF"
}

class AmendmentResourcesDatascript(DataScript):
    script_id = "gov_amendments_resource"
    lifetime = "0 6 * * *"

    source = "Portal da Transparência"
    source_url = "https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares/UNICO"
    description = (
        "Recursos financeiros das emendas parlamentares por execução e localidade."
    )

    input_paths = [
        GOV_AMENDMENTS_RESOURCE_RAW_PARQUETS,
    ]
    output_paths = [
        GOV_AMENDMENTS_RESOURCE_OUTPUT_PARQUETS,
    ]

    dependencies = []
    tags = []

    def _convert_ibge_to_uf(self) -> pl.Expr:
        return (
            pl.col("Código UF IBGE")
                .cast(pl.String)
                .str.strip_chars_start("0")
                .str.slice(0, 2) 
                .replace_strict(UF_MAP, default=None)
        )
        
    def process_data(self, logger: Logger):
        amendments: pl.LazyFrame | None = None

        for file in GOV_AMENDMENTS_RESOURCE_RAW_PARQUETS.parent.glob("*.parquet"):
            lf = pl.scan_parquet(file)
            schema = lf.collect_schema().names()

            # column that only exists in "EmendasParlamentares.csv"
            if "Nome Plano Orçamentário" in schema:
                amendments = lf
                break

        if amendments is None:
            logger.error("amendments csv not found")
            return

        items = (
            amendments.filter(
                ~(pl.col("Código da Emenda") == "Sem informação")
            )
            .with_columns(
                pl.col("Código da Emenda").hash(seed=NUMERIC_HASH_SEED).alias("emenda_id"),
                cs.string().replace(nullish, None)
            )
            .with_columns(
                (
                    pl
                    .when(
                        pl.col("Região") == "Nacional"
                    ).then(
                        pl.lit("BR")
                    )
                    .when(
                        pl.col("Código Município IBGE").is_not_null()
                    ).then(
                        pl.col("Código Município IBGE")
                    ).otherwise(
                        self._convert_ibge_to_uf()
                    ).alias("codigo_local")
                ),
                pl.col("Valor Empenhado").str
                    .replace_all(",", ".")
                    .cast(pl.Decimal(18, 2)).alias("valor_empenhado"),
                pl.col("Valor Liquidado").str
                    .replace_all(",", ".")
                    .cast(pl.Decimal(18, 2)).alias("valor_liquidado"),
                pl.col("Valor Pago").str
                    .replace_all(",", ".")
                    .cast(pl.Decimal(18, 2)).alias("valor_pago"),
                pl.col("Valor Restos A Pagar Inscritos").str
                    .replace_all(",", ".")
                    .cast(pl.Decimal(18, 2)).alias("rap_registrado"),
                pl.col("Valor Restos A Pagar Cancelados").str
                    .replace_all(",", ".")
                    .cast(pl.Decimal(18, 2)).alias("rap_cancelado"),
                pl.col("Valor Restos A Pagar Pagos").str
                    .replace_all(",", ".")
                    .cast(pl.Decimal(18, 2)).alias("rap_pago")
            )
            .rename({
                "Código Função": "codigo_funcao",
                "Código Subfunção": "codigo_subfuncao",
                "Código Programa": "codigo_programa",
                "Código Ação": "codigo_acao",
                "Código Plano Orçamentário": "codigo_plano_orcamentario",
                "Nome Plano Orçamentário": "nome_plano_orcamentario"
            })
            .select(
                "emenda_id",
                "codigo_local",
                "codigo_funcao",
                "codigo_subfuncao",
                "codigo_programa",
                "codigo_acao",
                "codigo_plano_orcamentario",
                "nome_plano_orcamentario",
                "valor_empenhado",
                "valor_liquidado",
                "valor_pago",
                "rap_registrado",
                "rap_cancelado",
                "rap_pago"
            )
        )

        items = items.sort(
            by=FINAL_PARQUET_SORT_KEYS["opendata_amendment_resource"]
        )

        GOV_AMENDMENTS_RESOURCE_OUTPUT_PARQUETS.parent.mkdir(parents=True, exist_ok=True)
        items.sink_parquet(GOV_AMENDMENTS_RESOURCE_OUTPUT_PARQUETS, compression="snappy")


script_instance = AmendmentResourcesDatascript()
