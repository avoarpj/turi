import polars as pl


def link_mandate_candidatures(
    mandates: pl.LazyFrame,
    candidates: pl.LazyFrame,
    elections: pl.LazyFrame,
    electoral_context: pl.LazyFrame,
) -> pl.LazyFrame:
    """Resolve unique candidatures using electoral context supplied by each source.

    Context columns: mandato_id, ano_eleicao, codigo_cargo_tse, tipo_eleicao,
    codigo_local (nullable when the source cannot determine the constituency).
    Multiple contexts per mandate are allowed; only one distinct matching
    candidature is accepted. Neither house nor office is hardcoded here.
    """
    contexts = electoral_context.filter(
        pl.col("ano_eleicao").is_not_null()
        & pl.col("codigo_cargo_tse").is_not_null()
        & pl.col("tipo_eleicao").is_not_null()
    )
    eligible = (
        candidates.select(
            pl.col("id").alias("_candidatura_id"), "pessoa_publica_id", "eleicao_id",
            "codigo_cargo_tse", pl.col("codigo_local").alias("_local_candidatura"),
        )
        .join(
            elections.select(
                pl.col("id").alias("eleicao_id"), pl.col("ano").alias("ano_eleicao"),
                pl.col("tipo").alias("tipo_eleicao"),
            ), on="eleicao_id", how="inner", validate="m:1",
        )
    )
    matches = (
        mandates.select(pl.col("id").alias("mandato_id"), "pessoa_publica_id")
        .join(contexts, on="mandato_id", how="inner")
        .join(eligible, on=["pessoa_publica_id", "ano_eleicao", "codigo_cargo_tse", "tipo_eleicao"], how="inner")
        .filter(pl.col("codigo_local").is_null() | (pl.col("codigo_local") == pl.col("_local_candidatura")))
        .group_by("mandato_id")
        .agg(
            pl.col("_candidatura_id").n_unique().alias("_candidaturas"),
            pl.col("_candidatura_id").first().cast(pl.UInt64),
        )
    )
    return (
        mandates.join(matches, left_on="id", right_on="mandato_id", how="left", validate="1:1")
        .with_columns(
            pl.when(pl.col("_candidaturas") == 1)
            .then(pl.col("_candidatura_id"))
            .otherwise(pl.lit(None, dtype=pl.UInt64)).alias("candidatura_id")
        )
        .drop("_candidaturas", "_candidatura_id")
    )
