"""External DataFusion sort with batch writes and atomic publication."""
from collections.abc import Mapping, Sequence
import logging
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from uuid import uuid4

from datafusion import RuntimeEnvBuilder, SessionConfig, SessionContext
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

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
    row_group_size: int = 65_536,
) -> dict:
    memory = parse_size(memory_limit or os.getenv("TURI_SORT_MEMORY_LIMIT", "256MiB"))
    expected_totals = dict(expected_totals or {})
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(f".{destination.name}.{uuid4().hex}.partial")
    ordering = ", ".join(f"{_quote_identifier(key)} ASC NULLS FIRST" for key in keys)
    disk_limit = os.getenv("TURI_SORT_MAX_TEMP_DIRECTORY_SIZE", "24G").upper()
    if re.fullmatch(r"[1-9][0-9]*[KMG]", disk_limit) is None:
        raise ValueError("TURI_SORT_MAX_TEMP_DIRECTORY_SIZE must use an integer and K/M/G")

    logger.info("External sort starting: rows=%d keys=%s pool=%d", expected_rows, keys, memory)

    try:
        with TemporaryDirectory(prefix="sort-", dir=work_directory) as directory:
            runtime = (
                RuntimeEnvBuilder()
                .with_fair_spill_pool(memory)
                .with_disk_manager_specified(directory)
            )
            context = SessionContext(
                SessionConfig({"datafusion.execution.spill_compression": "zstd"})
                .with_target_partitions(1)
                .with_batch_size(16_384),
                runtime,
            )
            context.sql(f"SET datafusion.runtime.max_temp_directory_size = '{disk_limit}'").collect()
            context.register_parquet("source", source)
            result = context.sql(f"SELECT * FROM source ORDER BY {ordering}")
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
                staging, schema, compression="zstd", sorting_columns=sorting_columns,
            ) as writer:
                for batch in result.execute_stream():
                    arrow = batch.to_pyarrow().cast(schema)
                    rows += arrow.num_rows

                    for name in totals:
                        subtotal = pc.sum(arrow.column(name)).as_py()
                        totals[name] += subtotal or 0

                    pending.append(arrow)
                    pending_rows += arrow.num_rows

                    if pending_rows >= row_group_size:
                        writer.write_table(
                            pa.Table.from_batches(pending, schema=schema),
                            row_group_size=row_group_size,
                        )
                        pending = []
                        pending_rows = 0

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
