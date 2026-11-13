from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
import os
from threading import Event, Thread

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
from polars.testing import assert_frame_equal

from infra.parquet_sort import sink_sorted_parquet_parts, write_sorted_parquets
from scripts.maintenance.sort_final_parquets import is_sorted, sort_parquet
from scripts.bricks.parquet_order import FINAL_PARQUET_SORT_KEYS


class FinalParquetSortTests(unittest.TestCase):
    def test_uint64_ranges_keep_boundaries_nulls_secondary_order_and_duplicate_rows(self):
        boundary = 2**62
        schema = {
            "empresa_id": pl.UInt64, "id": pl.UInt64, "items": pl.List(pl.String),
            "date": pl.Date, "amount": pl.Decimal(18, 2),
        }
        rows = [
            (None, 9, None, None, None),
            (0, 5, [], date(1800, 1, 1), Decimal("1.23")),
            (boundary - 1, 4, ["a", None], None, Decimal("-2.10")),
            (boundary, 3, ["b"], None, None),
            (2 * boundary, 2, [], None, None),
            (3 * boundary, 1, None, None, None),
            (2**64 - 1, 2**64 - 1, ["z"], None, None),
            (boundary, 1, ["first"], None, None),
        ]
        first = pl.DataFrame(rows[::-1], schema=schema, orient="row")
        second = pl.DataFrame(rows[:4], schema=schema, orient="row")
        expected = pl.concat([first, second]).sort("empresa_id", "id")

        with TemporaryDirectory() as directory:
            path = Path(directory) / "ranges.parquet"
            sink_sorted_parquet_parts(
                [first.lazy(), second.lazy()], path, ["empresa_id", "id"],
                range_partition_count=4, batch_size=2, compression="snappy",
            )
            assert_frame_equal(pl.read_parquet(path), expected)
            self.assertEqual(pq.read_metadata(path).num_row_groups, 1)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_ranges_keep_row_groups_across_sparse_ranges_and_empty_parts(self):
        rows = 70_000
        frame = pl.DataFrame({
            "empresa_id": pl.Series([2**64 - 1, 0] * (rows // 2), dtype=pl.UInt64),
            "id": pl.Series(range(rows, 0, -1), dtype=pl.UInt64),
        })

        with TemporaryDirectory() as directory:
            path = Path(directory) / "sparse.parquet"
            sink_sorted_parquet_parts(
                [frame.clear().lazy(), frame.lazy(), frame.clear().lazy()],
                path, ["empresa_id", "id"], range_partition_count=64, batch_size=8_192,
            )
            assert_frame_equal(pl.read_parquet(path), frame.sort("empresa_id", "id"))
            metadata = pq.read_metadata(path)
            self.assertEqual(
                [metadata.row_group(i).num_rows for i in range(metadata.num_row_groups)],
                [65_536, rows - 65_536],
            )

            sink_sorted_parquet_parts(
                [frame.clear().lazy()], path, ["empresa_id", "id"], range_partition_count=64,
            )
            assert_frame_equal(pl.read_parquet(path), frame.clear())

    def test_ranges_reject_unsupported_partitioning_before_writing(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "original.parquet"
            original = pl.DataFrame({"id": pl.Series([2, 1], dtype=pl.UInt64)})
            original.write_parquet(path)
            before = path.read_bytes()

            for count in [0, 1, 3, 512]:
                with self.assertRaisesRegex(ValueError, "power of two"):
                    sink_sorted_parquet_parts(
                        [original.lazy()], path, ["id"], range_partition_count=count,
                    )

            with self.assertRaisesRegex(ValueError, "UInt64"):
                sink_sorted_parquet_parts(
                    [original.cast({"id": pl.Int64}).lazy()], path, ["id"], range_partition_count=4,
                )

            with self.assertRaisesRegex(ValueError, "deduplication"):
                sink_sorted_parquet_parts(
                    [original.lazy()], path, ["id"], range_partition_count=4, unique_subset=["id"],
                )

            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_range_audit_failure_keeps_published_output_and_cleans_scratch(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.parquet"
            path = root / "published.parquet"
            scratch = root / "scratch"
            frame = pa.table({"id": pa.array([0, 2**64 - 1], type=pa.uint64()), "total": [2, 3]})
            pq.write_table(frame, source)
            pq.write_table(frame, path)
            before = path.read_bytes()

            with (
                patch.dict("os.environ", {"TURI_UNIQUE_TEMP_DIRECTORY": str(scratch)}),
                self.assertRaisesRegex(ValueError, "Sorted output audit failed"),
            ):
                write_sorted_parquets(
                    str(source), path, ["id"], range_sources=[str(source)],
                    schema=frame.schema, work_directory=scratch, expected_rows=2,
                    expected_totals={"total": 6},
                )

            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(scratch.iterdir()), [])
            self.assertEqual(list(root.glob("*.partial")), [])

    def test_skewed_range_keeps_spill_fallback_with_wide_rows(self):
        rows = 80_000
        frame = pl.DataFrame({
            "empresa_id": pl.Series([2**64 - 1] * rows, dtype=pl.UInt64),
            "id": pl.Series(range(rows, 0, -1), dtype=pl.UInt64),
            "text": [sha256(str(i).encode()).hexdigest() * 16 for i in range(rows)],
        })

        with TemporaryDirectory() as directory:
            path = Path(directory) / "skewed.parquet"
            sink_sorted_parquet_parts(
                [frame.lazy()], path, ["empresa_id", "id"], range_partition_count=64,
                batch_size=8_192, memory_limit="64MiB", reserve_merge_memory=True,
            )
            assert_frame_equal(pl.read_parquet(path), frame.sort("empresa_id", "id"))
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_partitioned_unique_preserves_null_keys_and_unsigned_ids_across_parts(self):
        first = pl.DataFrame({
            "id": pl.Series([None, 2**64 - 1, 1, 1], dtype=pl.UInt64),
            "value": [None, "z", "a", "a"],
        }).lazy()
        second = pl.DataFrame({
            "id": pl.Series([None, 2**64 - 1, 2], dtype=pl.UInt64),
            "value": [None, "z", "b"],
        }).lazy()
        expected = pl.concat([first, second]).unique("id").sort("id").collect()

        with TemporaryDirectory() as directory:
            path = Path(directory) / "unique.parquet"
            sink_sorted_parquet_parts([first, second], path, ["id"], unique_subset=["id"])
            assert_frame_equal(pl.read_parquet(path), expected)

    def test_wide_string_rows_sort_with_a_small_spill_pool(self):
        rows = 200_000
        values = [sha256(str(index).encode()).hexdigest()[:32] for index in range(rows)]
        frame = pl.DataFrame({
            "id": pl.Series(range(rows, 0, -1), dtype=pl.UInt64), "text": values,
        }).with_columns(pl.col("text").alias(f"text{index}") for index in range(7))

        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.parquet"
            destination = root / "sorted.parquet"
            frame.write_parquet(source, row_group_size=rows)
            original_tmpdir = os.environ.get("TMPDIR")
            scratch = root / "scratch selected"
            scratch.mkdir()
            stop = Event()
            spill_paths = set()

            def observe_spills():
                while not stop.wait(0.01):
                    try:
                        spill_paths.update(p for p in root.rglob(".tmp*") if p.is_file())
                    except FileNotFoundError:
                        pass

            observer = Thread(target=observe_spills)
            observer.start()

            try:
                with patch.dict("os.environ", {
                    "TURI_SORT_MAX_TEMP_DIRECTORY_SIZE": "128M",
                    "TURI_UNIQUE_TEMP_DIRECTORY": str(scratch),
                }):
                    write_sorted_parquets(
                        str(source), destination, ["id"], schema=pq.read_schema(source),
                        work_directory=root, expected_rows=rows, memory_limit="64MiB",
                        batch_size=1_024,
                        reserve_merge_memory=True,
                    )
            finally:
                stop.set()
                observer.join()

            assert_frame_equal(pl.read_parquet(destination), frame.sort("id"))
            self.assertTrue(spill_paths, "The forced spill must stay under the selected work directory")
            self.assertTrue(all(path.is_relative_to(scratch) for path in spill_paths))
            self.assertEqual(list(scratch.iterdir()), [])
            self.assertEqual(os.environ.get("TMPDIR"), original_tmpdir)

    def test_parts_match_global_sort_with_relaxed_schemas_and_duplicate_rows(self):
        first = pl.DataFrame({
            "id": pl.Series([2**64 - 1, 2**64 - 1, 1], dtype=pl.UInt64),
            "key": ["z", "z", None],
            "amount": pl.Series([Decimal("1.23"), Decimal("1.23"), None], dtype=pl.Decimal(18, 2)),
            "items": [["a", None], ["a", None], []],
            "date": [date(2024, 1, 1), date(2024, 1, 1), None],
        }).lazy()
        second = pl.DataFrame({
            "id": pl.Series([2], dtype=pl.UInt64),
            "key": ["a"],
            "amount": pl.Series([Decimal("-2.10")], dtype=pl.Decimal(18, 2)),
            "items": [None],
            "extra": ["preserved"],
        }).lazy()
        frames = [first, second]
        expected = pl.concat(frames, how="diagonal_relaxed").sort("key", "id").collect()

        with TemporaryDirectory() as directory:
            path = Path(directory) / "sorted.parquet"
            sink_sorted_parquet_parts(frames, path, ["key", "id"], compression="snappy")
            assert_frame_equal(pl.read_parquet(path), expected)
            self.assertEqual(pq.read_metadata(path).row_group(0).column(0).compression, "SNAPPY")
            self.assertEqual(list(path.parent.iterdir()), [path])

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
