"""Group elections into events shared by localities and rounds."""
from datetime import date

import polars as pl

from config.projectsettings.settings import NUMERIC_HASH_SEED
from avoar.core.opendata.election.domain import TipoEleicao


def pleito_id_expr() -> pl.Expr:
    return pl.struct(
        pl.col("ano").cast(pl.Int32),
        pl.col("tipo_pleito").cast(pl.Int32).alias("tipo"),
        pl.col("data_inicio").cast(pl.Date),
    ).hash(seed=NUMERIC_HASH_SEED)


def build_pleitos(metadata: pl.LazyFrame) -> tuple[pl.LazyFrame, pl.LazyFrame]:
    rows = (
        metadata
        .select(
            "ano_eleicao", "codigo_local", "tipo_eleicao_normalizado",
            "DT_PLEITO", "NR_TURNO",
        )
        .unique()
        .with_columns(
            pl.col("ano_eleicao").dt.year().cast(pl.Int32).alias("ano"),
            pl.col("NR_TURNO").cast(pl.Int32).alias("numero_turno"),
            pl.coalesce(
                pl.col("DT_PLEITO").str.to_date("%Y-%m-%d %H:%M:%S", strict=False),
                pl.col("DT_PLEITO").str.to_date("%d/%m/%Y", strict=False),
                pl.col("DT_PLEITO").str.to_date("%Y-%m-%d", strict=False),
            ).alias("data_turno"),
            pl.when(pl.col("tipo_eleicao_normalizado") == "0")
            .then(pl.lit(TipoEleicao.ORDINARIA.value))
            .when(pl.col("tipo_eleicao_normalizado") == "1")
            .then(pl.lit(TipoEleicao.SUPLEMENTAR.value))
            .otherwise(pl.lit(None, dtype=pl.Int32))
            .cast(pl.Int32)
            .alias("tipo_pleito"),
        )
        .collect()
    )

    if rows.filter(
        pl.col("data_turno").is_null()
        | pl.col("tipo_pleito").is_null()
        | pl.col("numero_turno").is_null()
        | ~pl.col("numero_turno").is_in([1, 2])
    ).height:
        raise ValueError("Pleito requires a valid date, election type and round")

    starts: dict[tuple[int, str, int], list[date]] = {}

    for row in rows.filter(pl.col("numero_turno") == 1).iter_rows(named=True):
        key = (row["ano"], row["codigo_local"], row["tipo_pleito"])
        starts.setdefault(key, []).append(row["data_turno"])

    event_dates = []

    for row in rows.iter_rows(named=True):
        key = (row["ano"], row["codigo_local"], row["tipo_pleito"])
        first_rounds = sorted(set(starts.get(key, [])))

        if not first_rounds:
            raise ValueError(f"Pleito has no first round for {key}")

        if row["tipo_pleito"] == TipoEleicao.ORDINARIA.value:
            if len(first_rounds) != 1:
                raise ValueError(f"Multiple ordinary events in the same locality/year: {key}")
            event_date = first_rounds[0]

        else:
            preceding = [value for value in first_rounds if value <= row["data_turno"]]
            if not preceding:
                raise ValueError(f"No preceding first round for supplementary event: {key}")
            event_date = preceding[-1]

        event_dates.append(event_date)

    linked = (
        rows.lazy()
        .with_columns(pl.Series("data_inicio", event_dates, dtype=pl.Date))
        .with_columns(pleito_id_expr().alias("pleito_id"))
    )

    pleitos = (
        linked
        .select(
            pl.col("pleito_id").alias("id"), "ano",
            pl.col("tipo_pleito").alias("tipo"), "data_inicio",
        )
        .unique()
        .sort("ano", "tipo", "data_inicio")
    )

    lookup = linked.select(
        "ano_eleicao", "codigo_local", "tipo_eleicao_normalizado",
        "DT_PLEITO", "NR_TURNO", "pleito_id",
    ).unique()

    return pleitos, lookup
