"""Shared, typed keys for candidatures and nominal bulletin votes."""

import polars as pl

from config.projectsettings.settings import NUMERIC_HASH_SEED
from scripts.bricks.validated_lookup import validated_lookup


def with_electoral_locality(
    frame: pl.LazyFrame,
    municipalities: pl.LazyFrame,
    role_column: str,
    municipality_column: str,
) -> pl.LazyFrame:
    municipalities = municipalities.select(
        pl.col("CD_MUNICIPIO_TSE").cast(pl.Int32, strict=False).alias("_municipio_tse"),
        pl.col("CD_MUNICIPIO_IBGE").cast(pl.String).alias("_municipio_ibge"),
    ).unique()
    municipalities = validated_lookup(municipalities, "_municipio_tse")

    role = pl.col(role_column).cast(pl.Int32, strict=False)
    return (
        frame.with_columns(
            pl.col(municipality_column).cast(pl.Int32, strict=False).alias("_municipio_tse")
        )
        .join(municipalities, on="_municipio_tse", how="left")
        .with_columns(
            pl.when(role.is_in([1, 2])).then(pl.lit("BR"))
            .when(role.is_in([3, 4, 5, 6, 7, 8, 9, 10]))
            .then(pl.col("SG_UF").cast(pl.String).str.strip_chars().str.to_uppercase())
            .when(role.is_in([11, 12, 13, 25])).then(pl.col("_municipio_ibge"))
            .otherwise(pl.lit(None, dtype=pl.String))
            .alias("codigo_local")
        )
        .drop("_municipio_tse", "_municipio_ibge")
    )


def election_lookup(rounds: pl.LazyFrame, elections: pl.LazyFrame) -> pl.LazyFrame:
    return (
        rounds.select("codigo_tse", "eleicao_id")
        .join(elections.select(pl.col("id").alias("eleicao_id"), "codigo_local"), on="eleicao_id")
        .select(
            pl.col("codigo_tse").cast(pl.Int32),
            pl.col("codigo_local").cast(pl.String),
            pl.col("eleicao_id").cast(pl.UInt64),
        )
        .unique()
    )


def candidature_id_expr() -> pl.Expr:
    # Field order, names, types and seed must match in every dataset.
    return pl.struct(
        pl.col("eleicao_id").cast(pl.UInt64),
        pl.col("codigo_local").cast(pl.String),
        pl.col("codigo_cargo_tse").cast(pl.Int32),
        pl.col("numero_candidato").cast(pl.Int32),
    ).hash(seed=NUMERIC_HASH_SEED)


def election_id_expr() -> pl.Expr:
    return pl.struct(
        pl.col("ano_eleicao").cast(pl.Date),
        pl.col("codigo_local").cast(pl.String),
        pl.col("codigo_tse").cast(pl.Int32),
    ).hash(seed=NUMERIC_HASH_SEED)


def election_round_id_expr(round_column: str = "numero_turno") -> pl.Expr:
    return pl.when(pl.col("eleicao_id").is_not_null()).then(
        pl.struct(
            pl.col("eleicao_id").cast(pl.UInt64),
            pl.col(round_column).cast(pl.Int32).alias("numero_turno"),
        ).hash(seed=NUMERIC_HASH_SEED)
    ).otherwise(pl.lit(None, dtype=pl.UInt64))
