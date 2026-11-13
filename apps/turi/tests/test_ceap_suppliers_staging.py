from logging import getLogger
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import polars as pl
from polars.testing import assert_frame_equal

from scripts.operations.services_supplier import camaradosdeputados as operation


class CeapSupplierStagingTests(unittest.TestCase):
    def test_multiple_downloads_keep_global_names_priority_and_supplier_ids(self):
        records = [
            {"cnpjCPF": "12345678901", "fornecedor": "Mesmo Nome", "unused": "a"},
            {"cnpjCPF": "???", "fornecedor": "mesmo nome", "unused": "b"},
            {"cnpjCPF": "00123456000199", "fornecedor": "Empresa", "unused": "c"},
            {"cnpjCPF": "00987654321", "fornecedor": " Outro Nome ", "unused": "d"},
        ]

        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw"
            raw.mkdir()
            pl.DataFrame({"dados": [records]}).write_parquet(raw / "a.parquet")
            pl.DataFrame({"dados": [records[:2]]}).write_parquet(raw / "b.parquet")
            suppliers = root / "suppliers.parquet"
            names = root / "names.parquet"

            with patch.multiple(
                operation,
                CD_SERVICES_SUPPLIER_RAW_PARQUETS=raw / "*.parquet",
                CD_SERVICES_SUPPLIER_OUTPUT_PARQUETS=suppliers,
                CD_SERVICES_SUPPLIER_NAMES_OUTPUT_PARQUETS=names,
            ):
                operation.script_instance.process_data(getLogger(__name__))

            actual_suppliers = pl.read_parquet(suppliers)
            actual_names = pl.read_parquet(names)

            with patch.multiple(
                operation,
                CD_SERVICES_SUPPLIER_OUTPUT_PARQUETS=root / "direct_suppliers.parquet",
                CD_SERVICES_SUPPLIER_NAMES_OUTPUT_PARQUETS=root / "direct_names.parquet",
            ):
                direct = (
                    pl.scan_parquet(raw / "*.parquet")
                    .select(pl.col("dados").list.explode())
                    .unnest("dados")
                )
                operation.script_instance._process_data(direct, getLogger(__name__))

            assert_frame_equal(
                actual_suppliers.sort("id"), pl.read_parquet(root / "direct_suppliers.parquet").sort("id"),
            )
            assert_frame_equal(
                actual_names.sort("id"), pl.read_parquet(root / "direct_names.parquet").sort("id"),
            )
            self.assertEqual(actual_suppliers.height, 3)
            self.assertEqual(actual_names.height, 2)
            cpf_supplier = actual_suppliers.filter(pl.col("documento") == "12345678901")["id"].item()
            self.assertEqual(
                actual_names.filter(pl.col("nome") == "MESMO NOME")["fornecedor_id"].item(), cpf_supplier,
            )
