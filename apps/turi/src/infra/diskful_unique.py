"""Deduplicate with bounded sorted runs and sequential external merges."""
import atexit
from array import array
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
from datetime import timedelta
from decimal import Decimal
from heapq import merge
import logging
import math
import os
from pathlib import Path
import shutil
import sys
from struct import Struct
from tempfile import mkdtemp
from time import perf_counter
from typing import Any, Literal

import msgspec
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq

from avoar.common.resources import parse_size


logger = logging.getLogger(__name__)

_HEADER = Struct("<QQQ")  # First position, last position, occurrence count.
_LENGTH = Struct("<Q")
_MERGE_FAN_IN = 32
_ACTIVE_DIRECTORY: ContextVar[Path | None] = ContextVar(
    "diskful_unique_directory", default=None,
)
_RETAINED_DIRECTORIES: set[Path] = set()


def cleanup_diskful_unique() -> None:
    """Release results retained outside a session; their lazy scans become invalid."""
    for directory in tuple(_RETAINED_DIRECTORIES):
        shutil.rmtree(directory, ignore_errors=True)
        _RETAINED_DIRECTORIES.discard(directory)


atexit.register(cleanup_diskful_unique)


def _temporary_directory(parent: str | Path | None = None) -> Path:
    root = Path(
        parent
        or _ACTIVE_DIRECTORY.get()
        or os.getenv("TURI_UNIQUE_TEMP_DIRECTORY", ".turi_unique_tmp")
    ).resolve()
    root.mkdir(parents=True, exist_ok=True)

    return Path(mkdtemp(prefix=f"unique-{os.getpid()}-", dir=root))


@contextmanager
def diskful_unique_session(
    directory: str | Path | None = None,
) -> Iterator[Path]:
    """Keep intermediate scans alive until all consumers in this context finish."""
    workspace = _temporary_directory(directory)
    token = _ACTIVE_DIRECTORY.set(workspace)

    try:
        yield workspace
    finally:
        _ACTIVE_DIRECTORY.reset(token)
        shutil.rmtree(workspace, ignore_errors=True)


def _canonical_value(value: Any) -> Any:
    # Arrow produces consistent types per field. MessagePack preserves boundaries
    # and nulls; these normalizations match Polars' floating-point equality.
    if isinstance(value, float):
        if math.isnan(value):
            return ("nan",)
        return 0.0 if value == 0 else value

    if isinstance(value, Decimal) and value == 0:
        return Decimal(0)
    if isinstance(value, timedelta):
        return (value.days, value.seconds, value.microseconds)
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonical_value(item) for key, item in value.items()}

    return value


def _encode_key(values: tuple) -> bytes:
    return msgspec.msgpack.encode([_canonical_value(value) for value in values])


def _batches(
    source: Path,
    schema: pa.Schema,
    batch_size: int,
) -> Iterator[pa.RecordBatch]:
    # Sequential row-group reads preserve the physical source positions.
    with pq.ParquetFile(source) as parquet:
        for batch in parquet.iter_batches(batch_size=batch_size):
            yield batch.cast(schema)


def _key_rows(batch: pa.RecordBatch, columns: list[str]) -> Iterator[bytes]:
    values = [_key_values(batch.column(name)) for name in columns]

    for row in zip(*values):
        yield _encode_key(row)


def _key_values(column: pa.Array) -> list:
    dtype = column.type

    # Converting ns timestamps/durations to Python datetime/timedelta loses
    # precision. Use physical integers, including inside lists and structs.
    if pa.types.is_temporal(dtype):
        physical = (
            pa.int32()
            if pa.types.is_date32(dtype) or pa.types.is_time32(dtype)
            else pa.int64()
        )
        return column.cast(physical).to_pylist()

    if (
        pa.types.is_list(dtype)
        or pa.types.is_large_list(dtype)
        or pa.types.is_fixed_size_list(dtype)
    ):
        return [_key_values(item.values) if item.is_valid else None for item in column]

    if pa.types.is_struct(dtype):
        fields = [_key_values(column.field(index)) for index in range(dtype.num_fields)]
        valid = column.is_valid().to_pylist()

        return [list(values) if present else None for present, values in zip(valid, zip(*fields))]

    return column.to_pylist()


