from logging import Logger
from functools import lru_cache

import nltk
from unidecode import unidecode
import polars as pl
from config.projectsettings.settings import (
    NUMERIC_HASH_SEED,
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
)
from config.projectsettings.scripts import (
    PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS,
    CD_LEGISLATURES_OUTPUT_PARQUETS,
    CD_DEPUTIES_HISTORY_RAW_PARQUETS,
)
from infra.datascript.DataScript import VENATO_INCLUDED, DataScript
from infra.nltk_setup import setup_nltk
from scripts.checkers.dump_dependencies import check_for_dumps_dependencies


PUBLIC_PEOPLE_RAW_PARQUETS = BASE_DIR / "downloads" / "tse" / "candidates"
PUBLIC_PEOPLE_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_public_people"
    / "public_people.parquet"
)
CD_DEPUTIES_RAW_PARQUETS = (
    BASE_DIR
    / "downloads"
    / "camaradosdeputados"
    / "federal_deputies"
    / "*.parquet"
)

dependencies = [CD_LEGISLATURES_OUTPUT_PARQUETS]


@lru_cache(maxsize=1)
def _nlp_resources():
    setup_nltk()

    return nltk.stem.RSLPStemmer(), nltk.corpus.stopwords.words("portuguese")

def _nlp_batch(s: pl.Series) -> pl.Series:
    stemmer, stopwords = _nlp_resources()
    processed_list: list[str | None] = []
    
    for text in s:
        if text is None:
            processed_list.append(None)
            continue

        text = unidecode(text).lower()
        tokens = [word for word in text.split() if word.isalpha() and word not in stopwords]
        
        stems: list[str] = [stemmer.stem(token) for token in tokens] # type: ignore
        stems.sort()
        
        processed_list.append(" ".join(stems))
        
    return pl.Series(processed_list)

