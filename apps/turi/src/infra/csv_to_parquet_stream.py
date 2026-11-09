import string
from itertools import islice
from pathlib import Path
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


def generate_excel_column_names():
    # Primeira volta: A até Z
    for char in string.ascii_uppercase:
        yield char

    suffix = 1
    while True:
        for char in string.ascii_uppercase:
            yield f"{char}{suffix}"
        suffix += 1


def csv_to_parquet_stream(
    source_path: Path,
    target_path: Path,
    sep: str = ";",
    encoding: str = "ISO-8859-1",
    chunk_size: int = 100_000,
    has_header: bool = True,
    headers: list[str] | None = None
):
    with open(source_path, "r", encoding=encoding, errors="replace") as f:
        first_line = f.readline()
        num_cols = len(first_line.split(sep))

    col_names = None
    if not has_header:
        col_names = list(islice(generate_excel_column_names(), num_cols))

    if headers is not None:
        col_names = headers

    writer = None

    try:
        for chunk in pd.read_csv(
            source_path,
            sep=sep,
            encoding=encoding,
            dtype=str,
            chunksize=chunk_size,
            low_memory=False,
            header=0 if has_header else None,
            names=col_names,
        ):
            table = pa.Table.from_pandas(chunk, preserve_index=False)

            if writer is None:
                writer = pq.ParquetWriter(
                    target_path,
                    table.schema,
                    compression="snappy",
                )

            writer.write_table(table)

    finally:
        if writer:
            writer.close()