def _read_keys(stream) -> Iterator[tuple[bytes, int, int, int]]:
    while size := stream.read(_LENGTH.size):
        length = _LENGTH.unpack(size)[0]
        first, last, count = _HEADER.unpack(stream.read(_HEADER.size))
        key = stream.read(length)
        if len(key) != length:
            raise OSError("Truncated unique key run")
        yield key, first, last, count


def _write_keys(path: Path, records, buffering: int) -> None:
    with path.open("wb", buffering=buffering) as stream:
        for key, first, last, count in records:
            stream.write(_LENGTH.pack(len(key)))
            stream.write(_HEADER.pack(first, last, count))
            stream.write(key)


def _coalesce_keys(records) -> Iterator[tuple[bytes, int, int, int]]:
    previous = None

    for key, first, last, count in records:
        if previous is not None and key == previous[0]:
            old_key, old_first, old_last, old_count = previous
            previous = old_key, min(first, old_first), max(last, old_last), count + old_count
        else:
            if previous is not None:
                yield previous
            previous = key, first, last, count

    if previous is not None:
        yield previous


def _read_positions(stream) -> Iterator[int]:
    while data := stream.read(65_536):
        values = array("Q")
        values.frombytes(data)
        if sys.byteorder != "little":
            values.byteswap()
        yield from values


def _merge_runs(paths: list[Path], directory: Path, *, keys: bool, buffering: int) -> Path:
    pass_number = 0

    while len(paths) > 1:
        logger.info(
            "diskful_unique merge: kind=%s pass=%d runs=%d fan_in=%d",
            "keys" if keys else "positions", pass_number + 1, len(paths), _MERGE_FAN_IN,
        )
        following = []
        for start in range(0, len(paths), _MERGE_FAN_IN):
            group = paths[start:start + _MERGE_FAN_IN]
            if len(group) == 1:
                following.extend(group)
                continue

            output = directory / f"merge-{pass_number}-{start}.bin"
            with ExitStack() as stack:
                streams = [stack.enter_context(path.open("rb", buffering=buffering)) for path in group]
                records = merge(*[(_read_keys(stream) if keys else _read_positions(stream)) for stream in streams])
                if keys:
                    _write_keys(output, _coalesce_keys(records), buffering)
                else:
                    with output.open("wb", buffering=buffering) as target:
                        for position in records:
                            target.write(_LENGTH.pack(position))

            # Readers are closed and the replacement run is complete before deletion.
            for path in group:
                path.unlink()
            following.append(output)

        paths = following
        pass_number += 1

    return paths[0]


