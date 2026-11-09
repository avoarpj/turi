"""Polling places, deduplicated nationally with electoral observations retained."""

import argparse
from logging import Logger, basicConfig, getLogger
from pathlib import Path
from uuid import uuid4

import polars as pl

from config.projectsettings.settings import (
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
)
from config.projectsettings.scripts import (
    IBGE_ADDRESSES_OUTPUT_PARQUETS,
    TSE_MUNICIPALITIES_RAW_PARQUETS,
)
from config.projectsettings.settings import NUMERIC_HASH_SEED
from infra.datascript.DataScript import DataScript
from scripts.bricks.parquet_order import FINAL_PARQUET_SORT_KEYS


VOTING_LOCATIONS_HISTORY_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_voting_location_history"
    / "tse.parquet"
)
VOTING_LOCATIONS_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_voting_location"
    / "tse.parquet"
)
VOTING_LOCATIONS_RAW_PARQUETS = BASE_DIR / "downloads" / "tse" / "voting_locations"


BRAZIL_UFS = (
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO",
    "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
    "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
)
IDENTITY_COLUMNS = (
    "uf", "codigo_municipio_tse", "zona_eleitoral", "numero",
)
OBSERVATION_COLUMNS = ("id", "data_eleicao", "numero_turno")
DETAIL_COLUMNS = (
    "nome", "endereco", "bairro", "cep", "latitude_tse",
    "longitude_tse", "codigo_situacao",
)


def _text(column: str) -> pl.Expr:
    return (
        pl.col(column).cast(pl.String).str.strip_chars()
        .replace(["", "-1", "-3", "#NULO#", "#NE#"], None)
    )


def _number(column: str) -> pl.Expr:
    return _text(column).cast(pl.Int64, strict=False).cast(pl.String)


def normalize_locations(frame: pl.LazyFrame) -> pl.LazyFrame:
    columns = frame.collect_schema().names()
    if "AA_ELEICAO" not in columns and "ANO_ELEICAO" in columns:
        frame = frame.rename({"ANO_ELEICAO": "AA_ELEICAO"})
        columns = frame.collect_schema().names()

    required = {
        "AA_ELEICAO", "DT_ELEICAO", "NR_TURNO", "SG_UF",
        "CD_MUNICIPIO", "NR_ZONA", "NR_LOCAL_VOTACAO",
    }
    missing = required.difference(columns)
    if missing:
        raise ValueError(f"Layout de locais de votação incompleto: {sorted(missing)}")

    optional = {
        "NM_LOCAL_VOTACAO", "DS_ENDERECO", "NM_BAIRRO", "NR_CEP",
        "NR_LATITUDE", "NR_LONGITUDE", "CD_SITU_LOCAL_VOTACAO",
        "DT_GERACAO", "HH_GERACAO",
    }
    frame = frame.with_columns(
        [pl.lit(None, dtype=pl.String).alias(name) for name in optional.difference(columns)]
    )

    generated_at = pl.concat_str(
        [_text("DT_GERACAO"), _text("HH_GERACAO")], separator=" "
    ).str.to_datetime("%d/%m/%Y %H:%M:%S", strict=False)

    normalized = frame.select(
        _text("SG_UF").str.to_uppercase().alias("uf"),
        _number("CD_MUNICIPIO").alias("codigo_municipio_tse"),
        _number("NR_ZONA").alias("zona_eleitoral"),
        _number("NR_LOCAL_VOTACAO").alias("numero"),

        _text("NM_LOCAL_VOTACAO").alias("nome"),
        _text("DS_ENDERECO").alias("endereco"),
        _text("NM_BAIRRO").alias("bairro"),
        _text("NR_CEP").alias("cep"),
        (
            pl.col("NR_LATITUDE").cast(pl.String).str.strip_chars()
            .str.replace(",", ".").cast(pl.Float64, strict=False)
            .alias("latitude_tse")
        ),
        (
            pl.col("NR_LONGITUDE").cast(pl.String).str.strip_chars()
            .str.replace(",", ".").cast(pl.Float64, strict=False)
            .alias("longitude_tse")
        ),
        (
            _text("CD_SITU_LOCAL_VOTACAO")
            .cast(pl.Int16, strict=False).alias("codigo_situacao")
        ),

        _text("AA_ELEICAO").cast(pl.Int32, strict=False).alias("ano_referencia"),
        pl.coalesce(
            _text("DT_ELEICAO").str.to_date("%d/%m/%Y", strict=False),
            _text("DT_ELEICAO").str.to_date("%Y-%m-%d", strict=False),
        ).alias("data_eleicao"),
        _text("NR_TURNO").cast(pl.Int16, strict=False).alias("numero_turno"),
        generated_at.alias("_gerado_em"),
    )

    # ZZ is abroad. Unknown domestic state codes are an input error, not a
    # reason to silently discard records from the extracts.
    normalized = normalized.filter(pl.col("uf").is_null() | (pl.col("uf") != "ZZ"))
    normalized = normalized.with_columns(
        pl.when(
            pl.col("cep").str.contains(r"^\d{8}$")
            & (pl.col("cep") != "00000000")
        )
        .then(pl.col("cep"))
        .otherwise(None)
        .alias("cep"),
    )

    valid_coordinates = (
        pl.col("latitude_tse").is_finite()
        & pl.col("longitude_tse").is_finite()
        & pl.col("latitude_tse").is_between(-90, 90)
        & pl.col("longitude_tse").is_between(-180, 180)
        & (pl.col("latitude_tse") != -1)
        & (pl.col("longitude_tse") != -1)
        & ~((pl.col("latitude_tse") == 0) & (pl.col("longitude_tse") == 0))
    )
    normalized = normalized.with_columns(
        pl.when(valid_coordinates).then(pl.col(name)).otherwise(None).alias(name)
        for name in ("latitude_tse", "longitude_tse")
    )

    return normalized.with_columns(
        pl.struct(IDENTITY_COLUMNS).hash(seed=NUMERIC_HASH_SEED).alias("id")
    )


