from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import polars as pl
from polars.testing import assert_frame_equal

from infra.parquet_staging import staged_nested_parquets


class ParquetStagingTests(unittest.TestCase):
    def test_expansion_preserves_schema_duplicates_nulls_and_full_row_hashes(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw"
            raw.mkdir()
            rows = [
                {"name": "Árvore", "value": None, "amount": 1.25},
                {"name": "", "value": "000123", "amount": None},
                {"name": "Árvore", "value": None, "amount": 1.25},
            ]

            for index in range(2):
                pl.DataFrame({"dados": [rows]}).write_parquet(raw / f"{index}.parquet")

            (raw / "empty.parquet").touch()
            source = raw / "*.parquet"
            expected = (
                pl.scan_parquet(source)
                .select(pl.col("dados").list.explode())
                .unnest("dados")
                .with_columns(pl.struct(pl.all()).hash(seed=42).alias("id"))
                .collect()
            )

            with staged_nested_parquets(source, work_directory=root / "work") as frame:
                actual = frame.with_columns(pl.struct(pl.all()).hash(seed=42).alias("id")).collect()
                assert_frame_equal(actual, expected)

            self.assertEqual(list((root / "work").iterdir()), [])

    def test_projected_scan_is_cleaned_up_when_consumer_fails(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "raw.parquet"
            pl.DataFrame({"dados": [[{"document": "001", "name": "Teste"}]]}).write_parquet(source)

            with self.assertRaisesRegex(ValueError, "consumer"):
                with staged_nested_parquets(
                    source, work_directory=root / "work", columns=["document"],
                ) as frame:
                    self.assertEqual(frame.collect().to_dicts(), [{"document": "001"}])
                    raise ValueError("consumer failed")

            self.assertEqual(list((root / "work").iterdir()), [])
