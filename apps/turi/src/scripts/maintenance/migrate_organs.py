"""Rename legislative-house references in final Parquets without rerunning ETL."""
import argparse
import json
from pathlib import Path
from uuid import uuid4

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq

from avoar.projectsettings.globals import OPENDATA_DUMPS_OUTPUT_DIR
from scripts.maintenance.bloom_final_parquets import bloom_columns, bloom_coverage


def migrate_parquet(path: Path) -> dict | None:
    with pq.ParquetFile(path) as source:
        names = source.schema_arrow.names
        renamed = [name.replace('casa_legislativa_id', 'orgao_id') for name in names]
        if renamed == names:
            return None
        if len(set(renamed)) != len(renamed):
            raise ValueError(f'Conflicting organ columns in {path}')

        schema = pa.schema(
            [
                field.with_name(name)
                for field, name in zip(source.schema_arrow, renamed)
            ],
            metadata=source.schema_arrow.metadata,
        )
        groups = [
            source.metadata.row_group(index)
            for index in range(source.metadata.num_row_groups)
        ]
        if any(group.total_byte_size > 512 * 1024 * 1024 for group in groups):
            raise ValueError(f'Row group exceeds memory guard in {path}')
        if any(group.sorting_columns != groups[0].sorting_columns for group in groups):
            raise ValueError(f'Mixed sorting metadata in {path}')

        codecs = {}
        for group in groups:
            for index in range(group.num_columns):
                column = group.column(index)
                name = column.path_in_schema.replace('casa_legislativa_id', 'orgao_id')
                codec = column.compression.lower()
                codec = 'none' if codec == 'uncompressed' else codec
                if name in codecs and codecs[name] != codec:
                    raise ValueError(f'Mixed compression for {name} in {path}')
                codecs[name] = codec

        supported, _ = bloom_columns(source)
        ndv = max((group.num_rows for group in groups), default=1)
        blooms = {
            name.replace('casa_legislativa_id', 'orgao_id'): {'ndv': max(ndv, 1), 'fpp': 0.05}
            for name in supported
        }
        original_stat = path.stat()
        staging = path.with_name(f'.{path.name}.{uuid4().hex}.organs')

        try:
            with pq.ParquetWriter(
                staging,
                schema,
                compression=codecs,
                sorting_columns=groups[0].sorting_columns if groups else None,
                use_compliant_nested_type=False,
                bloom_filter_options=blooms,
            ) as writer:
                for index, group in enumerate(groups):
                    table = (
                        source.read_row_group(index)
                        .rename_columns(renamed)
                        .cast(schema)
                    )
                    writer.write_table(table, row_group_size=max(group.num_rows, 1))

            with pq.ParquetFile(staging) as output:
                if not output.schema_arrow.equals(schema, check_metadata=True):
                    raise ValueError(f'Schema audit failed for {path}')
                if output.metadata.num_rows != source.metadata.num_rows:
                    raise ValueError(f'Row count audit failed for {path}')
                if output.metadata.num_row_groups != len(groups):
                    raise ValueError(f'Row group audit failed for {path}')

                for index, group in enumerate(groups):
                    expected = (
                        source.read_row_group(index)
                        .rename_columns(renamed)
                        .cast(schema)
                    )
                    actual = output.read_row_group(index)
                    if not pl.from_arrow(expected).equals(pl.from_arrow(actual)):
                        raise ValueError(f'Content audit failed for {path}, group {index}')
                    if output.metadata.row_group(index).sorting_columns != group.sorting_columns:
                        raise ValueError(f'Sorting metadata audit failed for {path}')

                columns, _ = bloom_columns(output)
                present, required = bloom_coverage(output.metadata, columns)
                if present != required:
                    raise ValueError(f'Bloom filter audit failed for {path}')

            current_stat = path.stat()
            if (current_stat.st_size, current_stat.st_mtime_ns) != (
                original_stat.st_size, original_stat.st_mtime_ns,
            ):
                raise ValueError(f'Source changed during migration: {path}')

            staging.chmod(original_stat.st_mode & 0o777)
            staging.replace(path)
        finally:
            staging.unlink(missing_ok=True)

        return {
            'file': str(path),
            'rows': source.metadata.num_rows,
            'renamed': {old: new for old, new in zip(names, renamed) if old != new},
            'all_values_and_order_preserved': True,
            'bloom_filter_chunks': present,
        }


def migrate_organs(root: Path) -> list[dict]:
    old_catalog = root / 'opendata_legislative_house'
    new_catalog = root / 'opendata_organ'
    if old_catalog.exists() and new_catalog.exists():
        raise ValueError('Both organ catalogs exist; reconcile them before migration')

    records = []
    for path in sorted(root.rglob('*.parquet')):
        record = migrate_parquet(path)
        if record is not None:
            records.append(record)

    if old_catalog.exists():
        old_catalog.rename(new_catalog)

    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=OPENDATA_DUMPS_OUTPUT_DIR)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()

    records = migrate_organs(args.root)
    report = json.dumps(records, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report + '\n')
    print(report)


if __name__ == '__main__':
    main()
