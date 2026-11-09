"""Validate the dimension side of m:1 joins without buffering the fact table."""
from collections.abc import Sequence

import polars as pl


def validated_lookup(
    frame: pl.LazyFrame,
    on: str | Sequence[str],
) -> pl.LazyFrame:
    keys = [on] if isinstance(on, str) else list(on)
    lookup = frame.collect(engine="streaming")

    # Default joins do not match a key containing null. Polars' m:1 validation
    # likewise ignores those keys; preserve that behavior for composite keys.
    matching_keys = lookup.select(keys).drop_nulls()
    if matching_keys.is_duplicated().any():
        raise pl.exceptions.ComputeError("join keys did not fulfill m:1 validation")

    return lookup.lazy()
