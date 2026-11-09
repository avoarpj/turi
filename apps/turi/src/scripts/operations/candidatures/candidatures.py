import re
from logging import Logger
from pathlib import Path

import polars as pl

from config.projectsettings.settings import (
    NUMERIC_HASH_SEED,
    BASE_DIR,
)
from config.projectsettings.scripts import (
    CANDIDATURES_OUTPUT_PARQUETS,
    ELECTIONS_ROUNDS_OUTPUT_PARQUETS,
    ELECTIONS_OUTPUT_PARQUETS,
    TSE_MUNICIPALITIES_RAW_PARQUETS,
)
from infra.datascript.DataScript import DataScript
from scripts.bricks.candidature_identity import (
    candidature_id_expr, election_lookup, with_electoral_locality,
)


CANDIDATURES_RAW_PARQUETS = BASE_DIR / "downloads" / "tse" / "candidates" / "*.parquet"
CANDIDATURES_PHOTOS_RAW_DIR = BASE_DIR / "downloads" / "tse" / "candidatures_photos"
CANDIDATURES_ASSETS_DIR = BASE_DIR / "assets" / "candidatures"

_CANDIDATURE_COLUMNS = [
    "id", "eleicao_id", "pessoa_publica_id", "numero_candidato",
    "codigo_local", "codigo_cargo_tse", "sigla_partido", "numero_partido",
]

_PHOTO_DIRECTORY = re.compile(
    r"^foto_cand(?P<year>\d{4})_(?P<uf>[A-Z]{2})_div_[0-9a-f]{8}_[0-9a-f]{8}$"
)
_PHOTO_FILENAME = re.compile(
    r"^F?(?P<uf>[A-Z]{2})(?P<sq>\d+)_div\.(?:jpg|jpeg|png)$",
    re.IGNORECASE,
)
_PHOTO_SUFFIXES = (".jpg", ".jpeg", ".png")


class CandidaturesDataScript(DataScript):
    script_id = "candidatures"
    lifetime = "0 3 1 * *"

    source = "Tribunal Superior Eleitoral"
    source_url = "https://dadosabertos.tse.jus.br/"
    description = (
        "Candidaturas eleitorais vinculadas às eleições e às pessoas públicas, com fotos "
        "disponíveis."
    )

    input_paths = [
        CANDIDATURES_RAW_PARQUETS,
        CANDIDATURES_PHOTOS_RAW_DIR,
        ELECTIONS_ROUNDS_OUTPUT_PARQUETS,
        ELECTIONS_OUTPUT_PARQUETS,
        TSE_MUNICIPALITIES_RAW_PARQUETS,
    ]
    output_paths = [
        CANDIDATURES_OUTPUT_PARQUETS,
    ]

    dependencies = [
        "elections",
    ]
    tags = []

    def process_data(self, logger: Logger):
        candidates_filenum = sum(1 for _ in CANDIDATURES_RAW_PARQUETS.parent.glob("*.parquet"))

        logger.info("found %d files reading %s", candidates_filenum, str(CANDIDATURES_RAW_PARQUETS.parent))

        candidates_with_photo_keys = _process_data(
            pl.scan_parquet(CANDIDATURES_RAW_PARQUETS),
            pl.scan_parquet(TSE_MUNICIPALITIES_RAW_PARQUETS / "*.parquet"),
            election_lookup(
                pl.scan_parquet(ELECTIONS_ROUNDS_OUTPUT_PARQUETS),
                pl.scan_parquet(ELECTIONS_OUTPUT_PARQUETS),
            ),
            include_photo_keys=True,
        )
        CANDIDATURES_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True, parents=True)
        candidates_with_photo_keys.select(_CANDIDATURE_COLUMNS).sink_parquet(
            CANDIDATURES_OUTPUT_PARQUETS, compression="snappy"
        )

        if CANDIDATURES_PHOTOS_RAW_DIR.exists():
            photo_keys = candidates_with_photo_keys.select(
                "id", "ANO_ELEICAO", "SG_UF", "SQ_CANDIDATO", "_photo_key_count"
            ).collect()

            _publish_candidature_photos(
                photo_keys,
                CANDIDATURES_PHOTOS_RAW_DIR,
                CANDIDATURES_ASSETS_DIR,
                logger,
            )



