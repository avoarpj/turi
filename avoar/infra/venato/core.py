from dataclasses import asdict
from pathlib import Path
from typing import TypedDict, Callable, Any
import math
import ctypes
import shutil
import yaml
import pyarrow.parquet as pq
import importlib
from datetime import datetime, timezone
from tantivy import SchemaBuilder, Index, Query, Order, Document

from avoar.infra.venato.config import VenatoConfig
from avoar.infra.venato.schema import VenatoSchemaConfig, VenatoSchemaColumn, VenatoSchemaSource
from avoar.projectsettings.globals import PROJECT_ROOT

def _cast_int64(val: Any) -> int:
    return ctypes.c_int64(int(val)).value

def _cast_date(val: Any) -> datetime:
    if isinstance(val, datetime):
        if val.tzinfo is not None:
            val = val.astimezone(timezone.utc)
        return val.replace(tzinfo=None)

    if hasattr(val, "year") and not hasattr(val, "hour"):
        return datetime(val.year, val.month, val.day)

    dt = pd.to_datetime(val)
    if dt.tzinfo is not None:
        dt = dt.tz_convert("UTC")
    return dt.tz_localize(None).to_pydatetime()

TYPE_COERCERS: dict[str, Callable[[Any], Any]] = {
    "u64": _cast_int64,
    "i64": _cast_int64,
    "int": _cast_int64,
    "float": lambda v: float(v),
    "text": lambda v: str(v),
    "string": lambda v: str(v),
    "bool": lambda v: bool(v),
    "date": _cast_date,
}

class SearchParameters(TypedDict, total=False):
    query: Query
    limit: int
    count: bool
    order_by_field: str | None
    offset: int
    order: Order
    weight_by_field: str | None

