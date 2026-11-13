from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import polars as pl
import polars.selectors as cs
from polars.testing import assert_frame_equal

from config.projectsettings.settings import NUMERIC_HASH_SEED
from scripts.bricks.nullish import nullify_strings


class NullishStreamingTests(unittest.TestCase):
    def test_values_schema_column_order_and_full_row_hashes_match_replace(self):
        frame = pl.DataFrame({
            "document": ["", "000123", None, " "],
            "name": [None, "", "Árvore", "\u00a0"],
            "number": [1, 2, None, 4],
        })
        expected = frame.with_columns(cs.string().replace([""], None))
        actual = frame.lazy().with_columns(nullify_strings([""])).collect(engine="streaming")
        assert_frame_equal(actual, expected)
        assert_frame_equal(
            actual.select(pl.struct(pl.all()).hash(seed=NUMERIC_HASH_SEED)),
            expected.select(pl.struct(pl.all()).hash(seed=NUMERIC_HASH_SEED)),
        )

    def test_physical_plan_has_no_in_memory_map(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "input.parquet"
            pl.DataFrame({"first": ["", "a"], "second": ["b", ""]}).write_parquet(path)
            frame = pl.scan_parquet(path).with_columns(nullify_strings([""]))
            graph = frame.show_graph(plan_stage="physical", engine="streaming", raw_output=True)
            self.assertNotIn("in-memory-map", graph)
