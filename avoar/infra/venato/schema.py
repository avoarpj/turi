from dataclasses import dataclass
from typing import Callable
from pathlib import Path
from tantivy import SchemaBuilder

@dataclass
class VenatoSchemaColumn:
    name: str
    type: str
    stored: bool = True
    fast: bool = False
    index_option: str | None = None
    tokenizer_name: str | None = None
    script_id: str | None = None 

@dataclass
class VenatoSchemaSource:
    path: Path
    format: str

@dataclass
class VenatoSchemaConfig:
    index_id: str
    producer_script: str | None
    columns: list[VenatoSchemaColumn]
    sources: list[VenatoSchemaSource]

    def resolve_raw_type_to_schemafunc(self, raw_type: str, builder: SchemaBuilder):
        raw_type_mapping: dict[str, Callable[..., SchemaBuilder]] = {
            "text": builder.add_text_field,
            "string": builder.add_text_field,
            "int": builder.add_integer_field,
            "i64": builder.add_integer_field,
            "u64": builder.add_integer_field,
            "float": builder.add_float_field,
            "bool": builder.add_boolean_field,
            "date": builder.add_date_field,
        }

        if raw_type not in raw_type_mapping:
            raise ValueError(f"Unsupported raw type: {raw_type}")

        return raw_type_mapping[raw_type]