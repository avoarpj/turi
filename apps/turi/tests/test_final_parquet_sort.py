from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from datetime import date, datetime
from decimal import Decimal

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq

from scripts.maintenance.sort_final_parquets import is_sorted, sort_parquet
from scripts.bricks.parquet_order import FINAL_PARQUET_SORT_KEYS


class FinalParquetSortTests(unittest.TestCase):
    def test_sort_preserves_unsigned_ids_lists_dates_decimals_metadata_and_duplicates(self):
        schema = pa.schema([
            pa.field("id", pa.uint64()),
            pa.field("key", pa.large_string()),
            pa.field("amount", pa.decimal128(18, 2)),
            pa.field("date", pa.date32()),
            pa.field("timestamp", pa.timestamp("us")),
            pa.field("items", pa.large_list(pa.large_string())),
        ], metadata={b"source": b"fixture"})
        rows = [
            {"id": 18446744073709551615, "key": "z", "amount": Decimal("1.23"),
             "date": date(1800, 1, 1), "timestamp": datetime(2024, 1, 1, 0, 0, 0, 123), "items": ["a", None]},
            {"id": 2, "key": None, "amount": None, "date": None, "timestamp": None, "items": []},
            {"id": 1, "key": "a", "amount": Decimal("-2.10"),
             "date": date(2024, 1, 2), "timestamp": None, "items": None},
        ]
        rows.append(dict(rows[0]))

        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "data.parquet"
            pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, compression="zstd", row_group_size=2)
            original_schema = pq.read_schema(path)

            self.assertFalse(is_sorted(path, ("key", "id"), batch_size=1))
            record = sort_parquet(path, ("key", "id"), work_directory=root / "work", memory_limit="128MB")
            actual = pq.read_table(path)

            self.assertEqual(actual.to_pylist(), [rows[1], rows[2], rows[0], rows[3]])
            self.assertTrue(actual.schema.equals(original_schema, check_metadata=True))
            self.assertTrue(is_sorted(path, ("key", "id"), batch_size=1))
            self.assertEqual(record["rows"], 4)
            self.assertEqual(record["status"], "sorted")
            self.assertEqual(pq.ParquetFile(path).metadata.row_group(0).column(0).compression, "ZSTD")

            inode = path.stat().st_ino
            skipped = sort_parquet(path, ("key", "id"), work_directory=root / "work")
            self.assertEqual(skipped["status"], "already_sorted")
            self.assertEqual(path.stat().st_ino, inode)

    def test_streamed_batches_keep_original_row_group_sizes(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "data.parquet"
            rows = 25000
            pq.write_table(
                pa.table({"id": pa.array(range(rows, 0, -1), type=pa.uint64())}),
                path,
                row_group_size=10000,
            )

            sort_parquet(path, ("id",), work_directory=root / "work", memory_limit="128MB")

            metadata = pq.ParquetFile(path).metadata
            self.assertEqual(
                [metadata.row_group(index).num_rows for index in range(metadata.num_row_groups)],
                [10000, 10000, 5000],
            )
            self.assertEqual(pq.read_table(path)["id"].to_pylist(), list(range(1, rows + 1)))
            self.assertEqual(list((root / "work").iterdir()), [])

    def test_failed_audit_keeps_the_original_file(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "data.parquet"
            pq.write_table(pa.table({"id": [2, 1]}), path)
            original = path.read_bytes()

            with patch(
                "scripts.maintenance.sort_final_parquets.content_summary",
                side_effect=[(2, 10), (2, 11)],
            ):
                with self.assertRaisesRegex(ValueError, "Content audit failed"):
                    sort_parquet(path, ("id",), work_directory=root / "work")

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(root.glob("*.sorted")), [])

    def test_sort_policies_apply_to_lazy_frames_and_reject_missing_columns(self):
        for table, keys in FINAL_PARQUET_SORT_KEYS.items():
            frame = pl.DataFrame({key: ["z", None, "a"] for key in keys}).lazy()
            ordered = frame.sort(by=keys).collect()
            self.assertEqual(ordered[keys[0]].to_list(), [None, "a", "z"], table)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "data.parquet"
            pq.write_table(pa.table({"id": [2, 1]}), path)
            with self.assertRaisesRegex(ValueError, "Missing sorting columns"):
                sort_parquet(path, ("missing",), work_directory=root / "work")
