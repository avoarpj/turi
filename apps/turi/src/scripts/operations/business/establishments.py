from logging import Logger

import polars as pl

from config.projectsettings.settings import (
    NUMERIC_HASH_SEED,
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
)
from infra.datascript.DataScript import VENATO_INCLUDED, DataScript
from infra.parquet_sort import sink_sorted_parquet_parts
from scripts.bricks.parquet_order import FINAL_PARQUET_SORT_KEYS
from scripts.bricks.nullish import nullify_strings

from avoar.core.opendata.business.domain import SituacaoCadastral

RECEITAFEDERAL_BUSINESS_ESTABLISHMENTS_RAW_PARQUETS = (
    BASE_DIR
    / "downloads"
    / "receitafederal"
    / "estabelecimentos"
    / "*.parquet"
)
RECEITAFEDERAL_BUSINESS_ESTABLISHMENTS_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_business_establishment"
    / "opendata_business_establishment.parquet"
)
GOV_MUNICIPALITIES_RAW_PARQUETS = (
    BASE_DIR
    / "downloads"
    / "gov"
    / "municipalities"
    / "*.parquet"
)

nullish = [""]

class BusinessEstablishmentsDatascript(DataScript):
    script_id = "receitafederal_business_establishments"
    lifetime = "0 0 15 */1 *"

    source = "Receita Federal; Tesouro Nacional"
    source_url = "https://arquivos.receitafederal.gov.br"
    description = (
        "Estabelecimentos do CNPJ com endereço, atividades e situação cadastral."
    )

    input_paths = [
        RECEITAFEDERAL_BUSINESS_ESTABLISHMENTS_RAW_PARQUETS,
        GOV_MUNICIPALITIES_RAW_PARQUETS,
    ]
    output_paths = [
        RECEITAFEDERAL_BUSINESS_ESTABLISHMENTS_OUTPUT_PARQUETS,
    ]

    dependencies = []
    tags = [VENATO_INCLUDED]

    def _format_phone(self, ddd_col: str, tel_col: str) -> pl.Expr:
        d = pl.col(ddd_col).str.strip_chars()
        t = pl.col(tel_col).str.strip_chars()
        
        return (
            pl.when(d.is_not_null() & (d != "") & t.is_not_null() & (t != ""))
            .then(d + t)
            .otherwise(None)
        )
    
    def parse_cnaes(self, principal_col: str, secundaria_col: str) -> list[pl.Expr]:
        p = pl.col(principal_col).cast(pl.String).str.strip_chars()
        cnae_principal_list = (
            pl.when(p.is_not_null() & (p != ""))
            .then(pl.concat_list([p]))
            .otherwise(pl.lit([], dtype=pl.List(pl.String)))
            .alias("cnae_principal")
        )
        
        s = pl.col(secundaria_col).cast(pl.String).str.strip_chars()
        cnae_secundaria_list = (
            pl.when(s.is_not_null() & (s != ""))
            .then(
                s.str.split(",")
                .list.eval(pl.element().str.strip_chars())
                .list.eval(pl.element().filter((pl.element() != "") & pl.element().is_not_null()))
            )
            .otherwise(pl.lit([], dtype=pl.List(pl.String)))
            .alias("cnaes_secundarios")
        )

        cnaes_todos = (
            pl.concat_list([cnae_principal_list, cnae_secundaria_list])
            .list.unique(maintain_order=True)
            .alias("cnaes_todos")
        )

        return [cnae_principal_list, cnae_secundaria_list, cnaes_todos]

    def process_data(self, logger: Logger):
        gov_municipalities = pl.scan_parquet(GOV_MUNICIPALITIES_RAW_PARQUETS)

        gov_municipalities = (
            gov_municipalities.select(
                "codigo_ibge",
                "codigo_siafi"
            )
        )

        files = list(RECEITAFEDERAL_BUSINESS_ESTABLISHMENTS_RAW_PARQUETS.parent.glob("*.parquet"))
        if not files:
            raise FileNotFoundError(f"Nenhum arquivo Parquet encontrado")

        lazyframes_op: list[pl.LazyFrame] = []

        for f in files:
            lf = pl.scan_parquet(f)

            lf = self._process_lf(
                lf,
                gov_municipalities,
                logger
            )

            lazyframes_op.append(lf)

        sink_sorted_parquet_parts(
            lazyframes_op,
            RECEITAFEDERAL_BUSINESS_ESTABLISHMENTS_OUTPUT_PARQUETS,
            FINAL_PARQUET_SORT_KEYS["opendata_business_establishment"],
            compression="zstd",
            batch_size=8_192,
            range_partition_count=64,
        )

    def _process_lf(self, lf: pl.LazyFrame, gov_municipalities: pl.LazyFrame, logger: Logger):
        lf = (
            lf.join(
                gov_municipalities,
                left_on=["municipio"],
                right_on=["codigo_siafi"]
            )
        )

        lf = (
            lf.with_columns(
                pl.concat_str([
                    pl.col("cnpj_basico").cast(pl.String).str.strip_chars(),
                    pl.col("cnpj_ordem").cast(pl.String).str.strip_chars(),
                    pl.col("cnpj_dv").cast(pl.String).str.strip_chars(),
                ]).alias("cnpj"),
                pl.col("cnpj_basico").hash(seed=NUMERIC_HASH_SEED).alias("empresa_id"),
                (
                    pl.when(
                        pl.col("situacao_cadastral") == "01"
                    ).then(
                        pl.lit(SituacaoCadastral.NULO)
                    )
                    .when(
                        pl.col("situacao_cadastral") == "02"
                    ).then(
                        pl.lit(SituacaoCadastral.ATIVO)
                    )
                    .when(
                        pl.col("situacao_cadastral") == "03"
                    ).then(
                        pl.lit(SituacaoCadastral.SUSPENSO)
                    )
                    .when(
                        pl.col("situacao_cadastral") == "04"
                    ).then(
                        pl.lit(SituacaoCadastral.INAPTO)
                    )
                    .when(
                        pl.col("situacao_cadastral") == "08"
                    ).then(
                        pl.lit(SituacaoCadastral.BAIXADO)
                    )
                ).alias("situacao_cadastral"),
                (
                    pl.when(
                        pl.col("data_situacao_cadastral").is_not_null()
                    ).then(
                        pl.col("data_situacao_cadastral")
                            .str.to_date("%Y%m%d", strict=False)
                    ).otherwise(
                        pl.lit(None)
                    )
                ).alias("data_situacao_cadastral"),
                (
                    pl.when(
                        pl.col("data_de_inicio_atividade").is_not_null()
                    ).then(
                        pl.col("data_de_inicio_atividade")
                            .str.to_date("%Y%m%d")
                    ).otherwise(
                        pl.lit(None)
                    )
                ).alias("data_de_inicio_atividade"),
                *self.parse_cnaes("cnae_fiscal_principal", "cnae_fiscal_secundaria"),
                (
                    pl.concat_list([
                        self._format_phone("ddd_1", "telefone_1"),
                        self._format_phone("ddd_2", "telefone_2")
                    ]).list.drop_nulls()
                ).alias("phone_numbers"),
                (
                    pl.when(
                        (pl.col("ddd_fax").is_not_null()) & (pl.col("fax").is_not_null())
                    ).then(
                        pl.concat_str([
                            pl.col("ddd_fax").cast(pl.String).str.strip_chars(),
                            pl.col("fax").cast(pl.String).str.strip_chars()
                        ])
                    ).otherwise(
                        pl.lit(None, dtype=pl.String)
                    )
                ).alias("fax"),
                (
                    pl.when(
                        pl.col("data_situacao_especial").is_not_null()
                    ).then(
                        pl.col("data_situacao_especial")
                            .str.to_date("%Y%m%d")
                    ).otherwise(
                        pl.lit(None)
                    )
                ).alias("data_situacao_especial"),

                pl.struct([
                    pl.col("cep"),
                    pl.col("numero"),
                    pl.col("codigo_ibge"),
                ]).hash(seed=NUMERIC_HASH_SEED).alias("endereco_cluster_id")
            )
            .with_columns(
                nullify_strings(nullish),
                pl.col("cnpj").hash(seed=NUMERIC_HASH_SEED).alias("id")
            )
            .rename({
                "indicador_matriz_ou_filial": "tipo",
                "nome_da_cidade_no_exterior": "cidade_exterior",
                "pais": "codigo_pais",
                "data_de_inicio_atividade": "data_inicio_atividade",
                "cnaes_todos": "cnaes",
                "tipo_de_logradouro": "endereco_tipo_logradouro",
                "logradouro": "endereco_logradouro",
                "numero": "endereco_numero",
                "complemento": "endereco_complemento",
                "bairro": "endereco_bairro",
                "cep": "endereco_cep",
                "codigo_ibge": "endereco_municipio",
                "correio_eletronico": "email",
                "uf": "endereco_uf",
                "phone_numbers": "telefones"
            })
            .select([
                "id",
                "empresa_id",
                "cnpj",
                "tipo",
                "nome_fantasia",
                "situacao_cadastral",
                "data_situacao_cadastral",
                "motivo_situacao_cadastral",
                "cidade_exterior",
                "codigo_pais",
                "data_inicio_atividade",
                "cnaes",
                "endereco_tipo_logradouro",
                "endereco_logradouro",
                "endereco_numero",
                "endereco_complemento",
                "endereco_bairro",
                "endereco_cep",
                "endereco_uf",
                "endereco_municipio",
                "endereco_cluster_id",
                "telefones",
                "fax",
                "email",
                "situacao_especial",
                "data_situacao_especial"
            ])
        )

        return lf


script_instance = BusinessEstablishmentsDatascript()