class Venato(VenatoConfig):
    _indexes: dict[str, Index] = {}

    def __init__(self, config: VenatoConfig):
        self.config = config

    def create_index(self, schema_config: VenatoSchemaConfig, recreate: bool = False) -> Index:
        schema_builder = SchemaBuilder()

        for column in schema_config.columns:
            create_field_func = schema_config.resolve_raw_type_to_schemafunc(column.type, schema_builder)
            kwargs = asdict(column)
            kwargs.pop("type", None)

            if column.type not in ("text", "string"):
                kwargs.pop("tokenizer_name", None)
                kwargs.pop("index_option", None)

            kwargs = {k: v for k, v in kwargs.items() if v is not None}
            create_field_func(**kwargs)

        schema = schema_builder.build()
        index_path = self.config.data_dir / "indexes" / schema_config.index_id
        index_path.mkdir(parents=True, exist_ok=True)

        index = Index(schema, path=str(index_path), reuse=(not recreate))
        self._indexes[schema_config.index_id] = index
        return index

    def get_or_create_index(self, schema_config: VenatoSchemaConfig) -> Index:
        index_path = self.config.data_dir / "indexes" / schema_config.index_id

        if index_path.exists() and any(index_path.iterdir()):
            return Index.open(str(index_path))
        
        return self.create_index(schema_config)

    def _resolve_source_files(self, source_path: Path) -> list[Path]:
        if not source_path.is_absolute():
            source_path = PROJECT_ROOT / source_path

        path_str = str(source_path)

        if "*" in path_str or "?" in path_str:
            parts = source_path.parts
            base_idx = next(i for i, part in enumerate(parts) if "*" in part or "?" in part)
            base_dir = Path(*parts[:base_idx])
            pattern = str(Path(*parts[base_idx:]))

            if not base_dir.exists():
                return []

            return sorted(base_dir.glob(pattern))
        
        if source_path.is_file():
            return [source_path]
        if source_path.is_dir():
            return sorted(source_path.glob("*.parquet"))
        
        return []

    def ingest_schema_sources(self, schema_config: VenatoSchemaConfig, batch_size: int = 500_000, heap_size_mb: int = 2048):
        index = self.get_or_create_index(schema_config)
        writer = index.writer(heap_size_mb * 1024 * 1024, num_threads=12)

        column_coercers: dict[str, Callable] = {
            col.name: TYPE_COERCERS[col.type]
            for col in schema_config.columns
            if col.type in TYPE_COERCERS
        }

        # Coleta todos os arquivos alvo declarados nos sources
        target_files = []
        for source in schema_config.sources:
            if source.format.lower() == "parquet":
                target_files.extend(self._resolve_source_files(source.path))

        if not target_files:
            return

        # Determina o gerador de batches
        if schema_config.producer_script:
            module = importlib.import_module(schema_config.producer_script)
            produce_func = getattr(module, "produce_batches")
            batches_iter = produce_func(target_files, PROJECT_ROOT, batch_size=batch_size)
        else:
            def default_parquet_reader():
                for file_path in target_files:
                    pf = pq.ParquetFile(file_path)
                    cols = [c for c in column_coercers.keys() if c in pf.schema_arrow.names]
                    for b in pf.iter_batches(batch_size=batch_size, columns=cols):
                        yield b
            batches_iter = default_parquet_reader()

        # Loop de ingestão rápido
        for batch in batches_iter:
            num_rows = batch.num_rows
            schema_names = batch.schema.names
            
            # Converte apenas as colunas necessárias para listas nativas C (to_pylist)
            # Isso é ordens de magnitude mais rápido que batch.to_pydict() ou pa.Array[i]
            cols_data = {}
            for name in schema_names:
                if name in column_coercers:
                    cols_data[name] = batch.column(name).to_pylist()

            col_keys = list(cols_data.keys())

            # Despeja no Tantivy
            for i in range(num_rows):
                doc_fields = {}
                for col_name in col_keys:
                    val = cols_data[col_name][i]
                    if val is None or val == "":
                        continue

                    coercer = column_coercers.get(col_name)
                    if coercer:
                        try:
                            val = coercer(val)
                        except (ValueError, TypeError, OverflowError):
                            continue

                    doc_fields[col_name] = [val]

                if doc_fields:
                    writer.add_document(Document(**doc_fields))

        writer.commit()
        writer.wait_merging_threads()

    def ingest_all(self):
        yaml_files = (Path(__file__).parent / "indexes").glob("*.yaml")

        for yaml_file in yaml_files:
            schema_config = self.read_index_declaration(yaml_file)

            has_valid_sources = False
            for source in schema_config.sources:
                if source.format.lower() == "parquet":
                    if self._resolve_source_files(source.path):
                        has_valid_sources = True
                        break

            if not has_valid_sources:
                continue

            self.ingest_schema_sources(schema_config)

    def prune_index(self, index_id: str, recreate: bool = False, schema_config: VenatoSchemaConfig | None = None) -> Index:
        index_path = self.config.data_dir / "indexes" / index_id

        if recreate:
            if not schema_config:
                raise ValueError("schema_config é obrigatório para recriar o índice do zero com recreate=True")
            
            self._indexes.pop(index_id, None)

            if index_path.exists():
                shutil.rmtree(index_path)

            return self.create_index(schema_config)

        if index_id not in self._indexes:
            if index_path.exists():
                self.load_index(index_id)
            elif schema_config:
                return self.create_index(schema_config)
            else:
                raise FileNotFoundError(f"Índice '{index_id}' não encontrado em disco e nenhum schema_config foi fornecido.")

        index = self._indexes[index_id]
        
        writer = index.writer(30_000_000)
        writer.delete_all_documents()
        writer.commit()

        return index

    def prune_all(self):
        self._indexes.clear()

        indexes_path = self.config.data_dir / "indexes"
        if not indexes_path.exists():
            return

        for item in indexes_path.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

    def load_index(self, index_id: str):
        index_path = self.config.data_dir / "indexes" / index_id

        if not index_path.exists():
            raise FileNotFoundError(f"Cannot find index directory: {index_path}")
        
        self._indexes[index_id] = Index.open(str(index_path))

    def startup(self):
        schemas_path = self.config.data_dir / "indexes"
        if not schemas_path.exists():
            return

        for index_path in schemas_path.iterdir():
            if index_path.is_dir():
                self.load_index(index_path.name)

    def search(self, index_id: str, search_kwargs: SearchParameters):
        index = self._indexes.get(index_id)
        
        if index is None:
            raise KeyError(f"Index '{index_id}' is not loaded.")

        searcher = index.searcher()
        return searcher.search(**search_kwargs)

    def search_ids(
        self, index_id: str, input: str, default_fields: list[str], id_field: str = "id"
    ) -> list[Any]:
        documents = self._iter_search_documents(index_id, input, default_fields)
        return [value for document in documents for value in document.get(id_field, [])]

    def search_documents(
        self, index_id: str, input: str, default_fields: list[str]
    ) -> list[dict[str, list[Any]]]:
        return list(self._iter_search_documents(index_id, input, default_fields))

    def search_scored_ids(
        self, index_id: str, input: str, default_fields: list[str], id_field: str = "id"
    ) -> list[tuple[Any, float]]:
        documents = self._iter_scored_documents(index_id, input, default_fields)

        return [
            (value, score)
            for score, document in documents
            for value in document.get(id_field, [])
        ]

    def _iter_search_documents(
        self, index_id: str, input: str, default_fields: list[str]
    ):
        for _, document in self._iter_scored_documents(index_id, input, default_fields):
            yield document

    def _iter_scored_documents(
        self, index_id: str, input: str, default_fields: list[str]
    ):
        schema = self.read_index_declaration(Path(__file__).parent / "indexes" / f"{index_id}.yaml")
        unsigned_fields = [column.name for column in schema.columns if column.stored and column.type == "u64"]

        if index_id not in self._indexes:
            self.load_index(index_id)

        index = self._indexes[index_id]
        query = index.parse_query(input, default_fields)
        searcher = index.searcher()
        if not searcher.num_docs:
            return

        # Keep all matches: the columnar query applies filters and pagination.
        results = searcher.search(query, limit=searcher.num_docs, count=False)
        for score, address in results.hits:
            document = searcher.doc(address).to_dict()
            # u64 fields use signed storage in Tantivy; restore their declared type.
            for field in unsigned_fields:
                if field in document:
                    document[field] = [ctypes.c_uint64(value).value for value in document[field]]
            yield score, document

    def read_index_declaration(self, path: Path) -> VenatoSchemaConfig:
        with open(path, "r", encoding="utf-8") as file:
            data = yaml.safe_load(file)

        columns = [
            VenatoSchemaColumn(
                name=col["name"],
                stored=col.get("stored", True),
                fast=col.get("fast", False),
                index_option=col.get("index_option"),
                tokenizer_name=col.get("tokenizer_name"),
                type=col["type"]
            )
            for col in data.get("columns", [])
        ]

        sources = [
            VenatoSchemaSource(
                format=src["format"],
                path=Path(src["path"])
            )
            for src in data.get("sources", [])
        ]

        return VenatoSchemaConfig(
            index_id=data["index_id"],
            columns=columns,
            sources=sources,
            producer_script=data.get("producer_script", None)
        )
