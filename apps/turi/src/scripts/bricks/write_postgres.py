import polars as pl
from typing import Sequence
from enum import Enum
from adbc_driver_postgresql.dbapi import Connection

class WriterBrickDataframeInput():
    table_name: str
    before_queries: list[str]
    after_queries: list[str]
    dataframe: pl.DataFrame

    def __init__(
        self,
        table_name: str,
        before_queries: list[str],
        after_queries: list[str],
        dataframe: pl.DataFrame
    ):
        self.table_name = table_name
        self.before_queries = before_queries
        self.after_queries = after_queries
        self.dataframe = dataframe

class LazyFrameInputMode(Enum):
    GOHORSE = 1 # allocate everything directly on ram (will explode your ram. do not use in production)
    STREAM = 2

class WriterBrickLazyFrameInput():
    table_name: str
    before_queries: list[str]
    after_queries: list[str]
    dataframe: pl.LazyFrame
    input_mode: LazyFrameInputMode
    
    def __init__(
        self,
        table_name: str,
        before_queries: list[str],
        after_queries: list[str],
        dataframe: pl.LazyFrame,
        input_mode: LazyFrameInputMode
    ):
        self.table_name = table_name
        self.before_queries = before_queries
        self.after_queries = after_queries
        self.dataframe = dataframe
        self.input_mode = input_mode


class PolarsPostgresWriterBrick():
    connection: Connection

    def __init__(self, connection: Connection):

        self.connection = connection

    def _write_dataframe(self, table_name: str, df: pl.DataFrame):
        df.write_database(
            table_name=table_name,
            connection=self.connection,
            engine="adbc",
            if_table_exists="append"
        )

    def _write_lazyframes_gohorsed(self, table_name: str, dataframe: pl.LazyFrame):
        frame = dataframe.collect()

        self._write_dataframe(table_name, frame)

    def _write_lazyframes_rationalway(self, table_name: str, dataframe: pl.LazyFrame):
        # use streaming to avoid exploding ram
        batches = dataframe.collect_batches(
            chunk_size=300000,
            maintain_order=False
        )

        for batch in batches:
            self._write_dataframe(table_name, batch)

    def write_postgres(self, inputs: Sequence[WriterBrickDataframeInput | WriterBrickLazyFrameInput]):
        for input in inputs:
            cursor = self.connection.cursor()
            
            try:
                for bquery in input.before_queries:
                    cursor.execute(bquery)

                if isinstance(input, WriterBrickDataframeInput):
                    self._write_dataframe(input.table_name, input.dataframe)
                elif isinstance(input, WriterBrickLazyFrameInput):
                    if input.input_mode == LazyFrameInputMode.GOHORSE:
                        self._write_lazyframes_gohorsed(input.table_name, input.dataframe)
                    elif input.input_mode == LazyFrameInputMode.STREAM:
                        self._write_lazyframes_rationalway(input.table_name, input.dataframe)

                for aquery in input.after_queries:
                    cursor.execute(aquery)

            except Exception as err:
                cursor.close()
                raise err
            finally:
                cursor.close()

            
