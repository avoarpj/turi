"""Add Bloom filters to existing final Parquets without rerunning the ETL."""
import argparse
from datetime import datetime, timezone
from itertools import zip_longest
import json
import logging
import os
from pathlib import Path
import stat
from time import perf_counter
from uuid import uuid4

import polars as pl
import pyarrow.parquet as pq

from avoar.projectsettings.globals import OPENDATA_DUMPS_OUTPUT_DIR


logger = logging.getLogger(__name__)


def bloom_columns(parquet: pq.ParquetFile) -> tuple[list[str], list[str]]:
    supported = []
    unsupported = []

    for index in range(len(parquet.schema)):
        column = parquet.schema.column(index)

        if column.physical_type in {"BOOLEAN", "INT96"}:
            unsupported.append(column.path)
        else:
            supported.append(column.path)

    return supported, unsupported


def bloom_coverage(metadata: pq.FileMetaData, columns: list[str]) -> tuple[int, int]:
    present = 0
    expected = 0

    for group_index in range(metadata.num_row_groups):
        group = metadata.row_group(group_index)

        for column_index in range(group.num_columns):
            column = group.column(column_index)

            if column.path_in_schema in columns:
                expected += 1
                present += (
                    column.bloom_filter_offset is not None
                    and (column.bloom_filter_length or 0) > 0
                )

    return present, expected


def audit_content(source: pq.ParquetFile, output: pq.ParquetFile) -> None:
    """Compare every logical value in order, including nulls, NaNs and lists."""
    if not source.schema_arrow.equals(output.schema_arrow, check_metadata=True):
        raise ValueError("Content audit failed: Arrow schema or metadata changed")

    if source.metadata.num_rows != output.metadata.num_rows:
        raise ValueError("Content audit failed: row count changed")

    if source.metadata.num_row_groups != output.metadata.num_row_groups:
        raise ValueError("Content audit failed: row group count changed")

    for index in range(source.metadata.num_row_groups):
        before = source.metadata.row_group(index)
        after = output.metadata.row_group(index)

        if before.num_rows != after.num_rows or before.sorting_columns != after.sorting_columns:
            raise ValueError("Content audit failed: row group layout changed")

    batches = zip_longest(
        source.iter_batches(batch_size=65536),
        output.iter_batches(batch_size=65536),
    )

    for before, after in batches:
        if before is None or after is None:
            raise ValueError("Content audit failed: batch count changed")

        if not pl.from_arrow(before).equals(pl.from_arrow(after)):
            raise ValueError("Content audit failed: values or row order changed")