def consolidate_observations(frame: pl.DataFrame) -> pl.DataFrame:
    valid = (
        pl.col("uf").is_in(BRAZIL_UFS)
        & pl.all_horizontal(
            pl.col(name).cast(pl.Int64, strict=False) > 0
            for name in IDENTITY_COLUMNS[1:]
        )
        & (pl.col("ano_referencia") == pl.col("data_eleicao").dt.year())
        & pl.col("numero_turno").is_in([1, 2])
    )
    invalid = frame.filter(~valid.fill_null(False))
    if invalid.height:
        raise ValueError(f"Locais de votação com identidade ou data inválida: {invalid.height}")

    # A refreshed source file supersedes previous snapshots of the same
    # election/round. Conflicting fields remain unknown in the consolidated
    # record, with the original alternatives preserved in the raw Parquets.
    latest = frame.filter(
        pl.col("_gerado_em").eq_missing(
            pl.col("_gerado_em").max().over(OBSERVATION_COLUMNS)
        )
    )
    coordinates_agree = pl.all_horizontal(
        pl.col(name).drop_nulls().n_unique() <= 1
        for name in ("latitude_tse", "longitude_tse")
    )
    details = []
    for name in DETAIL_COLUMNS:
        consistent = pl.col(name).drop_nulls().n_unique() <= 1
        if name in ("latitude_tse", "longitude_tse"):
            consistent = coordinates_agree

        details.append(
            pl.when(consistent)
            .then(pl.col(name).drop_nulls().first())
            .otherwise(None)
            .alias(name)
        )

    conflicting_fields = pl.concat_list(
        pl.when(pl.col(name).drop_nulls().n_unique() > 1)
        .then(pl.lit(name))
        .otherwise(pl.lit(None, dtype=pl.String))
        for name in DETAIL_COLUMNS
    ).list.drop_nulls().alias("campos_divergentes")

    return latest.group_by(OBSERVATION_COLUMNS).agg(
        *[pl.col(name).first() for name in (*IDENTITY_COLUMNS, "ano_referencia")],
        *details,
        conflicting_fields,
        pl.col("_gerado_em").first().alias("data_geracao"),
    )


def with_address_clusters(
    locations: pl.DataFrame,
    addresses: pl.LazyFrame | None,
) -> pl.DataFrame:
    if addresses is None or locations.is_empty():
        return locations.with_columns(
            pl.lit(None, dtype=pl.UInt64).alias("endereco_cluster_id")
        )

    # Only explicit building numbers at the end of the address are accepted.
    # Road numbers and kilometer markers must never become building numbers.
    numbered = locations.with_columns(
        pl.col("endereco")
        .str.extract(
            r"(?i)(?:,\s*|\bN(?:[.º°]|[UÚ]MERO)?\s+)(\d+)\s*[A-Z]?\s*$",
            1,
        )
        .cast(pl.Int64, strict=False).cast(pl.String)
        .alias("_numero_endereco")
    )
    join_columns = ["codigo_municipio_ibge", "cep", "_numero_endereco"]
    requested = numbered.select(join_columns).drop_nulls().unique().lazy()
    if requested.collect().is_empty():
        return locations.with_columns(
            pl.lit(None, dtype=pl.UInt64).alias("endereco_cluster_id")
        )

    candidates = (
        addresses.select(
            pl.col("municipio").cast(pl.String).alias("codigo_municipio_ibge"),
            pl.col("cep").cast(pl.String),
            (
                pl.col("numero_logradouro")
                .cast(pl.Int64, strict=False).cast(pl.String)
                .alias("_numero_endereco")
            ),
            pl.col("cluster_id").cast(pl.UInt64),
        )
        .join(requested, on=join_columns, how="semi")
        .group_by(join_columns)
        .agg(
            pl.col("cluster_id").drop_nulls().n_unique().alias("_clusters"),
            pl.col("cluster_id").drop_nulls().first().alias("endereco_cluster_id"),
        )
        .filter(pl.col("_clusters") == 1)
        .drop("_clusters")
        .collect(engine="streaming")
    )

    return (
        numbered.join(candidates, on=join_columns, how="left", validate="m:1")
        .drop("_numero_endereco")
    )


