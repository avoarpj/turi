from logging import Logger
import polars as pl

from config.projectsettings.settings import (
    NUMERIC_HASH_SEED,
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
)
from infra.datascript.DataScript import DataScript
from infra.parquet_sort import sink_sorted_parquet_parts
from scripts.bricks.parquet_order import FINAL_PARQUET_SORT_KEYS


RECEITAFEDERAL_PARTNERS_RAW_PARQUETS = (
    BASE_DIR
    / "downloads"
    / "receitafederal"
    / "socios"
    / "*.parquet"
)
RECEITAFEDERAL_PARTNERS_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_partner"
    / "opendata_partner.parquet"
)


class BusinessPartnersDatascript(DataScript):
    script_id = "receitafederal_partners"
    lifetime = "0 0 15 */1 *"

    source = "Receita Federal"
    source_url = "https://arquivos.receitafederal.gov.br"
    description = (
        "Pessoas físicas identificadas no quadro de sócios do CNPJ."
    )

    input_paths = [
        RECEITAFEDERAL_PARTNERS_RAW_PARQUETS,
    ]
    output_paths = [
        RECEITAFEDERAL_PARTNERS_OUTPUT_PARQUETS,
    ]

    dependencies = []
    tags = []

    def process_data(self, logger: Logger):
        files = list(RECEITAFEDERAL_PARTNERS_RAW_PARQUETS.parent.glob("*.parquet"))
        if not files:
            raise FileNotFoundError("Nenhum arquivo Parquet encontrado")

        lazyframes_op: list[pl.LazyFrame] = []

        for f in files:
            lf = pl.scan_parquet(f)
            lf = self._process_lf(lf, logger)
            lf = lf.select("id", "nome", "documento", "faixa_etaria")
            lazyframes_op.append(lf)

        sink_sorted_parquet_parts(
            lazyframes_op,
            RECEITAFEDERAL_PARTNERS_OUTPUT_PARQUETS,
            FINAL_PARQUET_SORT_KEYS["opendata_partner"],
            compression="zstd",
            unique_subset=["id"],
        )

    def _process_lf(self, lf: pl.LazyFrame, logger: Logger) -> pl.LazyFrame:
        def normalizar_nome(col_name: str) -> pl.Expr:
            return (
                pl.col(col_name)
                .str.normalize("NFD")
                .str.replace_all(r"\p{M}", "")
                .str.replace_all(r"\s+", " ")
                .str.strip_chars()
                .str.to_uppercase()
            )

        def limpar_documento(col_name: str) -> pl.Expr:
            return (
                pl.col(col_name)
                .str.replace_all("*", "", literal=True)
                .str.strip_chars()
            )

        socios_fisicos = (
            lf.filter(
                (pl.col("identificador_de_socio") == "2") &
                pl.col("nome_do_socio").is_not_null() &
                (pl.col("nome_do_socio") != "")
            )
            .select([
                normalizar_nome("nome_do_socio").alias("nome_normalizado"),
                pl.col("nome_do_socio").str.strip_chars().alias("nome"),
                limpar_documento("cnpjcpf_socio").alias("documento"),
                pl.col("faixa_etaria_socio").fill_null("0").alias("faixa_etaria")
            ])
            .with_columns(
                pl.concat_str([
                    pl.col("documento"),
                    pl.lit("-"),
                    pl.col("nome_normalizado"),
                    pl.lit("-"),
                    pl.col("faixa_etaria")
                ]).hash(seed=NUMERIC_HASH_SEED).alias("id"),

                pl.when(
                    ~(pl.col("faixa_etaria").is_in(["", None, "0"]))
                ).then(pl.col("faixa_etaria"))
                .otherwise(pl.lit(0))
                .cast(pl.Int32).alias("faixa_etaria")
            )
        )
        return socios_fisicos.unique(subset=["id"])


script_instance = BusinessPartnersDatascript()
