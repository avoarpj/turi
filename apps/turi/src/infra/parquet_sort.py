"""External DataFusion sort with batch writes and atomic publication."""
from collections.abc import Mapping, Sequence
import base64
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

from datafusion import RuntimeEnvBuilder, SessionConfig, SessionContext
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import polars as pl

from avoar.common.resources import parse_size


logger = logging.getLogger(__name__)


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def write_sorted_parquets(
    source: str,
    destination: Path,
    keys: Sequence[str],
    *,
    schema: pa.Schema,
    work_directory: Path,
    expected_rows: int,
    expected_totals: Mapping[str, int] | None = None,
    memory_limit: str | None = None,
    reserve_merge_memory: bool = False,
    row_group_size: int = 65_536,
    batch_size: int = 16_384,
    target_partitions: int = 1,
    compression: str = "zstd",
    max_temp_directory_size: str | None = None,
    range_sources: Sequence[str] | None = None,
) -> dict:
    """Sort one source, or concatenate sorted, disjoint leading-key ranges.

    ``range_sources`` must cover nonoverlapping ascending ranges of the first
    key, with nulls in the first range. Each range is sorted by all keys.
    """
    work_directory = Path(os.getenv("TURI_UNIQUE_TEMP_DIRECTORY", work_directory))
    work_directory.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix="sort-worker-", dir=work_directory) as directory:
        root = Path(directory).resolve()
        request = root / "request.json"
        response = root / "response.json"
        request.write_text(json.dumps({
            "source": str(Path(source).resolve()),
            "destination": str(destination.resolve()),
            "keys": list(keys),
            "schema": base64.b64encode(schema.serialize().to_pybytes()).decode("ascii"),
            "work_directory": str(root),
            "expected_rows": expected_rows,
            "expected_totals": dict(expected_totals or {}),
            "memory_limit": memory_limit,
            "reserve_merge_memory": reserve_merge_memory,
            "row_group_size": row_group_size,
            "batch_size": batch_size,
            "target_partitions": target_partitions,
            "compression": compression,
            "max_temp_directory_size": max_temp_directory_size,
            "range_sources": [str(Path(path).resolve()) for path in range_sources]
            if range_sources is not None else None,
        }))
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), str(request), str(response)],
            env=dict(os.environ, TMPDIR=str(root)),
            check=False,
        )

        if not response.exists():
            raise RuntimeError(f"Sort worker exited without a result: {process.returncode}")

        result = json.loads(response.read_text())
        if process.returncode or "error" in result:
            error_type = ValueError if result.get("error_type") == "ValueError" else RuntimeError
            raise error_type(result.get("error", f"Sort worker exited: {process.returncode}"))

        return result


