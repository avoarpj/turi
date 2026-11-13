"""Reorder existing final dumps without rerunning source adapters or changing rows."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import json
import os
from pathlib import Path
import shutil
import stat
from time import perf_counter
from uuid import uuid4

import numpy as np
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq

from avoar.projectsettings.globals import OPENDATA_DUMPS_OUTPUT_DIR, PROJECT_ROOT
from infra.parquet_sort import write_sorted_parquets
from scripts.bricks.parquet_order import FINAL_PARQUET_SORT_KEYS


def content_summary(path: Path, schema: pa.Schema) -> tuple:
    """Order-independent, bounded-memory audit of the logical Arrow rows."""
    rows = 0
    hash_sum = 0
    hash_xor = 0
    null_counts = [0] * len(schema)
    totals = [None] * len(schema)

    with localcontext() as decimal_context, pq.ParquetFile(path) as parquet:
        decimal_context.prec = 80

        for batch in parquet.iter_batches(batch_size=131072):
            frame = pl.from_arrow(batch.cast(schema))
            hashes = frame.hash_rows(seed=0)
            rows += batch.num_rows
            hash_sum += int(hashes.cast(pl.Decimal(38, 0)).sum())
            hash_xor ^= int(np.bitwise_xor.reduce(hashes.to_numpy(), initial=np.uint64(0)))

            for index, field in enumerate(schema):
                column = frame[field.name]
                null_counts[index] += column.null_count()

                if pa.types.is_integer(field.type) or pa.types.is_decimal(field.type):
                    if column.null_count() < len(column):
                        scale = field.type.scale if pa.types.is_decimal(field.type) else 0
                        values = column.cast(pl.Decimal(38, scale))
                        subtotal = values.sum()
                        totals[index] = (totals[index] or Decimal(0)) + subtotal

    aggregates = [rows, hash_sum, hash_xor]
    for index, field in enumerate(schema):
        aggregates.append(null_counts[index])
        if pa.types.is_integer(field.type) or pa.types.is_decimal(field.type):
            aggregates.append(totals[index])

    return tuple(aggregates)


def is_sorted(path: Path, keys: tuple[str, ...], batch_size: int = 131072) -> bool:
    previous = None

    with pq.ParquetFile(path) as parquet:
        for batch in parquet.iter_batches(batch_size=batch_size, columns=list(keys)):
            values = pl.from_arrow(batch).select(pl.struct(list(keys))).to_series()
            if previous is not None:
                values = previous.append(values)

            if not values.is_sorted():
                return False

            if len(values):
                previous = values.tail(1)

    return True


def sort_parquet(
    path: Path,
    keys: tuple[str, ...],
    *,
    work_directory: Path,
    memory_limit: str = "2GB",
    target_partitions: int = 2,
) -> dict:
    started = perf_counter()
    before_stat = path.stat()

    with pq.ParquetFile(path) as original:
        schema = original.schema_arrow
        rows = original.metadata.num_rows
        size_before = before_stat.st_size
        missing = set(keys) - set(schema.names)
        if missing:
            raise ValueError(f"Missing sorting columns in {path}: {sorted(missing)}")

        codecs = {
            original.metadata.row_group(group).column(column).compression
            for group in range(original.metadata.num_row_groups)
            for column in range(original.metadata.row_group(group).num_columns)
        }
        if len(codecs) > 1:
            raise ValueError(f"Mixed compression needs explicit handling: {path}")

        codec = next(iter(codecs), "SNAPPY").lower()
        if codec == "uncompressed":
            codec = "none"
        row_group_size = original.metadata.row_group(0).num_rows if rows else 122880

    record = {
        "file": str(path), "keys": list(keys), "rows": rows,
        "bytes_before": size_before,
    }
    if is_sorted(path, keys):
        return {**record, "status": "already_sorted", "bytes_after": size_before}

    work_directory.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex
    spill_directory = work_directory / token
    staging = path.with_name(f".{path.name}.{token}.sorted")
    backup = path.with_name(f".{path.name}.{token}.original")
    spill_directory.mkdir()

    try:
        before = content_summary(path, schema)
        if target_partitions <= 0:
            raise ValueError("Target partitions must be positive")

        write_sorted_parquets(
            str(path), staging, keys,
            schema=schema,
            work_directory=spill_directory,
            expected_rows=rows,
            memory_limit=memory_limit,
            row_group_size=row_group_size,
            target_partitions=target_partitions,
            compression=codec,
            max_temp_directory_size="60G",
        )

        with pq.ParquetFile(staging) as output:
            if not output.schema_arrow.equals(schema, check_metadata=True):
                raise ValueError(f"Parquet schema changed while sorting {path}")
            if output.metadata.num_rows != rows:
                raise ValueError(f"Parquet row count changed while sorting {path}")

        after = content_summary(staging, schema)
        if before != after:
            raise ValueError(f"Content audit failed for {path}")
        if not is_sorted(staging, keys):
            raise ValueError(f"Output is not globally sorted: {path}")

        current_stat = path.stat()
        if (current_stat.st_ino, current_stat.st_size, current_stat.st_mtime_ns) != (
            before_stat.st_ino, before_stat.st_size, before_stat.st_mtime_ns,
        ):
            raise RuntimeError(f"Source changed during sorting; publication refused: {path}")

        os.chmod(staging, stat.S_IMODE(before_stat.st_mode))
        os.link(path, backup)
        os.replace(staging, path)
        backup.unlink()

        return {
            **record,
            "status": "sorted",
            "bytes_after": path.stat().st_size,
            "seconds": round(perf_counter() - started, 3),
            "content_fingerprint_algorithm": "polars_hash_rows_v1",
            "content_fingerprint": [str(value) for value in before[:3]],
            "audit": "schema, rows, row hashes, null counts, numeric totals, global ordering",
        }
    finally:
        if staging.exists():
            staging.unlink()
        if backup.exists():
            # A failed replace leaves the source intact; preserve its recovery link.
            if not path.exists():
                os.replace(backup, path)
        shutil.rmtree(spill_directory)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=OPENDATA_DUMPS_OUTPUT_DIR)
    parser.add_argument("--table", action="append", choices=sorted(FINAL_PARQUET_SORT_KEYS))
    parser.add_argument("--memory-limit", default="2GB")
    parser.add_argument("--target-partitions", type=int, default=2)
    parser.add_argument("--work-directory", type=Path, default=PROJECT_ROOT / ".parquet_sort_tmp")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    tables = args.table or list(FINAL_PARQUET_SORT_KEYS)
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "files": []}
    args.report.parent.mkdir(parents=True, exist_ok=True)

    # Small datasets first, so progress and completed work are visible early.
    files = sorted(
        (path for table in tables for path in (args.root / table).glob("*.parquet")),
        key=lambda path: path.stat().st_size,
    )
    for path in files:
        print(f"Sorting {path.parent.name}/{path.name}", flush=True)
        record = sort_parquet(
            path,
            FINAL_PARQUET_SORT_KEYS[path.parent.name],
            work_directory=args.work_directory,
            memory_limit=args.memory_limit,
            target_partitions=args.target_partitions,
        )
        report["files"].append(record)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(record), flush=True)

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    args.report.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
