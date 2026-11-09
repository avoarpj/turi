"""Deduplicate a lazy plan with a filesystem hash index and bounded Arrow batches."""
import atexit
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
import logging
import math
import os
from pathlib import Path
import shutil
from struct import Struct
from tempfile import mkdtemp
from time import perf_counter
from typing import Any, Literal

from datafusion import RuntimeEnvBuilder, SessionConfig, SessionContext
import msgspec
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq

from avoar.common.resources import parse_size


logger = logging.getLogger(__name__)

_HEADER = Struct("<QQQ")  # First position, last position, occurrence count.
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


def _hash_key(key: bytes) -> str:
    return sha256(key).hexdigest()


class _DiskHashIndex:
    """Empty hash markers plus exact keys and small counters in companion files."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.prefixes: set[str] = set()
        self.entries = 0

    def locate(self, key: bytes) -> tuple[Path, tuple[int, int, int] | None]:
        digest = _hash_key(key)
        prefix = digest[:2]
        bucket = self.directory / prefix

        if prefix not in self.prefixes:
            bucket.mkdir(parents=True, exist_ok=True)
            self.prefixes.add(prefix)

        collision = 0

        while True:
            suffix = f".{collision}" if collision else ""
            marker = bucket / f"{digest}{suffix}"
            record = marker.with_name(marker.name + ".key")

            if not marker.exists():
                return record, None

            with record.open("rb") as source:
                header = _HEADER.unpack(source.read(_HEADER.size))
                if source.read() == key:
                    return record, header

            # Hash equality alone must never discard a different original key.
            collision += 1

    def observe(self, key: bytes, position: int, *, count: bool) -> bool:
        record, header = self.locate(key)

        if header is None:
            with record.open("xb") as target:
                target.write(_HEADER.pack(position, position, 1))
                target.write(key)

            record.with_name(record.name.removesuffix(".key")).touch(exist_ok=False)
            self.entries += 1

            return True

        if count:
            first, _, occurrences = header
            with record.open("r+b") as target:
                target.write(_HEADER.pack(first, position, occurrences + 1))

        return False


def _batches(
    context: SessionContext,
    source: Path,
    schema: pa.Schema,
) -> Iterator[pa.RecordBatch]:
    # One file and one partition, without scan repartitioning, preserve source
    # positions for first/last. Do not add a global DISTINCT, sort or collect here.
    for batch in context.read_parquet(str(source)).execute_stream():
        yield batch.to_pyarrow().cast(schema)


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


def _selected_batches(
    context: SessionContext,
    source: Path,
    schema: pa.Schema,
    columns: list[str],
    index: _DiskHashIndex,
    keep: str,
) -> Iterator[pa.RecordBatch]:
    position = 0

    for batch in _batches(context, source, schema):
        if not batch.num_rows:
            continue

        if keep in {"any", "first"}:
            # Local deduplication is bounded by batch_size, never global. BUs
            # often repeat the same metadata hundreds of times within a batch.
            batch_frame = pl.from_arrow(batch).unique(
                subset=columns,
                keep="first",
                maintain_order=True,
            )
            batch = batch_frame.to_arrow().cast(schema).combine_chunks().to_batches()[0]

        selected = []

        for key in _key_rows(batch, columns):
            selected.append(index.observe(key, position, count=keep in {"last", "none"}))
            position += 1

        if keep in {"any", "first"} and any(selected):
            yield batch.filter(pa.array(selected))

    if keep in {"any", "first"}:
        return

    # Last/none need a second bounded scan after final positions/counts are known.
    position = 0

    for batch in _batches(context, source, schema):
        selected = []

        for key in _key_rows(batch, columns):
            _, header = index.locate(key)
            assert header is not None
            _, last, occurrences = header
            selected.append(position == last if keep == "last" else occurrences == 1)
            position += 1

        if any(selected):
            yield batch.filter(pa.array(selected))


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
    not required. Memory is bounded by batches/index lookups, not global key count.
    Upstream operations still execute in Polars and retain their own requirements.

    Consume derived plans inside ``diskful_unique_session`` for prompt cleanup.
    Without a session, results remain available until process exit or explicit
    ``cleanup_diskful_unique``. Indexes and input copies are removed immediately.
    The DataFusion pool excludes Python, Polars, Arrow and writer allocations.
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
    spill_directory = workspace / "spill"
    spill_directory.mkdir()
    started = perf_counter()

    logger.info("diskful_unique starting: columns=%s workspace=%s", names, workspace)

    try:
        frame.sink_parquet(
            source,
            compression="zstd",
            row_group_size=batch_size,
            maintain_order=True,
            engine="streaming",
        )
        schema = pq.read_schema(source)

        config = (
            SessionConfig()
            .with_target_partitions(1)
            .with_batch_size(batch_size)
            .set("datafusion.optimizer.repartition_file_scans", "false")
        )
        runtime = (
            RuntimeEnvBuilder()
            .with_fair_spill_pool(memory_bytes)
            .with_disk_manager_specified(str(spill_directory))
        )
        context = SessionContext(config, runtime)
        index = _DiskHashIndex(index_directory)
        output_rows = 0

        with pq.ParquetWriter(result, schema, compression="zstd") as writer:
            for batch in _selected_batches(context, source, schema, names, index, keep):
                writer.write_batch(batch, row_group_size=batch_size)
                output_rows += batch.num_rows

        # Keep only the result; removing it here would invalidate the returned plan.
        source.unlink()
        shutil.rmtree(index_directory, ignore_errors=True)
        shutil.rmtree(spill_directory, ignore_errors=True)

        if _ACTIVE_DIRECTORY.get() is None or temp_directory is not None:
            _RETAINED_DIRECTORIES.add(workspace)

        logger.info(
            "diskful_unique done: keys=%d rows=%d seconds=%.3f",
            index.entries, output_rows, perf_counter() - started,
        )

        return pl.scan_parquet(result).cast(original_schema)
    except BaseException:
        shutil.rmtree(workspace, ignore_errors=True)
        raise