def _process_data(
    candidates_raw: pl.LazyFrame,
    municipalities: pl.LazyFrame,
    elections: pl.LazyFrame,
    *,
    include_photo_keys: bool = False,
) -> pl.LazyFrame:
    candidates_with_elections = with_electoral_locality(
        candidates_raw, municipalities, "CD_CARGO", "SG_UE"
    ).with_columns(
        pl.col("CD_ELEICAO").cast(pl.Int32).alias("codigo_tse"),
        pl.col("CD_CARGO").cast(pl.Int32).alias("codigo_cargo_tse"),
        pl.col("NR_CANDIDATO").cast(pl.Int32).alias("numero_candidato"),
    ).join(elections, on=["codigo_tse", "codigo_local"], how="inner", validate="m:1")

    candidates_with_elections = candidates_with_elections.with_columns(
        pl.when(
            (pl.col("NR_TITULO_ELEITORAL_CANDIDATO").is_not_null()) &
            (~pl.col("NR_TITULO_ELEITORAL_CANDIDATO").is_in(['#NULO#', '-4', 'NÃO DIVULGÁVEL', '']))
        ).then(pl.col("NR_TITULO_ELEITORAL_CANDIDATO"))
        .when(
            (pl.col("NR_CPF_CANDIDATO").is_not_null()) &
            (~pl.col("NR_CPF_CANDIDATO").is_in(['#NULO#', '-4', 'NÃO DIVULGÁVEL', '', '#NE', '-3']))
        ).then(pl.col("NR_CPF_CANDIDATO"))
        .otherwise(
            pl.format(
                "{}_{}_{}",
                pl.col("NM_CANDIDATO").str.to_uppercase().str.strip_chars(),
                pl.col("DT_NASCIMENTO"),
                pl.when(
                    pl.col("SG_UF").is_not_null() & ~pl.col("SG_UF").is_in([""])
                ).then(pl.col("SG_UF")).otherwise(pl.lit("XX"))
            )
        ).alias("identifier")
    )

    candidates_with_elections = (
        candidates_with_elections
        .with_columns([
            pl.col("identifier").hash(seed=NUMERIC_HASH_SEED).alias("pessoa_publica_id")
        ])
        .filter(pl.col("eleicao_id").is_not_null())
    )

    candidate_identity = candidates_with_elections.with_columns([
        candidature_id_expr().alias("_chave_candidatura"),
        pl.col("eleicao_id"),
        pl.col("SG_PARTIDO").alias("sigla_partido"),
        pl.col("NR_PARTIDO").alias("numero_partido").cast(pl.Int32),
        pl.col("NR_CANDIDATO").alias("numero_candidato").cast(pl.Int32),
    ])

    if include_photo_keys:
        candidate_identity = candidate_identity.with_columns(
            pl.struct("ANO_ELEICAO", "SG_UF", "SQ_CANDIDATO")
            .n_unique()
            .over("_chave_candidatura", "pessoa_publica_id")
            .alias("_photo_key_count")
        )

    photo_columns = []
    if include_photo_keys:
        photo_columns = [
            "ANO_ELEICAO", "SG_UF", "SQ_CANDIDATO", "_photo_key_count",
        ]

    lazy_candidatures_op = (
        candidate_identity
        .unique(subset=["_chave_candidatura", "pessoa_publica_id"])
        .with_columns(
            pl.when(pl.len().over("_chave_candidatura") == 1)
            .then(pl.col("_chave_candidatura"))
            .otherwise(
                pl.struct(
                    pl.col("_chave_candidatura"),
                    pl.col("pessoa_publica_id").cast(pl.UInt64),
                ).hash(seed=NUMERIC_HASH_SEED)
            ).alias("id")
        )
        .select(_CANDIDATURE_COLUMNS + photo_columns)
    )

    lazy_candidatures_op = lazy_candidatures_op.sort(
        by=["eleicao_id", "sigla_partido", "pessoa_publica_id"]
    )

    return lazy_candidatures_op


def _publish_candidature_photos(
    photo_keys: pl.DataFrame,
    source_root: Path,
    target_root: Path,
    logger: Logger,
) -> None:
    folders = {}
    for directory in source_root.iterdir():
        if not directory.is_dir():
            continue

        folder_match = _PHOTO_DIRECTORY.fullmatch(directory.name)
        if folder_match is None:
            continue

        folder_key = (folder_match["year"], folder_match["uf"])
        if folder_key in folders:
            raise ValueError(f"Pastas de fotos duplicadas para {folder_key}")

        folders[folder_key] = directory

    candidate_ids = {}
    ambiguous_keys = set()
    ambiguous_candidatures = 0
    for candidature_id, year, uf, sq_candidate, key_count in photo_keys.iter_rows():
        if key_count != 1:
            ambiguous_candidatures += 1
            continue

        if not year or not uf or not sq_candidate:
            continue

        folder_key = (str(year).strip(), str(uf).strip().upper())
        if folder_key not in folders:
            continue

        photo_key = (folder_key, str(sq_candidate).strip())
        if photo_key in candidate_ids and candidate_ids[photo_key] != candidature_id:
            ambiguous_keys.add(photo_key)
            continue

        candidate_ids[photo_key] = candidature_id

    for photo_key in ambiguous_keys:
        del candidate_ids[photo_key]

    folders_with_candidates = {folder_key for folder_key, _ in candidate_ids}
    moved = 0
    duplicate_photos = 0
    target_ready = False
    for folder_key, directory in folders.items():
        if folder_key not in folders_with_candidates:
            continue

        matches = {}
        for source in directory.rglob("*"):
            if not source.is_file():
                continue

            file_match = _PHOTO_FILENAME.fullmatch(source.name)
            if file_match is None or file_match["uf"].upper() != folder_key[1]:
                continue

            photo_key = (folder_key, file_match["sq"])
            if photo_key not in candidate_ids:
                continue

            if photo_key in matches:
                matches[photo_key] = None
                duplicate_photos += 1
            else:
                matches[photo_key] = source

        for photo_key, source in matches.items():
            if source is None:
                continue

            candidature_id = candidate_ids[photo_key]
            suffix = source.suffix.lower()
            if not target_ready:
                target_root.mkdir(parents=True, exist_ok=True)
                target_ready = True

            target = target_root / f"{candidature_id}{suffix}"

            source.replace(target)

            for other_suffix in _PHOTO_SUFFIXES:
                if other_suffix != suffix:
                    (target_root / f"{candidature_id}{other_suffix}").unlink(missing_ok=True)

            moved += 1
            if moved % 25_000 == 0:
                logger.info("Published %d candidature photos", moved)

    logger.info(
        "Published %d candidature photos; %d without source image; "
        "%d ambiguous candidatures, %d ambiguous photo keys and %d duplicate images skipped",
        moved,
        len(candidate_ids) - moved,
        ambiguous_candidatures,
        len(ambiguous_keys),
        duplicate_photos,
    )


script_instance = CandidaturesDataScript()
