"""Expand nested downloads one file at a time before scanning their rows."""
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
import logging
from pathlib import Path
from tempfile import TemporaryDirectory

import polars as pl
import pyarrow.parquet as pq


logger = logging.getLogger(__name__)


@contextmanager
def staged_nested_parquets(
    source: Path,
    *,
    work_directory: Path,
    columns: Sequence[str] | None = None,
) -> Iterator[pl.LazyFrame]:
    """Keep list expansion bounded by a source file, retaining its original schema."""
    schema = pl.scan_parquet(source).collect_schema()
    flattened = pl.LazyFrame(schema=schema).select(pl.col("dados").list.explode()).unnest("dados")
    if columns is not None:
        flattened = flattened.select(columns)
    flattened_schema = flattened.collect_schema()

    work_directory.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix="nested-", dir=work_directory) as directory:
        parts = []

        for path in sorted(source.parent.glob(source.name)):
            # Polars' multi-file reader also ignores empty files in the download glob.
            if path.stat().st_size == 0:
                continue

            if columns is None:
                raw = pl.scan_parquet(path, schema=schema)
            else:
                parquet = pq.ParquetFile(path)
                leaves = [parquet.schema.column(index) for index in range(len(parquet.schema))]
                selected = [
                    column.path for column in leaves
                    if column.path.startswith("dados.") and column.name in columns
                ]
                raw = pl.from_arrow(parquet.read(columns=selected)).lazy()

            frame = (
                raw
                .select(pl.col("dados").list.explode())
                .unnest("dados")
            )

            if columns is not None:
                frame = frame.select(columns)

            part = Path(directory) / f"{len(parts):05d}.parquet"
            logger.info("Expanding nested download %s", path.name)
            frame.cast(flattened_schema).sink_parquet(part, compression="zstd", row_group_size=16_384)
            parts.append(part)

        yield pl.scan_parquet(parts)
