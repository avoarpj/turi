from logging import Logger

import polars as pl
import polars.selectors as cs

from avoar.core.opendata.amendment.domain import TipoAutoria
from config.projectsettings.settings import (
    NUMERIC_HASH_SEED,
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
)
from config.projectsettings.scripts import (
    PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS,
    CD_DEPUTIES_HISTORY_RAW_PARQUETS,
    CD_MANDATES_OUTPUT_PARQUETS,
    CD_LEGISLATURES_OUTPUT_PARQUETS,
)
from infra.datascript.DataScript import DataScript
from scripts.bricks.parquet_order import FINAL_PARQUET_SORT_KEYS


GOV_AMENDMENTS_FEDERAL_DEPUTIES_AUTHORSHIP_RAW_PARQUETS = (
    BASE_DIR
    / "downloads"
    / "gov"
    / "amendments"
    / "*.parquet"
)
GOV_AMENDMENTS_FEDERAL_DEPUTIES_AUTHORSHIP_OUTPUT_DIR = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_amendment_authorship"
    / "gov.parquet"
)

nullish = ["Sem Informação", "Sem informação", "S/I"]

class AmendmentsFederalDeputiesAuthorshipDatascript(DataScript):
    script_id = "gov_amendments_authorship"
    lifetime = "0 6 */1 * *"

    source = "Portal da Transparência; Câmara dos Deputados; SDS"
    source_url = "https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares/UNICO"
    description = (
        "Autoria de emendas por deputados federais, vinculada aos mandatos da Câmara."
    )

    input_paths = [
        GOV_AMENDMENTS_FEDERAL_DEPUTIES_AUTHORSHIP_RAW_PARQUETS,
        PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS,
        CD_DEPUTIES_HISTORY_RAW_PARQUETS,
        CD_MANDATES_OUTPUT_PARQUETS,
        CD_LEGISLATURES_OUTPUT_PARQUETS,
    ]
    output_paths = [
        GOV_AMENDMENTS_FEDERAL_DEPUTIES_AUTHORSHIP_OUTPUT_DIR,
    ]

    dependencies = [
        "camaradosdeputados_legislatures",
        "camaradosdeputados_mandate",
        "public_people",
    ]
    tags = []

    def process_data(self, logger: Logger):
        amendments: pl.LazyFrame | None = None

        for file in GOV_AMENDMENTS_FEDERAL_DEPUTIES_AUTHORSHIP_RAW_PARQUETS.parent.glob("*.parquet"):
            lf = pl.scan_parquet(file)
            schema = lf.collect_schema().names()

            # column that only exists in "EmendasParlamentares.csv"
            if "Nome Plano Orçamentário" in schema:
                amendments = lf
                break

        if amendments is None:
            logger.error("amendments csv not found")
            return

        amendments = (
            amendments.filter(
                ~(pl.col("Código da Emenda") == "Sem informação")
            )
            .with_columns(
                pl.col("Código da Emenda").hash(seed=NUMERIC_HASH_SEED).alias("emenda_id")
            )
            .with_columns(
                cs.string().replace(nullish, None)
            )
            .unique(subset="emenda_id")
        )

        # podem ser associadas diretamente a uma entidade (parlamentares)
        deterministic_authorship_lf = (
            amendments.filter(
                (pl.col("Tipo de Emenda") == "Emenda Individual - Transferências com Finalidade Definida")
                |
                (pl.col("Tipo de Emenda") == "Emenda Individual - Transferências Especiais")
            )
        )

        # não podem ser associadas diretamente a uma entidade (bancadas, relatores, etc)
        undeterministic_authorship_lf = (
            amendments.filter(
                (pl.col("Tipo de Emenda") == "Emenda de Relator")
                |
                (pl.col("Tipo de Emenda") == "Emenda de Bancada")
                |
                (pl.col("Tipo de Emenda") == "Emenda de Comissão")
            )
        )

        deterministic_authorship = self._process_deterministic_authorship(deterministic_authorship_lf)
        undeterministic_authorsip = self._process_undeterministic_authorship(undeterministic_authorship_lf)

        amendments_final = pl.concat([deterministic_authorship, undeterministic_authorsip]).unique(subset="emenda_id")

        amendments_final = amendments_final.sort(
            by=FINAL_PARQUET_SORT_KEYS["opendata_amendment_authorship"]
        )

        GOV_AMENDMENTS_FEDERAL_DEPUTIES_AUTHORSHIP_OUTPUT_DIR.parent.mkdir(parents=True, exist_ok=True)
        amendments_final.sink_parquet(GOV_AMENDMENTS_FEDERAL_DEPUTIES_AUTHORSHIP_OUTPUT_DIR, compression="snappy")


    def _process_deterministic_authorship(self, amendments: pl.LazyFrame):
        identificators = pl.scan_parquet(PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS)
        sds_history = (
            pl.scan_parquet(CD_DEPUTIES_HISTORY_RAW_PARQUETS)
            .select(pl.col("dados").list.explode())
            .unnest("dados")
        )
        mandates = pl.scan_parquet(CD_MANDATES_OUTPUT_PARQUETS)
        legislatures = pl.scan_parquet(CD_LEGISLATURES_OUTPUT_PARQUETS)

        sds_history_keys = sds_history.collect_schema().names()
        sds_history_newkeys = {key: f"{key}_sds" for key in sds_history_keys}

        sds_history = (
            sds_history
            .rename(sds_history_newkeys)
            .sort(by="id_sds")
            .with_columns(
                pl.col("id_sds").cast(pl.String),
                pl.col("idLegislatura_sds").cast(pl.String)
            )
        )

        legislatures = (
            legislatures
            .with_columns(
                pl.col("data_inicio").dt.year().cast(pl.Int32).alias("start_year"),
                pl.col("data_fim").dt.year().cast(pl.Int32).alias("end_year"),
                pl.col("id").cast(pl.String).alias("legislature_id_str")
            )
        )

        mandates = (
            mandates
            .filter(pl.col("orgao_id") == "cd")
            .with_columns(
                pl.col("id").cast(pl.String).alias("mandate_id_raw"),
                pl.col("legislatura_id").cast(pl.String).alias("idLegislatura_mandate_str")
            )
        )

        identificators = identificators.filter(pl.col("fonte") == "camaradosdeputados")

        identificators = (
            identificators
            .join(
                other=sds_history,
                left_on="identificador",
                right_on="id_sds",
                how="left"
            )
            .join(
                other=mandates,
                left_on=["pessoa_publica_id", "idLegislatura_sds"],
                right_on=["pessoa_publica_id", "idLegislatura_mandate_str"],
                suffix="_mandate",
                how="left"
            )
            .with_columns(
                pl.col("nome_sds")
                .str.normalize("NFD")
                .str.replace_all(r"\p{Mn}", "")
                .str.to_lowercase()
                .alias("nome_norm")
            )
        )

        amendments_with_leg = (
            amendments
            .with_columns(
                pl.col("Ano da Emenda").cast(pl.Int32).alias("ano_emenda_int"),
                pl.col("Nome do Autor da Emenda")
                .str.normalize("NFD")
                .str.replace_all(r"\p{Mn}", "")
                .str.to_lowercase()
                .alias("name_norm")
            )
            .join_where(
                legislatures,
                pl.col("ano_emenda_int") >= pl.col("start_year"),
                pl.col("ano_emenda_int") <= pl.col("end_year"),
                suffix="_legislature"
            )
        )

        amendments_final = (
            amendments_with_leg
            .join(
                identificators,
                left_on=["name_norm", "legislature_id_str"],
                right_on=["nome_norm", "idLegislatura_sds"],
                how="left",
                suffix="_identificator"
            )
            .with_columns(
                pl.when(
                    pl.col("Tipo de Emenda") == "Emenda Individual - Transferências com Finalidade Definida"
                ).then(
                    pl.lit(TipoAutoria.INDIVIDUAL_COM_FINALIDADE.value)
                ).when(
                    pl.col("Tipo de Emenda") == "Emenda Individual - Transferências Especiais"
                ).then(
                    pl.lit(TipoAutoria.INDIVIDUAL_ESPECIAL.value)
                ).alias("tipo_autoria"),
                
                pl.col("mandate_id_raw").cast(pl.UInt64).alias("mandato_id"),
                pl.col("Nome do Autor da Emenda").alias("nome_autor")
            )
            .select(
                "emenda_id",
                "tipo_autoria",
                "mandato_id",
                "nome_autor"
            )
        )

        return amendments_final

    def _process_undeterministic_authorship(self, amendments: pl.LazyFrame):
        amendments_final = (
            amendments
            .with_columns(
                pl.when(
                    pl.col("Tipo de Emenda") == "Emenda de Relator"
                ).then(
                    pl.lit(TipoAutoria.RELATOR.value)
                ).when(
                    pl.col("Tipo de Emenda") == "Emenda de Bancada"
                )
                .then(
                    pl.lit(TipoAutoria.BANCADA.value)
                )
                .when(
                    pl.col("Tipo de Emenda") == "Emenda de Comissão"
                ).then(
                    pl.lit(TipoAutoria.COMISSAO.value)
                )
                .alias("tipo_autoria"),
    
                pl.lit(None, dtype=pl.UInt64).alias("mandato_id"),
                pl.col("Nome do Autor da Emenda").alias("nome_autor")
            )
            .select(
                "emenda_id",
                "tipo_autoria",
                "mandato_id",
                "nome_autor"
            )
        )

        return amendments_final

script_instance = AmendmentsFederalDeputiesAuthorshipDatascript()
