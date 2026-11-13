from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import polars as pl
from polars.testing import assert_frame_equal

from infra.diskful_unique import (
    diskful_unique,
    diskful_unique_session,
)


class DiskfulUniqueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.session = diskful_unique_session(self.temporary.name)
        self.workspace = self.session.__enter__()
        self.addCleanup(self.session.__exit__, None, None, None)

    def test_keep_modes_match_polars_across_batches_and_row_groups(self):
        frame = pl.DataFrame({
            "id": [1, 2, 1, None, 3, 2, None, 4],
            "value": list("abcdefgh"),
        })

        for keep in ("any", "first", "last", "none"):
            for batch_size in (1, 3, 100):
                with self.subTest(keep=keep, batch_size=batch_size):
                    result = diskful_unique(
                        frame.lazy(), "id", keep=keep,
                        maintain_order=True, batch_size=batch_size,
                    ).collect()
                    expected = frame.unique(
                        subset="id",
                        keep="first" if keep == "any" else keep,
                        maintain_order=True,
                    )

                    assert_frame_equal(result, expected)

    def test_full_rows_composite_keys_and_ambiguous_string_boundaries(self):
        frame = pl.DataFrame({
            "first": ["a|b", "a", "a|b", "", None, "null", "a|b"],
            "second": ["c", "b|c", "c", None, "", "", "c"],
            "value": [1, 2, 3, 4, 5, 6, 1],
        })

        for columns in (None, ["first", "second"]):
            with self.subTest(columns=columns):
                actual = diskful_unique(
                    frame.lazy(), subset=columns, batch_size=2,
                ).collect()
                expected = frame.unique(
                    subset=columns, keep="first", maintain_order=True,
                )

                assert_frame_equal(actual, expected)

    def test_exact_keys_and_representatives_survive_multiple_merge_passes(self):
        frame = pl.DataFrame({
            "id": [f"prefix-{i % 23:03d}" for i in range(200)],
            "value": list(range(200)),
        })

        with patch("infra.diskful_unique._MERGE_FAN_IN", 2):
            for keep in ("first", "last", "none"):
                actual = diskful_unique(
                    frame.lazy(), "id", keep=keep, batch_size=7,
                ).collect()
                expected = frame.unique(subset="id", keep=keep, maintain_order=True)

                assert_frame_equal(actual, expected)

    def test_null_nan_signed_zero_and_noncanonical_nan_bits(self):
        frame = pl.DataFrame({
            "key": [None, float("nan"), -float("nan"), 0.0, -0.0, float("inf"), None],
            "value": list("abcdefg"),
        })

        for keep in ("first", "last", "none"):
            actual = diskful_unique(frame.lazy(), "key", keep=keep, batch_size=1).collect()
            expected = frame.unique(subset="key", keep=keep, maintain_order=True)

            assert_frame_equal(actual, expected)

    def test_unsigned_nested_temporal_decimal_binary_and_categorical_types(self):
        frame = pl.DataFrame({
            "id": pl.Series([2**64 - 1, 2, 2**64 - 1], dtype=pl.UInt64),
            "list": [[1, None], [], [1, None]],
            "struct": [{"x": "a", "y": 1.0}, None, {"x": "a", "y": 1.0}],
            "date": [date(1800, 1, 1), None, date(1800, 1, 1)],
            "timestamp": [datetime(2024, 1, 1, tzinfo=timezone.utc), None,
                          datetime(2024, 1, 1, tzinfo=timezone.utc)],
            "duration": [timedelta(microseconds=-1), None, timedelta(microseconds=-1)],
            "decimal": [Decimal("123456789012345678901234567890.12"), None,
                        Decimal("123456789012345678901234567890.12")],
            "binary": [b"a\x00b", b"", b"a\x00b"],
            "category": pl.Series(["a", "b", "a"], dtype=pl.Categorical),
            "enum": pl.Series(["a", "b", "a"], dtype=pl.Enum(["a", "b"])),
        })
        actual = diskful_unique(frame.lazy(), batch_size=1).collect()
        expected = frame.unique(keep="first", maintain_order=True)

        assert_frame_equal(actual, expected)

    def test_nanoseconds_are_not_rounded_when_building_keys(self):
        frame = pl.DataFrame({
            "timestamp": pl.Series([1, 2, 1], dtype=pl.Int64).cast(pl.Datetime("ns")),
            "duration": pl.Series([1, 2, 1], dtype=pl.Int64).cast(pl.Duration("ns")),
        })

        for variant in (
            frame,
            frame.select(pl.struct(pl.all()).alias("nested")),
            frame.select(pl.concat_list(pl.col("timestamp")).alias("nested")),
        ):
            actual = diskful_unique(variant.lazy(), batch_size=1).collect()

            assert_frame_equal(actual, variant.unique(keep="first", maintain_order=True))

    def test_empty_and_all_duplicate_inputs_keep_the_schema(self):
        for frame in (
            pl.DataFrame(schema={"id": pl.UInt64, "value": pl.String}),
            pl.DataFrame({"id": [1, 1], "value": ["a", "a"]}),
            pl.DataFrame({"id": [None, None], "value": [None, None]}),
        ):
            for keep in ("first", "none"):
                actual = diskful_unique(frame.lazy(), keep=keep, batch_size=1).collect()
                expected = frame.unique(keep=keep, maintain_order=True)

                assert_frame_equal(actual, expected)

    def test_invalid_arguments_fail_before_creating_files(self):
        frame = pl.LazyFrame({"id": [1]})

        for kwargs in (
            {"subset": "missing"}, {"subset": []}, {"subset": [1]},
            {"keep": "invalid"}, {"batch_size": 0}, {"memory_limit": "0GB"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                diskful_unique(frame, **kwargs)

        with self.assertRaises(ValueError):
            diskful_unique(frame, "id", subset="id")
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_result_survives_reassignment_reuse_and_multiple_lazy_consumers(self):
        frame = pl.LazyFrame({"id": [2, 1, 2], "value": [20, 10, 99]})
        frame = diskful_unique(frame, "id", batch_size=1)
        frame = frame.filter(pl.col("id") > 0).with_columns(pl.col("value") + 1)

        for _ in range(2):
            self.assertEqual(frame.sort("id").collect()["value"].to_list(), [11, 21])
        self.assertEqual(frame.select(pl.len()).collect().item(), 2)

        directories = list(self.workspace.iterdir())
        self.assertEqual(len(directories), 1)
        self.assertEqual([item.name for item in directories[0].iterdir()], ["result.parquet"])

    def test_failure_removes_partial_index_and_output(self):
        with patch("infra.diskful_unique._write_keys", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                diskful_unique(pl.LazyFrame({"id": [1]}))

        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_nested_sessions_remove_only_their_own_results(self):
        outer = diskful_unique(pl.LazyFrame({"id": [1, 1]}))

        with diskful_unique_session(self.workspace):
            inner = diskful_unique(pl.LazyFrame({"id": [2, 2]}))
            self.assertEqual(inner.collect()["id"].to_list(), [2])

        self.assertEqual(outer.collect()["id"].to_list(), [1])
        with self.assertRaises(FileNotFoundError):
            inner.collect()

    def test_file_creation_is_per_run_rather_than_per_distinct_key(self):
        from infra import diskful_unique as implementation

        frame = pl.LazyFrame({"id": list(range(1000)) * 2})
        write_keys = implementation._write_keys
        created = []

        def observe_run(path, records, buffering):
            created.append(path)
            return write_keys(path, records, buffering)

        with patch("infra.diskful_unique._write_keys", side_effect=observe_run):
            result = diskful_unique(frame, batch_size=128).collect()

        self.assertEqual(result["id"].to_list(), list(range(1000)))
        self.assertLess(len(created), 25)
