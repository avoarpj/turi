from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import polars as pl

if TYPE_CHECKING:
    from infra.datascript.DataScript import DataScript


def write_metadata(script: "DataScript", executed_at: datetime) -> None:
    """Publish metadata beside every output, preserving other producers."""
    metadata = pl.DataFrame(
        [{
            "script_id": script.script_id,
            "lifetime": script.lifetime,
            "source": script.source,
            "source_url": script.source_url,
            "description": script.description,
            "input_paths": [str(path) for path in script.input_paths],
            "output_paths": [str(path) for path in script.output_paths],
            "dependencies": script.dependencies,
            "tags": script.tags,
            "last_successful_execution": executed_at.isoformat(),
        }],
        schema={
            "script_id": pl.String,
            "lifetime": pl.String,
            "source": pl.String,
            "source_url": pl.String,
            "description": pl.String,
            "input_paths": pl.List(pl.String),
            "output_paths": pl.List(pl.String),
            "dependencies": pl.List(pl.String),
            "tags": pl.List(pl.String),
            "last_successful_execution": pl.String,
        },
    )

    directories = sorted({path.parent for path in script.output_paths})

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "metadata.avro"
        records = metadata

        if target.exists():
            previous = pl.read_avro(target).filter(pl.col("script_id") != script.script_id)
            records = pl.concat([previous, metadata], how="diagonal_relaxed")

        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")

        try:
            records.sort("script_id").write_avro(temporary)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