def _selection_positions(
    source: Path,
    schema: pa.Schema,
    columns: list[str],
    directory: Path,
    keep: str,
    batch_size: int,
    memory_bytes: int,
) -> tuple[Path, int, int]:
    buffering = min(1024**2, max(4096, memory_bytes // (2 * (_MERGE_FAN_IN + 1))))
    key_directory = directory / "keys"
    position_directory = directory / "positions"
    key_directory.mkdir()
    position_directory.mkdir()
    paths = []
    position = 0

    for batch in _batches(source, schema, batch_size):
        local = {}
        for key in _key_rows(batch, columns):
            first, _, count = local.get(key, (position, position, 0))
            local[key] = first, position, count + 1
            position += 1

        path = key_directory / f"run-{len(paths)}.bin"
        _write_keys(path, ((key, *local[key]) for key in sorted(local)), buffering)
        paths.append(path)

    if not paths:
        path = key_directory / "empty.bin"
        path.touch()
        paths.append(path)

    logger.info("diskful_unique key runs ready: rows=%d runs=%d", position, len(paths))
    keys = _merge_runs(paths, key_directory, keys=True, buffering=buffering)
    selected = []
    paths = []
    distinct = 0
    selected_count = 0

    def flush_positions():
        path = position_directory / f"run-{len(paths)}.bin"
        with path.open("wb", buffering=buffering) as target:
            values = array("Q", sorted(selected))
            if sys.byteorder != "little":
                values.byteswap()
            values.tofile(target)
        paths.append(path)
        selected.clear()

    with keys.open("rb", buffering=buffering) as stream:
        for _, first, last, count in _read_keys(stream):
            distinct += 1
            if keep != "none" or count == 1:
                selected.append(last if keep == "last" else first)
                selected_count += 1
            if len(selected) >= batch_size:
                flush_positions()

    if selected or not paths:
        flush_positions()
    keys.unlink()

    positions = _merge_runs(paths, position_directory, keys=False, buffering=buffering)
    return positions, distinct, selected_count


def _selected_batches(source: Path, schema: pa.Schema, positions: Path, batch_size: int):
    offset = 0
    with positions.open("rb") as stream:
        selected = _read_positions(stream)
        current = next(selected, None)
        if current is None:
            return

        for batch in _batches(source, schema, batch_size):
            indices = []
            while current is not None and current < offset + batch.num_rows:
                indices.append(current - offset)
                current = next(selected, None)
            if indices:
                yield batch.take(pa.array(indices, type=pa.int64()))
            offset += batch.num_rows
            if current is None:
                return

        if current is not None:
            raise OSError("Unique selection contains positions outside the source")


def diskful_unique(
    frame: pl.LazyFrame,
    *columns: str,
    subset: str | Sequence[str] | None = None,
    keep: Literal["any", "first", "last", "none"] = "any",
    maintain_order: bool = False,
    batch_size: int = 16_384,
    memory_limit: str | None = None,
    temp_directory: str | Path | None = None,
) -> pl.LazyFrame:
    """Execute deduplication now and return a lazy scan of its temporary Parquet.

    Accept positional column names or Polars-style ``subset``; omitted columns
    mean the entire row. All keep modes preserve source order, even when it is
    not required. Sorted runs and bounded fan-in merges avoid per-key random I/O.
    Key buffers are bounded by batches, not the global number of distinct keys.
    Upstream operations still execute in Polars and retain their own requirements.

    Consume derived plans inside ``diskful_unique_session`` for prompt cleanup.
    Without a session, results remain available until process exit or explicit
    ``cleanup_diskful_unique``. Indexes and input copies are removed immediately.
    memory_limit budgets merge I/O buffers, not total RSS or upstream allocations.
    """
    if not isinstance(frame, pl.LazyFrame):
        raise TypeError("diskful_unique expects a Polars LazyFrame")
    if columns and subset is not None:
        raise ValueError("Pass positional columns or subset, not both")
    if keep not in {"any", "first", "last", "none"}:
        raise ValueError(f"Unsupported keep mode: {keep}")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    original_schema = frame.collect_schema()
    requested = columns if columns else subset
    if requested is None:
        names = original_schema.names()
    elif isinstance(requested, str):
        names = [requested]
    else:
        names = list(requested)

    if not names or not all(isinstance(name, str) for name in names):
        raise ValueError("Unique columns must be nonempty string column names")

    missing = set(names) - set(original_schema.names())
    if missing:
        raise ValueError(f"Missing unique columns: {sorted(missing)}")

    memory_bytes = parse_size(
        memory_limit or os.getenv("TURI_UNIQUE_MEMORY_LIMIT", "256MiB")
    )
    workspace = _temporary_directory(temp_directory)
    source = workspace / "source.parquet"
    result = workspace / "result.parquet"
    index_directory = workspace / "index"
    started = perf_counter()

    logger.info("diskful_unique starting: columns=%s workspace=%s", names, workspace)

    try:
        index_directory.mkdir()

        frame.sink_parquet(
            source,
            compression="zstd",
            row_group_size=batch_size,
            maintain_order=True,
            engine="streaming",
        )
        schema = pq.read_schema(source)

        positions, distinct, expected_rows = _selection_positions(
            source, schema, names, index_directory, keep, batch_size, memory_bytes,
        )
        output_rows = 0

        with pq.ParquetWriter(result, schema, compression="zstd") as writer:
            for batch in _selected_batches(source, schema, positions, batch_size):
                writer.write_batch(batch, row_group_size=batch_size)
                output_rows += batch.num_rows

        if output_rows != expected_rows:
            raise ValueError(f"Unique output audit failed: rows={output_rows}/{expected_rows}")

        # Keep only the result; removing it here would invalidate the returned plan.
        source.unlink()
        shutil.rmtree(index_directory, ignore_errors=True)

        if _ACTIVE_DIRECTORY.get() is None or temp_directory is not None:
            _RETAINED_DIRECTORIES.add(workspace)

        logger.info(
            "diskful_unique done: keys=%d rows=%d seconds=%.3f",
            distinct, output_rows, perf_counter() - started,
        )

        return pl.scan_parquet(result).cast(original_schema)
    except BaseException:
        shutil.rmtree(workspace, ignore_errors=True)
        raise
