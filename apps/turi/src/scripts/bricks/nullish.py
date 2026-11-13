"""Elementwise null normalization for producer string columns."""
from collections.abc import Sequence

import polars as pl
import polars.selectors as cs


def nullify_strings(values: Sequence[str]) -> pl.Expr:
    """Keep literal-to-null replacement in the streaming engine."""
    return (
        pl.when(cs.string().is_in(values))
        .then(pl.lit(None, dtype=pl.String))
        .otherwise(cs.string())
        .name.keep()
    )
