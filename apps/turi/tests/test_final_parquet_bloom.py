from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

from scripts.maintenance.bloom_final_parquets import (
    audit_content,
    bloom_columns,
    bloom_coverage,
    rewrite_final_parquets,
    rewrite_parquet,
)


class FinalParquetBloomTests(unittest.TestCase):
    def test_filters_cover_nested_leaves_and_preserve_content_and_layout(self):
        schema = pa.schema([
            pa.field("id", pa.uint64()),
            pa.field("amount", pa.decimal128(18, 2)),
            pa.field("date", pa.date32()),
            pa.field("timestamp", pa.timestamp("us")),
            pa.field("items", pa.large_list(pa.large_string())),
            pa.field("float", pa.float64()),
            pa.field("flag", pa.bool_()),
        ], metadata={b"source": b"fixture"})
        rows = [
            {"id": 2**64 - 1, "amount": Decimal("1.23"), "date": date(1800, 1, 1),
             "timestamp": datetime(2024, 1, 1, 0, 0, 0, 123), "items": ["a", None],
             "float": float("nan"), "flag": True},
            {"id": 1, "amount": None, "items": [], "flag": False},
            {"id": 1, "amount": Decimal("-2.10"), "items": None},
        ]
        rows.append(dict(rows[0]))

        with TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.parquet"
            original = Path(directory) / "original.parquet"
            pq.write_table(
                pa.Table.from_pylist(rows, schema=schema), path,
                row_group_size=2, compression={"id": "zstd", "items.list.item": "gzip"},
                use_compliant_nested_type=False,
            )
            original.write_bytes(path.read_bytes())

            result = rewrite_parquet(path)

            with pq.ParquetFile(original) as before, pq.ParquetFile(path) as after:
                audit_content(before, after)
                supported, unsupported = bloom_columns(after)
                self.assertIn("items.list.item", supported)
                self.assertEqual(unsupported, ["flag"])
                self.assertEqual(bloom_coverage(after.metadata, supported), (12, 12))

                for group in range(2):
                    for column in range(after.metadata.num_columns):
                        self.assertEqual(
                            before.metadata.row_group(group).column(column).compression,
                            after.metadata.row_group(group).column(column).compression,
                        )

            self.assertEqual(result["status"], "rewritten")
            inode = path.stat().st_ino
            self.assertEqual(rewrite_parquet(path)["status"], "already_filtered")
            self.assertEqual(path.stat().st_ino, inode)
            self.assertEqual(rewrite_parquet(path, force=True)["status"], "rewritten")

    def test_failed_audit_preserves_original_and_removes_staging(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.parquet"
            pq.write_table(pa.table({"id": [3, 1, 1]}), path)
            original = path.read_bytes()

            with patch(
                "scripts.maintenance.bloom_final_parquets.audit_content",
                side_effect=ValueError("Content audit failed"),
            ):
                with self.assertRaisesRegex(ValueError, "Content audit failed"):
                    rewrite_parquet(path)

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_audit_rejects_changed_order_and_values(self):
        with TemporaryDirectory() as directory:
            before = Path(directory) / "before.parquet"
            after = Path(directory) / "after.parquet"
            pq.write_table(pa.table({"id": [1, 2, 1]}), before)
            pq.write_table(pa.table({"id": [2, 1, 1]}), after)

            with pq.ParquetFile(before) as source, pq.ParquetFile(after) as output:
                with self.assertRaisesRegex(ValueError, "row order changed"):
                    audit_content(source, output)

    def test_discovery_handles_new_tables_and_empty_files_and_checkpoints(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "new_table" / "partition"
            folder.mkdir(parents=True)
            pq.write_table(pa.table({"id": [1, 2]}), folder / "data.parquet")
            pq.write_table(pa.table({"id": pa.array([], type=pa.uint64())}), folder / "empty.parquet")
            report_path = root / "report.json"

            result = rewrite_final_parquets(root, report_path=report_path)
            self.assertEqual(len(result["files"]), 2)
            self.assertIn("finished_at", json.loads(report_path.read_text()))

            result = rewrite_final_parquets(root, report_path=report_path)
            self.assertTrue(all(record["status"] == "already_filtered" for record in result["files"]))

    def test_memory_guard_and_concurrent_source_changes_preserve_source(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.parquet"
            pq.write_table(pa.table({"id": [3, 1, 1]}), path)
            original = path.read_bytes()

            with self.assertRaisesRegex(ValueError, "memory guard"):
                rewrite_parquet(path, max_row_group_bytes=1)
            self.assertEqual(path.read_bytes(), original)

            def replace_source(*args):
                pq.write_table(pa.table({"id": [99]}), path)

            with patch("scripts.maintenance.bloom_final_parquets.audit_content", side_effect=replace_source):
                with self.assertRaisesRegex(RuntimeError, "Source changed"):
                    rewrite_parquet(path)

            self.assertEqual(pq.read_table(path)["id"].to_pylist(), [99])
