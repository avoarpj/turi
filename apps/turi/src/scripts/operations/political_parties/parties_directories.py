from logging import Logger

import polars as pl
from config.projectsettings.settings import (
    NUMERIC_HASH_SEED,
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
)
from config.projectsettings.scripts import (
    SDS_MUNICIPALITIES_OUTPUT_PARQUETS,
)
from infra.datascript.DataScript import DataScript
from scripts.checkers.dump_dependencies import check_for_dumps_dependencies


POLITICAL_PARTIES_DIRECTORIES_RAW_PARQUETS = (
    BASE_DIR
    / "downloads"
    / "tse"
    / "political_parties_directory"
)
POLITICAL_PARTIES_DIRECTORIES_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_political_party_directory"
    / "tse.parquet"
)

dependencies = [SDS_MUNICIPALITIES_OUTPUT_PARQUETS]

class PoliticalPartiesDirectoriesDataScript(DataScript):
    script_id = "political_parties_directories"
    lifetime = "0 6 */7 * *"

    source = "Tribunal Superior Eleitoral; SDS"
    source_url = "https://cdn.tse.jus.br/estatistica/sead/odsele/orgao_partidario/orgao_partidario.zip"
    description = (
        "Diretórios partidários com vigência e localização municipal."
    )

    input_paths = [
        POLITICAL_PARTIES_DIRECTORIES_RAW_PARQUETS,
        SDS_MUNICIPALITIES_OUTPUT_PARQUETS,
    ]
    output_paths = [
        POLITICAL_PARTIES_DIRECTORIES_OUTPUT_PARQUETS,
    ]

    dependencies = [
        "sds_municipalities",
    ]
    tags = []

    def process_data(self, logger: Logger):
        logger.info("process data")

        check_for_dumps_dependencies(dependencies)

        municipalities_dump = pl.scan_parquet(SDS_MUNICIPALITIES_OUTPUT_PARQUETS)
        parties_directories_raw = (
            pl.scan_parquet(POLITICAL_PARTIES_DIRECTORIES_RAW_PARQUETS / "*.parquet")
            .with_columns(
                pl.col("DT_INICIO_VIGENCIA_ORGAO")
                .str.strptime(pl.Date, "%d/%m/%Y", strict=False)
            )
            .with_columns(
                pl.col("DT_FIM_VIGENCIA_ORGAO")
                .str.strptime(pl.Date, "%d/%m/%Y", strict=False)
            ).sort("DT_FIM_VIGENCIA_ORGAO", descending=True)
            .with_columns(
                pl.col("NM_MUNICIPIO")
                .str.normalize("NFD")
                .str.replace_all(r"[\u0300-\u036f]", "")
                .str.replace_all(r" ", "")
                .str.to_lowercase()
                .alias("norm_municipality")
            )
            .unique(subset=["CD_MUNICIPIO", "SG_PARTIDO"])
            .join(
                other=municipalities_dump,
                left_on=[
                    "norm_municipality",
                    "SG_UF"
                ],
                right_on=["nome_normalizado", "uf"],
                how="left"
            )
        )

        column_map = {
            "SG_PARTIDO": "sigla_partido",
            "DT_INICIO_VIGENCIA_ORGAO": "inicio_vigencia",
            "DT_FIM_VIGENCIA_ORGAO": "fim_vigencia",
            "CD_TIPO_ABRANGENCIA": "abrangencia",
            "SG_UF": "uf",
            "NM_MUNICIPIO": "municipio",
            "codigo_ibge": "codigo_ibge_municipio",
            "DS_ENDERECO_ORGAO": "endereco",
            "NR_CEP_ORGAO": "cep",
            "SG_UE": "zona_eleitoral",
            "CD_TIPO_ORGAO_PARTIDARIO": "tipo_diretorio",
            "SQ_ORGAO_PARTIDARIO": "sequencial_tse"
        }

        parties_directories = parties_directories_raw.select([
            pl.col(old).alias(new)
            for old, new in column_map.items()
                if old in parties_directories_raw.columns
        ])

        parties_directories = parties_directories.with_columns(
            (pl.struct([
                pl.col("sigla_partido"),
                pl.col("codigo_ibge_municipio")
            ])
            .hash(seed=NUMERIC_HASH_SEED))
            .cast(pl.UInt64)
            .alias("id")
        ).sort(
            by=pl.col("inicio_vigencia"),
            descending=True
        ).unique(
            subset=pl.col("id")
        )

        standard_parties_directories_op = parties_directories.select(
            pl.col("id"),
            pl.col("sigla_partido"),
            pl.col("inicio_vigencia"),
            pl.col("fim_vigencia"),
            pl.col("abrangencia").cast(pl.Int32),
            pl.col("uf"),
            pl.col("municipio"),
            pl.col("codigo_ibge_municipio"),
            pl.col("endereco"),
            pl.col("cep"),
            pl.col("zona_eleitoral"),
            pl.col("tipo_diretorio").cast(pl.Int32),
            pl.col("sequencial_tse").cast(pl.Int32)
        ).sort(
            by=[
                "sigla_partido",
                "abrangencia",
                "uf",
                "codigo_ibge_municipio",
                "inicio_vigencia"
            ]
        )

        POLITICAL_PARTIES_DIRECTORIES_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True, parents=True)
        standard_parties_directories_op.sink_parquet(POLITICAL_PARTIES_DIRECTORIES_OUTPUT_PARQUETS, compression="snappy")

        logger.info("done")

        
script_instance = PoliticalPartiesDirectoriesDataScript()
