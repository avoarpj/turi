from logging import Logger
import polars as pl

from avoar.core.opendata.business.domain import TipoSocio
from config.projectsettings.settings import (
    NUMERIC_HASH_SEED,
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
)
from infra.datascript.DataScript import DataScript
from infra.parquet_sort import sink_sorted_parquet_parts
from scripts.bricks.parquet_order import FINAL_PARQUET_SORT_KEYS


RECEITAFEDERAL_PARTNERSHIP_RAW_PARQUETS = (
    BASE_DIR
    / "downloads"
    / "receitafederal"
    / "socios"
    / "*.parquet"
)
RECEITAFEDERAL_PARTNERSHIP_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_partnerhip"
    / "opendata_partnerhip.parquet"
)

class BusinessPartnershipDatascript(DataScript):
    script_id = "receitafederal_partnership"
    lifetime = "0 0 15 */1 *"

    source = "Receita Federal"
    source_url = "https://arquivos.receitafederal.gov.br"
    description = (
        "Vínculos societários de empresas, pessoas físicas e sócios estrangeiros."
    )

    input_paths = [
        RECEITAFEDERAL_PARTNERSHIP_RAW_PARQUETS,
    ]
    output_paths = [
        RECEITAFEDERAL_PARTNERSHIP_OUTPUT_PARQUETS,
    ]

    dependencies = []
    tags = []

    def process_data(self, logger: Logger):
        files = list(RECEITAFEDERAL_PARTNERSHIP_RAW_PARQUETS.parent.glob("*.parquet"))
        if not files:
            raise FileNotFoundError("Nenhum arquivo Parquet encontrado")

        lazyframes_op: list[pl.LazyFrame] = []

        for f in files:
            lf = pl.scan_parquet(f)
            lf = self._process_lf(lf, logger, deduplicate=False)
            lazyframes_op.append(lf)

        sink_sorted_parquet_parts(
            lazyframes_op,
            RECEITAFEDERAL_PARTNERSHIP_OUTPUT_PARQUETS,
            FINAL_PARQUET_SORT_KEYS["opendata_partnerhip"],
            compression="zstd",
            per_part_unique_subset=["empresa_id", "socio_id"],
        )

    def _process_lf(self, lf: pl.LazyFrame, logger: Logger, *, deduplicate: bool = True) -> pl.LazyFrame:
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
            .with_columns([
                normalizar_nome("nome_do_socio").alias("nome_normalizado"),
                pl.col("nome_do_socio").str.strip_chars().alias("nome"),
                limpar_documento("cnpjcpf_socio").alias("documento"),
                limpar_documento("representante_legal").alias("representante_legal"),
                pl.col("faixa_etaria_socio").fill_null("0").alias("faixa_etaria"),
                pl.col("cnpj_basico").hash(seed=NUMERIC_HASH_SEED).alias("empresa_id")
            ])
            .with_columns(
                pl.concat_str([
                    pl.col("documento"),
                    pl.lit("-"),
                    pl.col("nome_normalizado"),
                    pl.lit("-"),
                    pl.col("faixa_etaria")
                ]).hash(seed=NUMERIC_HASH_SEED).cast(pl.UInt64).alias("socio_id"),

                pl.lit(TipoSocio.PESSOA_FISICA.value).alias("tipo_socio"),
                pl.lit(None).cast(pl.String).alias("nome_socio"),
                pl.lit(None).cast(pl.String).alias("documento_socio"),

                pl.when(
                    pl.col("representante_legal").is_not_null() &
                    (pl.col("representante_legal") != "000000")
                ).then(pl.col("nome_representante_legal"))
                .otherwise(pl.lit(None)).alias("nome_representante_legal"),

                pl.when(
                    pl.col("representante_legal").is_not_null() &
                    (pl.col("representante_legal") != "000000")
                ).then(pl.col("representante_legal"))
                .otherwise(pl.lit(None)).alias("representante_legal"),

                pl.when(
                    pl.col("representante_legal").is_not_null() &
                    (pl.col("representante_legal") != "000000")
                ).then(pl.col("qualificacao_representante_legal"))
                .otherwise(pl.lit(None)).alias("qualificacao_representante_legal"),

                (pl.col("data_de_entrada_sociedade").str.to_date("%Y%m%d", strict=False)).alias("data_entrada")
            )
            .rename({
                "empresa_id": "empresa_id",
                "socio_id": "socio_id",
                "tipo_socio": "tipo_socio",
                "qualificacao_socio": "qualificacao",
                "data_entrada": "data_entrada",
                "nome_socio": "nome_socio",
                "documento_socio": "documento_socio",
                "nome_representante_legal": "nome_representante_legal",
                "representante_legal": "documento_representante_legal",
                "qualificacao_representante_legal": "qualificacao_representante_legal"
            })
            .select([
                "empresa_id",
                "socio_id",
                "tipo_socio",
                "qualificacao",
                "data_entrada",
                "nome_socio",
                "documento_socio",
                "nome_representante_legal",
                "documento_representante_legal",
                "qualificacao_representante_legal"
            ])
        )

        outros_socios = (
            lf.filter(
                (pl.col("identificador_de_socio") != "2") &
                pl.col("nome_do_socio").is_not_null() &
                (pl.col("nome_do_socio") != "")
            )
            .with_columns([
                pl.col("nome_do_socio").str.strip_chars().alias("nome"),
                limpar_documento("cnpjcpf_socio").alias("documento"),
                pl.col("cnpj_basico").hash(seed=NUMERIC_HASH_SEED).alias("empresa_id")
            ])
            .with_columns(
                pl.when(
                    pl.col("identificador_de_socio") == "1"
                ).then(
                    pl.col("documento").str.slice(0, 8).hash(seed=NUMERIC_HASH_SEED)
                ).otherwise(pl.lit(None)).cast(pl.UInt64).alias("socio_id"),

                pl.when(
                    (pl.col("identificador_de_socio") == "1")
                ).then(pl.lit(TipoSocio.PESSOA_JURIDICA.value))
                .when(
                    (pl.col("identificador_de_socio") == "3")
                ).then(pl.lit(TipoSocio.ESTRANGEIRO.value))
                .otherwise(pl.lit(None)).cast(pl.Int32).alias("tipo_socio"),

                pl.when(
                    (pl.col("identificador_de_socio") == "3")
                ).then(pl.col("nome_do_socio"))
                .otherwise(pl.lit(None)).alias("nome_socio"),

                pl.when(
                    (pl.col("identificador_de_socio") == "3")
                ).then(pl.col("documento"))
                .otherwise(pl.lit(None)).alias("documento_socio"),

                pl.when(
                    pl.col("representante_legal").is_not_null() &
                    (pl.col("representante_legal") != "000000")
                ).then(pl.col("nome_representante_legal"))
                .otherwise(pl.lit(None)).alias("nome_representante_legal"),
                pl.when(
                    pl.col("representante_legal").is_not_null() &
                    (pl.col("representante_legal") != "000000")
                ).then(pl.col("representante_legal"))
                .otherwise(pl.lit(None)).alias("representante_legal"),
                pl.when(
                    pl.col("representante_legal").is_not_null() &
                    (pl.col("representante_legal") != "000000")
                ).then(pl.col("qualificacao_representante_legal"))
                .otherwise(pl.lit(None)).alias("qualificacao_representante_legal"),

                (pl.col("data_de_entrada_sociedade").str.to_date("%Y%m%d", strict=False)).alias("data_entrada")
            )
            .rename({
                "empresa_id": "empresa_id",
                "socio_id": "socio_id",
                "tipo_socio": "tipo_socio",
                "qualificacao_socio": "qualificacao",
                "data_entrada": "data_entrada",
                "nome_socio": "nome_socio",
                "documento_socio": "documento_socio",
                "nome_representante_legal": "nome_representante_legal",
                "representante_legal": "documento_representante_legal",
                "qualificacao_representante_legal": "qualificacao_representante_legal"
            })
            .select([
                "empresa_id",
                "socio_id",
                "tipo_socio",
                "qualificacao",
                "data_entrada",
                "nome_socio",
                "documento_socio",
                "nome_representante_legal",
                "documento_representante_legal",
                "qualificacao_representante_legal"
            ])
        )

        partnerships_op = pl.concat([socios_fisicos, outros_socios])

        if deduplicate:
            partnerships_op = partnerships_op.unique(subset=["empresa_id", "socio_id"])

        return partnerships_op


script_instance = BusinessPartnershipDatascript()