class PublicPeopleDataScript(DataScript):
    script_id = "public_people"
    lifetime = "0 6 1 * *"

    source = "Tribunal Superior Eleitoral; Câmara dos Deputados; SDS"
    source_url = "https://dadosabertos.tse.jus.br/"
    description = (
        "Pessoas públicas das candidaturas e seus identificadores externos na Câmara dos "
        "Deputados."
    )

    input_paths = [
        PUBLIC_PEOPLE_RAW_PARQUETS,
        CD_LEGISLATURES_OUTPUT_PARQUETS,
        CD_DEPUTIES_RAW_PARQUETS,
        CD_DEPUTIES_HISTORY_RAW_PARQUETS,
    ]
    output_paths = [
        PUBLIC_PEOPLE_OUTPUT_PARQUETS,
        PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS,
    ]

    dependencies = [
        "camaradosdeputados_legislatures",
    ]
    tags = [VENATO_INCLUDED]

    def process_data(self, logger: Logger):
        logger.info("process data")

        check_for_dumps_dependencies(dependencies)

        camaradosdeputados_legislatures_dump = pl.scan_parquet(CD_LEGISLATURES_OUTPUT_PARQUETS)
        camaradosdeputados_deputies_raw = (
            pl.scan_parquet(CD_DEPUTIES_RAW_PARQUETS)
            .select(
                pl.col("dados").list.explode()
            ).unnest("dados")
        )
        sds_deputies_history = (
            pl.scan_parquet(CD_DEPUTIES_HISTORY_RAW_PARQUETS)
            .select(
                pl.col("dados").list.explode()
            ).unnest("dados")
        )

        candidates_raw = pl.scan_parquet(PUBLIC_PEOPLE_RAW_PARQUETS / "*.parquet")

        sds_deputies_history = sds_deputies_history.filter(
            pl.col("descricaoStatus") == "Nome no início da legislatura / Partido no início da legislatura"
        ).with_columns(
            pl.col("uri").str.split("/").list.get(-1).alias("deputy_id"),
        )

        camaradosdeputados_deputies_raw = (
            camaradosdeputados_deputies_raw.with_columns(
                pl.col("uri").str.split("/").list.get(-1).alias("deputy_id"),
                pl.col("dataNascimento").str.to_date("%Y-%m-%d", strict=False).alias("dataNascimento"),
                pl.col("nomeCivil").str.to_lowercase().map_batches(
                    function=_nlp_batch,
                    return_dtype=pl.String,
                ).alias("vec_name")
            )
        )

        public_people_op = (
            candidates_raw
            .with_columns(
                pl.when(
                    (pl.col("NR_TITULO_ELEITORAL_CANDIDATO").is_not_null()) & 
                    (~pl.col("NR_TITULO_ELEITORAL_CANDIDATO").is_in(['#NULO#', '-4', 'NÃO DIVULGÁVEL', '']))
                ).then(pl.col("NR_TITULO_ELEITORAL_CANDIDATO"))
                .when(
                    (pl.col("NR_CPF_CANDIDATO").is_not_null())
                    &
                    (~pl.col("NR_CPF_CANDIDATO").is_in(['#NULO#', '-4', 'NÃO DIVULGÁVEL', '', '#NE', '-3']))
                ).then(pl.col("NR_CPF_CANDIDATO"))
                .when(
                    (pl.col("NM_CANDIDATO")).is_not_null()
                    &
                    (~pl.col("NM_CANDIDATO").is_in([""]))
                    &
                    (pl.col("DT_NASCIMENTO").is_not_null())
                ).then(
                    pl.format(
                        "{}_{}_{}",
                        pl.col("NM_CANDIDATO").str.to_uppercase().str.strip_chars(),
                        pl.col("DT_NASCIMENTO"),
                        pl.when(
                            pl.col("SG_UF").is_not_null()
                            &
                            ~pl.col("SG_UF").is_in([""])
                        ).then(pl.col("SG_UF")).otherwise(pl.lit("XX"))
                    )
                ).alias("identifier"),

                pl.when(
                    (pl.col("NR_TITULO_ELEITORAL_CANDIDATO").is_not_null()) & 
                    (~pl.col("NR_TITULO_ELEITORAL_CANDIDATO").is_in(['#NULO#', '-4', 'NÃO DIVULGÁVEL', '']))
                ).then(pl.lit("personal"))
                .when(
                    (pl.col("NR_CPF_CANDIDATO").is_not_null())
                    &
                    (~pl.col("NR_CPF_CANDIDATO").is_in(['#NULO#', '-4', 'NÃO DIVULGÁVEL', '', '#NE', '-3']))
                ).then(pl.lit("personal"))
                .when(
                    (pl.col("NM_CANDIDATO")).is_not_null()
                    &
                    (~pl.col("NM_CANDIDATO").is_in([""]))
                    &
                    (pl.col("DT_NASCIMENTO").is_not_null())
                ).then(pl.lit("biography"))
                .alias("identifier_type"),

                pl.when(
                    (pl.col("NR_TITULO_ELEITORAL_CANDIDATO").is_not_null()) & 
                    (~pl.col("NR_TITULO_ELEITORAL_CANDIDATO").is_in(['#NULO#', '-4', 'NÃO DIVULGÁVEL', '']))
                ).then(pl.lit("titulo_eleitoral"))
                .when(
                    (pl.col("NR_CPF_CANDIDATO").is_not_null())
                    &
                    (~pl.col("NR_CPF_CANDIDATO").is_in(['#NULO#', '-4', 'NÃO DIVULGÁVEL', '', '#NE', '-3']))
                ).then(pl.lit("cpf"))
                .when(
                    (pl.col("NM_CANDIDATO")).is_not_null()
                    &
                    (~pl.col("NM_CANDIDATO").is_in([""]))
                    &
                    (pl.col("DT_NASCIMENTO").is_not_null())
                ).then(pl.lit("bio"))
                .alias("subjective_identifier_type")
            )
        )

        public_people_op = public_people_op.with_columns(
            (pl.col("identifier").hash(seed=NUMERIC_HASH_SEED)).alias("id")
        )

        public_people_op = (
            public_people_op
            .filter(
                pl.col("identifier").is_not_null() & pl.col("identifier_type").is_not_null()
            )
            .with_columns(
                pl.col("DT_NASCIMENTO").str.to_date("%d/%m/%Y", strict=False).alias("DT_NASCIMENTO"),
            )
        )

        # O vínculo externo da Câmara usa somente candidaturas de deputado
        # federal elegíveis pelo recorte histórico da fonte. Pessoas públicas
        # incluem também não eleitos e eleições suplementares.
        cd_public_people = public_people_op.filter(
            (pl.col("CD_CARGO") == "6")
            & (pl.col("CD_TIPO_ELEICAO") == "2")
            & (pl.col("CD_SIT_TOT_TURNO") != "4")
        ).join(
            other=camaradosdeputados_legislatures_dump.select(
                pl.col("id").alias("legislatura_id").cast(pl.Int64),
                pl.col("data_inicio").dt.year().alias("legislature_year")
            ),
            left_on=[
                pl.col("ANO_ELEICAO").str.to_integer().add(1)
            ],
            right_on=["legislature_year"]
        ).sort(
            by=["ANO_ELEICAO", "NM_CANDIDATO", "SG_UF", "NR_CANDIDATO"],
            descending=[True, False, False, False],
        ).unique(
            subset=["id"], keep="first", maintain_order=True,
        ).with_columns(
            pl.int_range(0, pl.len()).alias("turi_seq"),
            pl.col("NM_CANDIDATO").str.to_lowercase().map_batches(
                function=_nlp_batch,
                return_dtype=pl.String,
            ).alias("vec_name"),
        )

        public_people_op = (
            public_people_op
            .sort(
                by=[
                    "ANO_ELEICAO", "NM_CANDIDATO", "SG_UF",
                    "CD_CARGO", "NR_CANDIDATO",
                ],
                descending=[True, False, False, False, False],
            )
            .unique(subset=["id"], keep="first", maintain_order=True)
            .collect()
            .lazy()
        )

        camaradosdeputados_deputies_raw = sds_deputies_history.join(
            other=camaradosdeputados_deputies_raw,
            left_on=["deputy_id"],
            right_on=["deputy_id"],
            suffix="_history"
        )

        tse_identificators = (
            public_people_op.select(
                pl.col("id").alias("pessoa_publica_id"),
                pl.col("identifier").alias("identificador"),
                pl.col("identifier_type").alias("tipo_identificador"),
                pl.lit("tse").alias("fonte")
            )
            .unique(
                subset=["pessoa_publica_id"]
            )
        )

        tse_candidature_identificators = (
            public_people_op.select(
                pl.col("id").alias("pessoa_publica_id"),
                pl.concat_str(["identifier", "NR_CANDIDATO", "ANO_ELEICAO"], separator="-").alias("identificador"),
                pl.col("identifier_type").alias("tipo_identificador"),
                pl.lit("tse").alias("fonte")
            )
            .unique(
                subset=["pessoa_publica_id"]
            )
        )

        # Homônimos não podem depender da ordem arbitrária de unique/join.
        # Priorize o nascimento coincidente antes de escolher cada vínculo.
        camaradosdeputados_deputies_joined = (
            camaradosdeputados_deputies_raw.join(
                other=cd_public_people,
                left_on=["vec_name"],
                right_on=["vec_name"],
                suffix="_public_people"
            )
            .with_columns(
                (pl.col("dataNascimento") == pl.col("DT_NASCIMENTO"))
                .fill_null(False)
                .alias("_same_birth")
            )
            .sort(
                by=["_same_birth", "deputy_id", "id_public_people"],
                descending=[True, False, False],
            )
            .unique(
                subset=["deputy_id"], keep="first", maintain_order=True,
            )
            .unique(
                subset=["turi_seq"], keep="first", maintain_order=True,
            )
        )

        camaradosdeputados_identificators = camaradosdeputados_deputies_joined.select(
            pl.col("id_public_people").alias("pessoa_publica_id"),
            pl.col("deputy_id").alias("identificador"),
            pl.lit("external").alias("tipo_identificador"),
            pl.lit("camaradosdeputados").alias("fonte")
        )

        public_people_op = public_people_op.select(
            pl.col("id"),
            pl.col("NM_CANDIDATO").alias("nome_completo").str.to_lowercase(),
            pl.col("NM_URNA_CANDIDATO").alias("nome").str.to_lowercase(),
            
            pl.when(
                pl.col("CD_GENERO") == "2"
            ).then(pl.lit("M"))
            .when(
                pl.col("CD_GENERO") == "4"
            ).then(pl.lit("F"))
            .otherwise(pl.lit("na"))
            .alias("genero"),

            pl.col("DT_NASCIMENTO").alias("data_nascimento"),
            pl.col("SG_UF_NASCIMENTO").alias("uf_nascimento"),
        ).sort(
            by=[
                "genero",
                "uf_nascimento",
                "nome"
            ]
        )

        identificators_op = pl.concat([tse_identificators, camaradosdeputados_identificators, tse_candidature_identificators]).unique(
            subset=["identificador", "tipo_identificador"],
            keep="first",
            maintain_order=True,
        ).sort(
            by=[
                "fonte",
                "pessoa_publica_id"
            ]
        )

        PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True)
        identificators_op.sink_parquet(PUBLIC_PEOPLE_IDENTIFICATORS_OUTPUT_PARQUETS, compression="snappy")

        PUBLIC_PEOPLE_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True, parents=True)
        public_people_op.sink_parquet(PUBLIC_PEOPLE_OUTPUT_PARQUETS, compression="snappy")

        logger.info("done")


script_instance = PublicPeopleDataScript()