def rewrite_parquet(
    path: Path,
    *,
    false_positive_probability: float = 0.05,
    force: bool = False,
    max_row_group_bytes: int = 512 * 1024 * 1024,
) -> dict:
    if not 0 < false_positive_probability < 1:
        raise ValueError("False-positive probability must be between zero and one")
    if max_row_group_bytes <= 0:
        raise ValueError("Maximum row group bytes must be positive")
    if path.is_symlink():
        raise ValueError(f"Refusing to replace a symlink: {path}")

    started = perf_counter()
    before_stat = path.stat()
    staging = path.with_name(f".{path.name}.{uuid4().hex}.bloom")

    try:
        with pq.ParquetFile(path) as source:
            columns, unsupported = bloom_columns(source)
            metadata = source.metadata
            present, expected = bloom_coverage(metadata, columns)
            record = {
                "file": str(path),
                "rows": metadata.num_rows,
                "row_groups": metadata.num_row_groups,
                "columns": columns,
                "unsupported_columns": unsupported,
                "bytes_before": before_stat.st_size,
            }

            if not force and present == expected:
                return {
                    **record,
                    "status": "already_filtered" if expected else "no_filterable_chunks",
                    "bytes_after": before_stat.st_size,
                    "bloom_filter_chunks": present,
                }

            groups = [metadata.row_group(index) for index in range(metadata.num_row_groups)]
            if any(group.total_byte_size > max_row_group_bytes for group in groups):
                raise ValueError(f"Row group exceeds memory guard in {path}")

            codecs = {}
            dictionary_columns = set()
            statistics_columns = set()

            for group in groups:
                if group.sorting_columns != groups[0].sorting_columns:
                    raise ValueError(f"Mixed sorting metadata in {path}")

                for index in range(group.num_columns):
                    column = group.column(index)
                    name = column.path_in_schema
                    codec = column.compression.lower()
                    codec = "none" if codec == "uncompressed" else codec

                    if name in codecs and codecs[name] != codec:
                        raise ValueError(f"Mixed compression for {name} in {path}")

                    codecs[name] = codec
                    if any("DICTIONARY" in encoding for encoding in column.encodings):
                        dictionary_columns.add(name)
                    if column.is_stats_set:
                        statistics_columns.add(name)

            # Size for the largest original row group, rather than the whole file.
            ndv = max((group.num_rows for group in groups), default=1)
            options = {
                name: {"ndv": max(ndv, 1), "fpp": false_positive_probability}
                for name in columns
            }

            with pq.ParquetWriter(
                staging,
                source.schema_arrow,
                compression=codecs,
                use_dictionary=sorted(dictionary_columns),
                write_statistics=sorted(statistics_columns),
                use_compliant_nested_type=False,
                sorting_columns=groups[0].sorting_columns if groups else None,
                bloom_filter_options=options,
            ) as writer:
                last_progress = perf_counter()

                for index, group in enumerate(groups):
                    table = source.read_row_group(index)
                    writer.write_table(table, row_group_size=max(group.num_rows, 1))
                    del table

                    if perf_counter() - last_progress >= 30:
                        logger.info("%s: row group %s/%s", path, index + 1, len(groups))
                        last_progress = perf_counter()

            with pq.ParquetFile(staging) as output:
                actual, required = bloom_coverage(output.metadata, columns)
                if actual != required or required != expected:
                    raise ValueError(f"Bloom filter coverage audit failed for {path}")

                logger.info("Auditing all values and row order: %s", path)
                audit_content(source, output)

        current_stat = path.stat()
        if (current_stat.st_ino, current_stat.st_size, current_stat.st_mtime_ns) != (
            before_stat.st_ino, before_stat.st_size, before_stat.st_mtime_ns,
        ):
            raise RuntimeError(f"Source changed during rewrite; publication refused: {path}")

        os.chmod(staging, stat.S_IMODE(before_stat.st_mode))
        with staging.open("rb") as stream:
            os.fsync(stream.fileno())

        os.replace(staging, path)

        return {
            **record,
            "status": "rewritten",
            "bytes_after": path.stat().st_size,
            "seconds": round(perf_counter() - started, 3),
            "bloom_filter_chunks": actual,
            "ndv": ndv,
            "false_positive_probability": false_positive_probability,
            "audit": "exact logical values in order, schema, metadata, row groups, Bloom coverage",
        }
    finally:
        staging.unlink(missing_ok=True)


def rewrite_final_parquets(
    root: Path = OPENDATA_DUMPS_OUTPUT_DIR,
    *,
    paths: list[Path] | None = None,
    report_path: Path | None = None,
    false_positive_probability: float = 0.05,
    force: bool = False,
    max_row_group_bytes: int = 512 * 1024 * 1024,
) -> dict:
    root = root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Parquet root does not exist: {root}")

    candidates = root.rglob("*.parquet") if paths is None else set(paths)
    files = sorted(candidates, key=lambda path: path.stat().st_size)
    if not files:
        raise ValueError(f"No final Parquets found in {root}")

    report_path = report_path or root.parent / "bloom_filters_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "root": str(root), "files": []}

    def checkpoint() -> None:
        temporary = report_path.with_name(f".{report_path.name}.{uuid4().hex}.tmp")

        try:
            temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, report_path)
        finally:
            temporary.unlink(missing_ok=True)

    checkpoint()

    for index, path in enumerate(files, 1):
        logger.info("Bloom filters [%s/%s]: %s", index, len(files), path)

        try:
            record = rewrite_parquet(
                path,
                false_positive_probability=false_positive_probability,
                force=force,
                max_row_group_bytes=max_row_group_bytes,
            )
        except Exception as error:
            report["files"].append({"file": str(path), "status": "failed", "error": str(error)})
            checkpoint()
            raise

        report["files"].append(record)
        checkpoint()
        logger.info("%s: %s -> %s bytes", record["status"], record["bytes_before"], record["bytes_after"])

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    checkpoint()

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=OPENDATA_DUMPS_OUTPUT_DIR)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--fpp", type=float, default=0.05)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-row-group-mib", type=int, default=512)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    rewrite_final_parquets(
        args.root,
        report_path=args.report,
        false_positive_probability=args.fpp,
        force=args.force,
        max_row_group_bytes=args.max_row_group_mib * 1024 * 1024,
    )


if __name__ == "__main__":
    main()