def _write_sorted_parquets(
    source: str,
    destination: Path,
    keys: Sequence[str],
    *,
    schema: pa.Schema,
    work_directory: Path,
    expected_rows: int,
    expected_totals: Mapping[str, int] | None = None,
    memory_limit: str | None = None,
    reserve_merge_memory: bool = False,
    row_group_size: int = 65_536,
    batch_size: int = 16_384,
    target_partitions: int = 1,
    compression: str = "zstd",
    max_temp_directory_size: str | None = None,
    range_sources: Sequence[str] | None = None,
) -> dict:
    memory = parse_size(memory_limit or os.getenv("TURI_SORT_MEMORY_LIMIT", "256MiB"))
    options = {
        "datafusion.execution.spill_compression": "zstd",
        "datafusion.execution.parquet.schema_force_view_types": "false",
    }
    if reserve_merge_memory:
        # Leave room to open and merge spilled runs before sort buffers fill the pool.
        options["datafusion.execution.sort_spill_reservation_bytes"] = str(memory // 4)
    expected_totals = dict(expected_totals or {})
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(f".{destination.name}.{uuid4().hex}.partial")
    ordering = ", ".join(f"{_quote_identifier(key)} ASC NULLS FIRST" for key in keys)
    disk_limit = os.getenv(
        "TURI_SORT_MAX_TEMP_DIRECTORY_SIZE", max_temp_directory_size or "24G",
    ).upper()
    if re.fullmatch(r"[1-9][0-9]*[KMG]", disk_limit) is None:
        raise ValueError("TURI_SORT_MAX_TEMP_DIRECTORY_SIZE must use an integer and K/M/G")

    logger.info(
        "External sort starting: rows=%d keys=%s pool=%d disk_limit=%s batch_size=%d tmpdir=%s",
        expected_rows, keys, memory, disk_limit, batch_size, os.getenv("TMPDIR"),
    )

    try:
        with TemporaryDirectory(prefix="sort-", dir=work_directory) as directory:
            runtime = (
                RuntimeEnvBuilder()
                .with_fair_spill_pool(memory)
                .with_disk_manager_specified(directory)
            )
            context = SessionContext(
                SessionConfig(options)
                .with_target_partitions(target_partitions)
                .with_batch_size(batch_size),
                runtime,
            )
            context.sql(f"SET datafusion.runtime.max_temp_directory_size = '{disk_limit}'").collect()

            sorting_columns = pq.SortingColumn.from_ordering(
                schema,
                [(key, "ascending") for key in keys],
                null_placement="at_start",
            )
            rows = 0
            totals = dict.fromkeys(expected_totals, 0)
            pending = []
            pending_rows = 0

            with pq.ParquetWriter(
                staging, schema, compression=compression, sorting_columns=sorting_columns,
            ) as writer:
                sources = list(range_sources) if range_sources is not None else [source]

                for index, current_source in enumerate(sources):
                    logger.info(
                        "Sorting range %d/%d: rows_written=%d source=%s",
                        index + 1, len(sources), rows, current_source,
                    )

                    if index:
                        context.deregister_table("source")

                    context.register_parquet("source", current_source)
                    result = context.sql(f"SELECT * FROM source ORDER BY {ordering}")

                    for batch in result.execute_stream():
                        arrow = batch.to_pyarrow().cast(schema)
                        rows += arrow.num_rows

                        for name in totals:
                            subtotal = pc.sum(arrow.column(name)).as_py()
                            totals[name] += subtotal or 0

                        pending.append(arrow)
                        pending_rows += arrow.num_rows

                        if pending_rows >= row_group_size:
                            table = pa.Table.from_batches(pending, schema=schema)

                            while table.num_rows >= row_group_size:
                                writer.write_table(table.slice(0, row_group_size), row_group_size=row_group_size)
                                table = table.slice(row_group_size)

                            pending = table.to_batches()
                            pending_rows = table.num_rows

                if pending_rows:
                    writer.write_table(pa.Table.from_batches(pending, schema=schema))

            if rows != expected_rows or totals != expected_totals:
                raise ValueError(
                    f"Sorted output audit failed: rows={rows}/{expected_rows}, "
                    f"totals={totals}/{expected_totals}"
                )

            os.replace(staging, destination)
            logger.info("External sort done: rows=%d totals=%s", rows, totals)

            return {"rows": rows, "totals": totals}
    finally:
        staging.unlink(missing_ok=True)


def sink_sorted_parquet_parts(
    frames: Sequence[pl.LazyFrame],
    destination: Path,
    keys: Sequence[str],
    *,
    compression: str = "zstd",
    unique_subset: Sequence[str] | None = None,
    per_part_unique_subset: Sequence[str] | None = None,
    memory_limit: str | None = None,
    reserve_merge_memory: bool = False,
    batch_size: int = 1_024,
    range_partition_count: int | None = None,
) -> None:
    """Stage sources once, then sort globally, optionally in UInt64 key ranges."""
    if unique_subset is not None and per_part_unique_subset is not None:
        raise ValueError("Choose global or per-part deduplication, not both")

    schema = pl.concat(frames, how="diagonal_relaxed").collect_schema()

    if range_partition_count is not None:
        if (
            range_partition_count < 2
            or range_partition_count > 256
            or range_partition_count & (range_partition_count - 1)
        ):
            raise ValueError("Range partition count must be a power of two between 2 and 256")

        if not keys or schema[keys[0]] != pl.UInt64:
            raise ValueError("Range partitioning requires a UInt64 leading sort key")

        if unique_subset is not None or per_part_unique_subset is not None:
            raise ValueError("Range partitioning cannot be combined with deduplication")

    destination.parent.mkdir(parents=True, exist_ok=True)
    work_directory = Path(os.getenv("TURI_UNIQUE_TEMP_DIRECTORY", destination.parent))
    work_directory.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix="sorted-parts-", dir=work_directory) as directory:
        workspace = Path(directory)
        range_key = f"__sort_range_{uuid4().hex}"

        for index, frame in enumerate(frames):
            columns = frame.collect_schema().names()
            aligned = frame.select(
                (pl.col(name).cast(dtype) if name in columns else pl.lit(None, dtype=dtype))
                .alias(name)
                for name, dtype in schema.items()
            )
            part = workspace / f"part-{index:05d}.parquet"
            logger.info("Staging sort input %d/%d", index + 1, len(frames))

            if range_partition_count is None:
                aligned.sink_parquet(part, compression="zstd", row_group_size=65_536)
            else:
                # Exact integer division covers [0, 2**64), including uint64's
                # maximum. Nulls share the first range with zero; the local sort
                # restores NULLS FIRST. Only the auxiliary expression is omitted.
                partition = (
                    pl.col(keys[0]) // pl.lit(2**64 // range_partition_count, dtype=pl.UInt64)
                ).fill_null(0).alias(range_key)

                def range_path(context, part_index=index):
                    bucket = context.partition_keys.item()
                    return (
                        f"range-{bucket:03d}/"
                        f"part-{part_index:05d}-{context.index_in_partition:05d}.parquet"
                    )

                aligned.sink_parquet(
                    pl.PartitionBy(
                        workspace, key=partition, include_key=False,
                        file_path_provider=range_path,
                    ),
                    # Bound each of the partition writers' row-group buffers.
                    compression="zstd", row_group_size=16_384, mkdir=True,
                )

        parts = sorted(workspace.glob("part-*.parquet"))
        range_sources = None

        if range_partition_count is not None:
            parts = sorted(workspace.glob("range-*/*.parquet"))
            range_sources = [
                str(path / "*.parquet") for path in sorted(workspace.glob("range-*"))
            ]

            # A partitioned empty sink writes no files. Retain its full schema
            # and publish an empty Parquet through the same audited writer.
            if not parts:
                part = workspace / "part-00000.parquet"
                pl.DataFrame(schema=schema).write_parquet(part)
                parts = [part]
                range_sources = None

        rows = sum(pq.read_metadata(part).num_rows for part in parts)

        source = str(workspace / "part-*.parquet")
        subset = unique_subset if unique_subset is not None else per_part_unique_subset
        if subset is not None:
            if not subset:
                raise ValueError("Deduplication requires a nonempty subset")
            # Only unordered keep="any" is supported here. The compact parts
            # release transformation buffers; hash partitions bound the number
            # of distinct keys held at once. Auxiliary hashes never leave the plan.
            sources = [source] if unique_subset is not None else [
                str(workspace / f"part-{index:05d}.parquet") for index in range(len(frames))
            ]
            rows = 0

            for source_index, unique_source in enumerate(sources):
                for bucket in range(16):
                    unique = workspace / f"unique-{source_index:05d}-{bucket:02d}.parquet"
                    (
                        pl.scan_parquet(unique_source)
                        .filter((pl.struct(subset).hash(seed=0) % 16) == bucket)
                        .unique(subset=subset)
                        .sink_parquet(unique, compression="zstd", row_group_size=65_536)
                    )
                    rows += pq.read_metadata(unique).num_rows

            source = str(workspace / "unique-*.parquet")

        write_sorted_parquets(
            source, destination, keys,
            schema=pq.read_schema(parts[0]),
            work_directory=workspace,
            expected_rows=rows,
            compression=compression,
            memory_limit=os.getenv("TURI_SORT_MEMORY_LIMIT", memory_limit),
            reserve_merge_memory=reserve_merge_memory,
            max_temp_directory_size="64G",
            batch_size=batch_size,
            range_sources=range_sources,
        )


if __name__ == "__main__":
    import traceback

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    request = json.loads(Path(sys.argv[1]).read_text())
    request["schema"] = pa.ipc.read_schema(pa.BufferReader(base64.b64decode(request["schema"])))
    request["destination"] = Path(request["destination"])
    request["work_directory"] = Path(request["work_directory"])

    def offline(event, args):
        if event in ("socket.connect", "socket.getaddrinfo"):
            raise RuntimeError("Network disabled during external sorting")

    sys.addaudithook(offline)

    try:
        result = _write_sorted_parquets(**request)
    except Exception as exc:
        traceback.print_exc()
        Path(sys.argv[2]).write_text(json.dumps({"error_type": type(exc).__name__, "error": str(exc)}))
        sys.exit(1)

    Path(sys.argv[2]).write_text(json.dumps(result))
