from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

from scripts.maintenance.migrate_organs import migrate_organs


class OrganMigrationTest(unittest.TestCase):
    def test_preserves_values_uint64_nested_data_metadata_and_row_groups(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            old_catalog = root / 'opendata_legislative_house'
            old_catalog.mkdir()
            path = root / 'references.parquet'
            schema = pa.schema([
                pa.field('id', pa.uint64()),
                pa.field('casa_legislativa_id', pa.string(), metadata={'domain': 'organ'}),
                pa.field('coletado_de_casa_legislativa_id', pa.string()),
                pa.field('total', pa.decimal128(12, 2)),
                pa.field('items', pa.list_(pa.int64())),
            ], metadata={'source': 'fixture'})
            source = pa.Table.from_pylist([
                {'id': 2**64 - 1, 'casa_legislativa_id': 'cd',
                 'coletado_de_casa_legislativa_id': None, 'total': Decimal('12.34'), 'items': [1, 2]},
                {'id': 1, 'casa_legislativa_id': None,
                 'coletado_de_casa_legislativa_id': 'sf', 'total': None, 'items': []},
            ], schema=schema)
            pq.write_table(source, path, row_group_size=1, compression='zstd')

            records = migrate_organs(root)
            actual = pq.read_table(path)
            self.assertEqual(len(records), 1)
            self.assertTrue(actual.equals(source.rename_columns([
                'id', 'orgao_id', 'coletado_de_orgao_id', 'total', 'items',
            ])))
            self.assertEqual(actual.schema.metadata, schema.metadata)
            self.assertEqual(
                actual.schema.field('orgao_id').metadata,
                schema.field('casa_legislativa_id').metadata,
            )
            self.assertEqual(pq.ParquetFile(path).metadata.num_row_groups, 2)
            self.assertTrue((root / 'opendata_organ').is_dir())
            self.assertFalse(old_catalog.exists())
            self.assertGreater(records[0]['bloom_filter_chunks'], 0)

            before = path.read_bytes()
            self.assertEqual(migrate_organs(root), [])
            self.assertEqual(path.read_bytes(), before)
