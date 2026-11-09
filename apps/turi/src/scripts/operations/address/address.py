from logging import Logger

import polars as pl
import polars.selectors as cs

from avoar.core.opendata.address.domain import NivelGeoCodificacao, EspecieEndereco, IndicadorQuantitativoEstabelecimento, SubIndicadorQuantitativoEstabelecimento, FinalidadeConstrucao, EspecieDomicilio
from config.projectsettings.settings import (
    NUMERIC_HASH_SEED,
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
)
from config.projectsettings.scripts import (
    IBGE_ADDRESSES_OUTPUT_PARQUETS,
)
from infra.datascript.DataScript import VENATO_INCLUDED, DataScript
from scripts.bricks.parquet_order import FINAL_PARQUET_SORT_KEYS


IBGE_ADDRESSES_RAW_PARQUETS = BASE_DIR / "downloads" / "ibge" / "enderecos" / "*.parquet"
IBGE_ADDRESSES_COMPLEMENTS_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_address_complement"
    / "opendata_address_complement.parquet"
)

nullish = [""]

class BusinessEstablishmentsDatascript(DataScript):
    script_id = "ibge_addresses"
    lifetime = "0 0 15 */1 *"

    source = "IBGE — CNEFE"
    source_url = "https://ftp.ibge.gov.br/Cadastro_Nacional_de_Enderecos_para_Fins_Estatisticos/Censo_Demografico_2022/Arquivos_CNEFE/"
    description = (
        "Endereços e complementos do Cadastro Nacional de Endereços para Fins "
        "Estatísticos."
    )

    input_paths = [
        IBGE_ADDRESSES_RAW_PARQUETS,
    ]
    output_paths = [
        IBGE_ADDRESSES_OUTPUT_PARQUETS,
        IBGE_ADDRESSES_COMPLEMENTS_OUTPUT_PARQUETS,
    ]

    dependencies = [
        "sds_municipalities",
    ]
    tags = [VENATO_INCLUDED]

    def _format_phone(self, ddd_col: str, tel_col: str) -> pl.Expr:
        d = pl.col(ddd_col).str.strip_chars()
        t = pl.col(tel_col).str.strip_chars()
        
        return (
            pl.when(d.is_not_null() & (d != "") & t.is_not_null() & (t != ""))
            .then(d + t)
            .otherwise(None)
        )

    def process_data(self, logger: Logger):
        files = list(IBGE_ADDRESSES_RAW_PARQUETS.parent.glob("*.parquet"))
        if not files:
            raise FileNotFoundError(f"Nenhum arquivo Parquet encontrado")

        lazyframes_op: list[pl.LazyFrame] = []
        complements_op: list[pl.LazyFrame] = []

        for f in files:
            lf = pl.scan_parquet(f)

            lf = self._process_lf(
                lf,
                logger
            )

            lazyframes_op.append(lf[0])
            complements_op.append(lf[1])

        final_lf_op = pl.concat(lazyframes_op, how="diagonal_relaxed")
        final_complements_lf = pl.concat(complements_op, how="diagonal_relaxed")

        final_lf_op = final_lf_op.sort(
            by=FINAL_PARQUET_SORT_KEYS["opendata_address"]
        )

        IBGE_ADDRESSES_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True)
        final_lf_op.sink_parquet(IBGE_ADDRESSES_OUTPUT_PARQUETS, compression="snappy")

        final_complements_lf = final_complements_lf.sort(
            by=FINAL_PARQUET_SORT_KEYS["opendata_address_complement"]
        )

        IBGE_ADDRESSES_COMPLEMENTS_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True)
        final_complements_lf.sink_parquet(IBGE_ADDRESSES_COMPLEMENTS_OUTPUT_PARQUETS, compression="snappy")

    def _extract_complements(self, lf: pl.LazyFrame) -> pl.LazyFrame:
        pairs = [
            pl.struct([
                pl.col(f"NOM_COMP_ELEM{i}").alias("nome"),
                pl.col(f"VAL_COMP_ELEM{i}").alias("valor")
            ])
            for i in range(1, 6)
        ]

        return (
            lf.select([
                pl.col("id").alias("endereco_id"),
                pl.concat_list(pairs).alias("complementos")
            ])
            .explode("complementos")
            .unnest("complementos")
            .filter(
                pl.col("nome").is_not_null() & 
                (pl.col("nome").str.strip_chars() != "") &
                pl.col("valor").is_not_null() & 
                (pl.col("valor").str.strip_chars() != "")
            )
        )

    def _process_lf(self, lf: pl.LazyFrame, logger: Logger):
        lf = (
            lf.with_columns(
                cs.string().replace(nullish, None)
            )
            .with_columns(
                pl.col("COD_UNICO_ENDERECO").hash(seed=NUMERIC_HASH_SEED).alias("id"),
                pl.struct([pl.col("CEP"), pl.col("NUM_ENDERECO"), pl.col("COD_MUNICIPIO")]).hash(seed=NUMERIC_HASH_SEED).alias("cluster_id"),

                pl.col("LATITUDE").str.replace(",", ".").cast(pl.Float64).alias("LATITUDE"),
                pl.col("LONGITUDE").str.replace(",", ".").cast(pl.Float64).alias("LONGITUDE"),
                
                (
                    pl.when(
                        pl.col("NV_GEO_COORD") == "1"
                    ).then(
                        pl.lit(NivelGeoCodificacao.ORIGINAL)
                    )
                    .when(
                        pl.col("NV_GEO_COORD") == "2"
                    ).then(
                        pl.lit(NivelGeoCodificacao.MODIFICADA)
                    )
                    .when(
                        pl.col("NV_GEO_COORD") == "3"
                    ).then(
                        pl.lit(NivelGeoCodificacao.ESTIMADA)
                    )
                    .when(
                        pl.col("NV_GEO_COORD") == "4"
                    ).then(
                        pl.lit(NivelGeoCodificacao.FACE_QUADRA)
                    )
                    .when(
                        pl.col("NV_GEO_COORD") == "5"
                    ).then(
                        pl.lit(NivelGeoCodificacao.LOCALIDADE)
                    )
                    .when(
                        pl.col("NV_GEO_COORD") == "6"
                    ).then(
                        pl.lit(NivelGeoCodificacao.SETOR_CENSITARIO)
                    )
                ).alias("nivel_geocodificacao"),

                (
                    pl.when(
                        pl.col("COD_ESPECIE") == "1"
                    ).then(
                        pl.lit(EspecieEndereco.PARTICULAR)
                    )
                    .when(
                        pl.col("COD_ESPECIE") == "2"
                    ).then(
                        pl.lit(EspecieEndereco.COLETIVO)
                    )
                    .when(
                        pl.col("COD_ESPECIE") == "3"
                    ).then(
                        pl.lit(EspecieEndereco.AGROPECUARIO)
                    )
                    .when(
                        pl.col("COD_ESPECIE") == "4"
                    ).then(
                        pl.lit(EspecieEndereco.ENSINO)
                    )
                    .when(
                        pl.col("COD_ESPECIE") == "5"
                    ).then(
                        pl.lit(EspecieEndereco.SAUDE)
                    )
                    .when(
                        pl.col("COD_ESPECIE") == "6"
                    ).then(
                        pl.lit(EspecieEndereco.OUTRAS_FINALIDADES)
                    )
                    .when(
                        pl.col("COD_ESPECIE") == "7"
                    ).then(
                        pl.lit(EspecieEndereco.EM_CONSTRUCAO)
                    )
                    .when(
                        pl.col("COD_ESPECIE") == "8"
                    ).then(
                        pl.lit(EspecieEndereco.RELIGIOSO)
                    )
                ).alias("especie_endereco"),

                (
                    pl.when(
                        pl.col("COD_INDICADOR_ESTAB_ENDERECO") == "1"
                    ).then(
                        pl.lit(IndicadorQuantitativoEstabelecimento.UNICO)
                    ).otherwise(
                        pl.lit(IndicadorQuantitativoEstabelecimento.MULTIPLO)
                    )
                ).alias("indicador_quantitativo"),

                (
                    pl.when(
                        pl.col("COD_INDICADOR_ESTAB_ENDERECO") == "2"
                    ).then(
                        pl.lit(SubIndicadorQuantitativoEstabelecimento.MENOR)
                    )
                    .when(
                        pl.col("COD_INDICADOR_ESTAB_ENDERECO") == "3"
                    ).then(
                        pl.lit(SubIndicadorQuantitativoEstabelecimento.MAIOR)
                    )
                    .otherwise(
                        pl.lit(SubIndicadorQuantitativoEstabelecimento.DESCONHECIDO)
                    )
                ).alias("subindicador_quantitativo"),

                (
                    pl.when(
                        pl.col("COD_INDICADOR_CONST_ENDERECO").is_not_null() & (pl.col("COD_INDICADOR_CONST_ENDERECO") != "")
                    ).then(
                        pl.when(
                            pl.col("COD_INDICADOR_CONST_ENDERECO") == "1"
                        ).then(
                            pl.lit(IndicadorQuantitativoEstabelecimento.UNICO)
                        ).otherwise(
                            pl.lit(IndicadorQuantitativoEstabelecimento.MULTIPLO)
                        )
                    ).otherwise(pl.lit(None))
                ).alias("indicador_quantitativo_construcao"),

                (
                    pl.when(
                        pl.col("COD_INDICADOR_CONST_ENDERECO").is_not_null() & (pl.col("COD_INDICADOR_CONST_ENDERECO") != "")
                    ).then(
                        pl.when(
                            pl.col("COD_INDICADOR_CONST_ENDERECO") == "2"
                        ).then(
                            pl.lit(SubIndicadorQuantitativoEstabelecimento.MENOR)
                        )
                        .when(
                            pl.col("COD_INDICADOR_CONST_ENDERECO") == "3"
                        ).then(
                            pl.lit(SubIndicadorQuantitativoEstabelecimento.MAIOR)
                        )
                        .otherwise(
                            pl.lit(SubIndicadorQuantitativoEstabelecimento.DESCONHECIDO)
                        )
                    ).otherwise(pl.lit(None))
                ).alias("subindicador_quantitativo_construcao"),

                # os arquivos do IBGE vieram com o nome errado, mas pode ser que corrijam silenciosamente e isso passe a quebrar.
                (
                    pl.when(
                        pl.col("COD_TIPO_ESPECI") == "101"
                    ).then(
                        pl.lit(EspecieDomicilio.CASA)
                    )
                    .when(
                        pl.col("COD_TIPO_ESPECI") == "102"
                    ).then(
                        pl.lit(EspecieDomicilio.CASA_VILA_CONDOMINIO)
                    )
                    .when(
                        pl.col("COD_TIPO_ESPECI") == "103"
                    ).then(
                        pl.lit(EspecieDomicilio.APARTAMENTO)
                    )
                    .when(
                        pl.col("COD_TIPO_ESPECI") == "104"
                    ).then(
                        pl.lit(EspecieDomicilio.OUTROS)
                    )
                ).alias("especie_domicilio"),

                (
                    pl.when(
                        pl.col("COD_INDICADOR_FINALIDADE_CONST") == "1"
                    ).then(
                        pl.lit(FinalidadeConstrucao.RESIDENCIAL)
                    )
                    .when(
                        pl.col("COD_INDICADOR_FINALIDADE_CONST") == "2"
                    ).then(
                        pl.lit(FinalidadeConstrucao.NAO_RESIDENCIAL)
                    )
                    .when(
                        pl.col("COD_INDICADOR_FINALIDADE_CONST") == "3"
                    ).then(
                        pl.lit(FinalidadeConstrucao.MISTO)
                    )
                    .when(
                        pl.col("COD_INDICADOR_FINALIDADE_CONST") == "4"
                    ).then(
                        pl.lit(FinalidadeConstrucao.INDETERMINADO)
                    )
                    .otherwise(pl.lit(None))
                ).alias("finalidade_construcao")
            )
            .rename({
                "COD_MUNICIPIO": "municipio",
                "COD_DISTRITO": "distrito",
                "COD_SUBDISTRITO": "subdistrito",
                "COD_SETOR": "setor",
                "NUM_QUADRA": "quadra",
                "NUM_FACE": "face",
                "CEP": "cep",
                "DSC_LOCALIDADE": "descricao_localidade",
                "NOM_TIPO_SEGLOGR": "tipo_logradouro",
                "NOM_TITULO_SEGLOGR": "titulo_logradouro",
                "NOM_SEGLOGR": "nome_logradouro",
                "NUM_ENDERECO": "numero_logradouro",
                "DSC_MODIFICADOR": "descricao_modificador",
                "LATITUDE": "latitude",
                "LONGITUDE": "longitude",
                "nivel_geocodificacao": "nivel_geocodificacao",
                "especie_endereco": "especie",
                "DSC_ESTABELECIMENTO": "identificacao_estabelecimento",
                "indicador_quantitativo": "indicador_quantitativo",
                "subindicador_quantitativo": "subindicador_quantitativo",
                "indicador_quantitativo_construcao": "indicador_quantitativo_construcao",
                "subindicador_quantitativo_construcao": "subindicador_quantitativo_construcao",
                "finalidade_construcao": "finalidade_construcao",
                "especie_domicilio": "especie_domicilio"
            })
        )

        complements = self._extract_complements(lf)

        lf = lf.select([
            "id",
            "cluster_id",
            "municipio",
            "distrito",
            "subdistrito",
            "setor",
            "quadra",
            "face",
            "cep",
            "descricao_localidade",
            "tipo_logradouro",
            "titulo_logradouro",
            "nome_logradouro",
            "numero_logradouro",
            "descricao_modificador",
            "latitude",
            "longitude",
            "nivel_geocodificacao",
            "especie",
            "identificacao_estabelecimento",
            "indicador_quantitativo",
            "subindicador_quantitativo",
            "indicador_quantitativo_construcao",
            "subindicador_quantitativo_construcao",
            "finalidade_construcao",
            "especie_domicilio"
        ])

        return [lf, complements]


script_instance = BusinessEstablishmentsDatascript()
