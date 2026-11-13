from logging import Logger
from pathlib import Path
from tempfile import TemporaryDirectory

import polars as pl
from config.projectsettings.settings import (
    NUMERIC_HASH_SEED,
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
)
from infra.datascript.DataScript import DataScript
from infra.diskful_unique import diskful_unique, diskful_unique_session


EVM_RAW_PARQUETS = BASE_DIR / "downloads" / "tse" / "evm_bulletin"
EVM_OUTPUT_PARQUETS = DUMPS_OUTPUT_DIR / "opendata" / "opendata_evm" / "opendata_evm.parquet"

class EvmDataScript(DataScript):
    script_id = "evm"
    lifetime = "0 6 17 * *"

    source = "Tribunal Superior Eleitoral"
    source_url = "https://dadosabertos.tse.jus.br/"
    description = (
        "Urnas eletrônicas identificadas nos boletins de urna."
    )

    input_paths = [
        EVM_RAW_PARQUETS,
    ]
    output_paths = [
        EVM_OUTPUT_PARQUETS,
    ]

    dependencies = []
    tags = []

    @diskful_unique_session()
    def process_data(self, logger: Logger):
        logger.info("process data")
        
        EVM_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True, parents=True)

        with TemporaryDirectory(prefix="urns-", dir=EVM_OUTPUT_PARQUETS.parent) as directory:
            bu_raw = _scan_tse_bulletins_dynamic(Path(directory))
            bu_raw = diskful_unique(bu_raw, "NR_URNA_EFETIVADA")

            evm_lazy = (
                bu_raw
                .with_columns([
                    pl.col("NR_URNA_EFETIVADA").hash(seed=NUMERIC_HASH_SEED).alias("id"),
                    pl.col("NR_URNA_EFETIVADA").alias("numero_serie_urna")
                ])
                .select(["id", "numero_serie_urna"])
                .sort(
                    by=["id"]
                )
            )

            evm_lazy.sink_parquet(EVM_OUTPUT_PARQUETS, compression="zstd")
        
        logger.info("done")
    

def _scan_tse_bulletins_dynamic(directory: Path) -> pl.LazyFrame:
    files = list(EVM_RAW_PARQUETS.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"Nenhum arquivo Parquet encontrado")

    lazy_frames: list[pl.LazyFrame] = []
    
    for f in files:
        lf = pl.scan_parquet(f)
        current_columns = lf.collect_schema().names()
        
        if "CD_TIPO_ELEICAO" in current_columns:
            lf = lf.with_columns(pl.col("CD_TIPO_ELEICAO").cast(pl.String).alias("tipo_eleicao_normalizado"))
        else:
            lf = lf.with_columns(pl.lit(None).alias("tipo_eleicao_normalizado"))

        if "CD_ELEICAO" not in current_columns:
            lf = lf.with_columns(pl.lit("0").alias("CD_ELEICAO"))
        else:
            lf = lf.with_columns(pl.col("CD_ELEICAO").cast(pl.String))

        if "NR_TURNO" not in current_columns:
            lf = lf.with_columns(pl.lit("1").alias("NR_TURNO"))
        else:
            lf = lf.with_columns(pl.col("NR_TURNO").cast(pl.String))

        # Only the serial number reaches the global filesystem index. Reduce
        # repetitions per source before paying for cross-batch index lookups.
        lazy_frames.append(lf.select("NR_URNA_EFETIVADA"))
    schema = pl.concat(lazy_frames, how="diagonal_relaxed").collect_schema()
    parts = []

    for index, frame in enumerate(lazy_frames):
        part = directory / f"urns-{index:05d}.parquet"
        frame.cast(schema).unique().sink_parquet(part, compression="zstd", row_group_size=16_384)
        parts.append(part)

    return pl.scan_parquet(parts)

script_instance = EvmDataScript()
