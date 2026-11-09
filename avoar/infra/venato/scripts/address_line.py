from pathlib import Path
from typing import Iterator
import polars as pl
import pyarrow as pa
import pyarrow.dataset as ds
from avoar.projectsettings.globals import OPENDATA_DUMPS_OUTPUT_DIR

_MAPA_MUNICIPIOS: dict[int, str] | None = None
_MAPA_UFS: dict[int, str] | None = None

def _get_mapas_municipios() -> tuple[dict[int, str], dict[int, str]]:
    """Carrega os ~5.570 municípios do IBGE como dicionários Python em RAM (~1MB)."""
    global _MAPA_MUNICIPIOS, _MAPA_UFS
    if _MAPA_MUNICIPIOS is None or _MAPA_UFS is None:
        df = pl.read_parquet(
            OPENDATA_DUMPS_OUTPUT_DIR / "opendata_municipality" / "*.parquet",
            columns=["codigo_ibge", "nome", "uf"]
        )
        _MAPA_MUNICIPIOS = dict(zip(df["codigo_ibge"], df["nome"]))
        _MAPA_UFS = dict(zip(df["codigo_ibge"], df["uf"]))
        
    return _MAPA_MUNICIPIOS, _MAPA_UFS


def produce_batches(
    source_paths: list[Path], 
    project_root: Path, 
    batch_size: int = 100_000
):
    mapa_nome, mapa_uf = _get_mapas_municipios()

    # O PyArrow Dataset lê o arquivo Parquet em partes sem carregar tudo na RAM
    dataset = ds.dataset([str(p) for p in source_paths], format="parquet")

    # Iteramos batch por batch diretamente do disco
    for record_batch in dataset.to_batches(batch_size=batch_size):
        # Convertemos apenas o lote atual de 100k linhas para DataFrame Polars
        df_chunk = pl.from_arrow(record_batch)

        # Aplicamos o mapeamento via dict + concatenação de string APENAS no lote
        df_transformed = df_chunk.with_columns([
            pl.col("municipio")
            .replace_strict(mapa_nome, default=None, return_dtype=pl.String)
            .alias("nome_municipio"),
            
            pl.col("municipio")
            .replace_strict(mapa_uf, default=None, return_dtype=pl.String)
            .alias("uf_municipio")
        ]).with_columns([
            pl.concat_str(
                [
                    pl.col("tipo_logradouro").fill_null(""),
                    pl.col("nome_logradouro").fill_null(""),
                    pl.col("numero_logradouro").fill_null(""),
                    pl.col("descricao_localidade").fill_null(""),
                    pl.col("nome_municipio").fill_null(""),
                    pl.col("uf_municipio").fill_null(""),
                ],
                separator=" ",
                ignore_nulls=True
            ).str.strip_chars().alias("endereco_completo")
        ]).drop(["nome_municipio", "uf_municipio"])

        # Converte de volta para RecordBatch para o gerador yieldar sem estourar a RAM
        yield df_transformed.to_arrow().to_batches()[0]
