from pathlib import Path
import json
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

from avoar.core.opendata.election.domain import CargoEleicao
from avoar.core.opendata.municipality.domain import Municipio
from avoar.core.validation import decimal_value, validate
from avoar.infra.venato.config import VenatoConfig
from avoar.infra.venato.core import Venato
from avoar.infra.venato.schema import VenatoSchemaColumn, VenatoSchemaConfig, VenatoSchemaSource
from avoar.projectsettings.globals import PROJECT_ROOT
from apps.turi.src.config.projectsettings.settings import PROJECT_ROOT as TURI_ROOT


class StandaloneTests(TestCase):
    def test_core_and_turi_import_together_outside_the_checkout(self):
        root = Path(__file__).resolve().parents[1]
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        code = """
import json
from avoar.core.opendata.business import domain
from avoar.infra.venato.core import Venato
from avoar.projectsettings.globals import PROJECT_ROOT
print(json.dumps({"root": str(PROJECT_ROOT), "core": domain.__file__}))
"""

        with TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-c", code], cwd=directory, env=environment,
                check=True, capture_output=True, text=True,
            )

        imported = json.loads(result.stdout)
        self.assertEqual(Path(imported["root"]), root)
        self.assertFalse(Path(imported["core"]).is_relative_to(root / "avoar"))

    def test_core_generated_contracts_and_repository_paths(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(PROJECT_ROOT, root)
        self.assertEqual(TURI_ROOT, root)
        self.assertEqual(CargoEleicao.DEPUTADO_FEDERAL.value, 5)
        validate(Municipio(
            codigo_ibge="3550308",
            nome="São Paulo",
            nome_normalizado="saopaulo",
            uf="SP",
            latitude=decimal_value("-23.550520"),
            longitude=decimal_value("-46.633308"),
        ))

    def test_unchanged_venato_ingests_parquet_and_restores_uint64(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.parquet"
            expected_id = 2**63 + 17
            pq.write_table(pa.table({
                "id": pa.array([expected_id], type=pa.uint64()),
                "nome": ["municipio"],
            }), source)
            declaration = VenatoSchemaConfig(
                index_id="standalone_test",
                producer_script=None,
                columns=[
                    VenatoSchemaColumn(name="id", type="u64"),
                    VenatoSchemaColumn(name="nome", type="text"),
                ],
                sources=[VenatoSchemaSource(path=source, format="parquet")],
            )
            venato = Venato(VenatoConfig(data_dir=root / "venato"))
            venato.ingest_schema_sources(declaration, batch_size=1, heap_size_mb=256)
            venato.load_index(declaration.index_id)

            with patch.object(venato, "read_index_declaration", return_value=declaration):
                self.assertEqual(venato.search_ids(declaration.index_id, "municipio", ["nome"]), [expected_id])

            Venato._indexes.pop(declaration.index_id, None)