class VotingLocationsDataScript(DataScript):
    script_id = "tse_voting_locations"
    lifetime = "0 6 15 * *"

    source = "Tribunal Superior Eleitoral; IBGE"
    source_url = "https://dadosabertos.tse.jus.br/"
    description = (
        "Cadastro atual e histórico dos locais de votação, com coordenadas TSE e "
        "agrupamento de endereços IBGE."
    )

    input_paths = [
        IBGE_ADDRESSES_OUTPUT_PARQUETS,
        TSE_MUNICIPALITIES_RAW_PARQUETS,
        VOTING_LOCATIONS_RAW_PARQUETS,
    ]
    output_paths = [
        VOTING_LOCATIONS_HISTORY_OUTPUT_PARQUETS,
        VOTING_LOCATIONS_OUTPUT_PARQUETS,
    ]

    dependencies = []
    tags = []

    def process_data(self, logger: Logger):
        files = sorted(VOTING_LOCATIONS_RAW_PARQUETS.glob("*.parquet"))
        if not files:
            raise FileNotFoundError("Nenhum Parquet de locais de votação encontrado")

        # Normalize each layout before concatenating, just like election metadata.
        normalized = pl.concat(
            [normalize_locations(pl.scan_parquet(file)) for file in files],
            how="diagonal_relaxed",
        ).unique().collect(engine="streaming")
        observations = consolidate_observations(normalized)
        if observations.is_empty():
            raise ValueError("Cadastro nacional sem locais de votação no Brasil")

        municipalities = (
            pl.scan_parquet(TSE_MUNICIPALITIES_RAW_PARQUETS / "*.parquet")
            .select(
                _number("CD_MUNICIPIO_TSE").alias("codigo_municipio_tse"),
                _text("CD_MUNICIPIO_IBGE").alias("codigo_municipio_ibge"),
            )
            .unique()
            .collect()
        )
        observations = observations.join(
            municipalities, on="codigo_municipio_tse", how="left", validate="m:1"
        )

        addresses = None
        if IBGE_ADDRESSES_OUTPUT_PARQUETS.exists():
            addresses = pl.scan_parquet(IBGE_ADDRESSES_OUTPUT_PARQUETS)
        else:
            logger.info("Sem cadastro IBGE de endereços; preservando coordenadas TSE como fallback")

        history = with_address_clusters(observations, addresses)
        current = (
            history.sort(
                ["data_eleicao", "numero_turno", "ano_referencia"],
                descending=True,
            )
            .unique(subset="id", keep="first")
        )
        outputs = [
            (current, VOTING_LOCATIONS_OUTPUT_PARQUETS, "opendata_voting_location"),
            (history, VOTING_LOCATIONS_HISTORY_OUTPUT_PARQUETS, "opendata_voting_location_history"),
        ]

        # Prepare both datasets before replacing either published file.
        temporary_files = []
        try:
            for frame, target, table in outputs:
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
                temporary_files.append((temporary, target))
                frame.sort(FINAL_PARQUET_SORT_KEYS[table]).write_parquet(
                    temporary, compression="zstd"
                )

            for temporary, target in temporary_files:
                temporary.replace(target)
        finally:
            for temporary, _target in temporary_files:
                temporary.unlink(missing_ok=True)

        logger.info(
            "Locais: %d; observações: %d; sem município IBGE: %d; "
            "sem coordenadas TSE: %d; com cluster: %d; com divergências: %d",
            current.height,
            history.height,
            history["codigo_municipio_ibge"].null_count(),
            history["latitude_tse"].null_count(),
            history["endereco_cluster_id"].count(),
            (history["campos_divergentes"].list.len() > 0).sum(),
        )



script_instance = VotingLocationsDataScript()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--download",
        action="store_true",
        help="Baixar os anos eleitorais configurados antes de gerar",
    )
    args = parser.parse_args()

    basicConfig(level="INFO")
    logger = getLogger(__name__)
    if args.download:
        from downloaders.tse_voting_locations import tse_voting_locations_downloader

        _files, errors = tse_voting_locations_downloader.get_meta_files_or_download(
            "zip", "application/zip"
        )
        if errors:
            raise RuntimeError(f"Falha em {len(errors)} downloads de locais de votação")

    script_instance.process_data(logger)


if __name__ == "__main__":
    main()
