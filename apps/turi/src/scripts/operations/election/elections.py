from logging import Logger
from pathlib import Path
from tempfile import TemporaryDirectory

import polars as pl
from config.projectsettings.settings import (
    BASE_DIR,
    DUMPS_OUTPUT_DIR,
)
from config.projectsettings.scripts import (
    ELECTIONS_OUTPUT_PARQUETS,
    ELECTIONS_ROUNDS_OUTPUT_PARQUETS,
    TSE_MUNICIPALITIES_RAW_PARQUETS,
    CD_LEGISLATURES_OUTPUT_PARQUETS,
)
from scripts.bricks.pleito_identity import build_pleitos
from scripts.bricks.election_type import tse_bulletin_election_type_expr
from scripts.bricks.election_role import tse_bulletin_election_role_expr
from scripts.bricks.candidature_identity import with_electoral_locality, election_id_expr, election_round_id_expr
from infra.datascript.DataScript import DataScript
from scripts.bricks.parquet_order import FINAL_PARQUET_SORT_KEYS
from scripts.bricks.tse_bulletin_schema import normalize_tse_bulletin


ELECTIONS_RAW_PARQUETS = BASE_DIR / "downloads" / "tse" / "evm_bulletin"
PLEITOS_OUTPUT_PARQUETS = (
    DUMPS_OUTPUT_DIR
    / "opendata"
    / "opendata_pleito"
    / "opendata_pleito.parquet"
)

class ElectionsDataScript(DataScript):
    script_id = "elections"
    lifetime = "0 6 15 * *"

    source = "Tribunal Superior Eleitoral; Câmara dos Deputados"
    source_url = "https://dadosabertos.tse.jus.br/"
    description = (
        "Pleitos, eleições por cargo e localidade e seus turnos."
    )

    input_paths = [
        ELECTIONS_RAW_PARQUETS,
        TSE_MUNICIPALITIES_RAW_PARQUETS,
        CD_LEGISLATURES_OUTPUT_PARQUETS,
    ]
    output_paths = [
        ELECTIONS_OUTPUT_PARQUETS,
        ELECTIONS_ROUNDS_OUTPUT_PARQUETS,
        PLEITOS_OUTPUT_PARQUETS,
    ]

    dependencies = [
        "camaradosdeputados_legislatures",
    ]
    tags = []

    def process_data(self, logger: Logger):
        ELECTIONS_OUTPUT_PARQUETS.parent.mkdir(parents=True, exist_ok=True)

        with TemporaryDirectory(prefix="election-metadata-", dir=ELECTIONS_OUTPUT_PARQUETS.parent) as directory:
            bu_raw = _scan_tse_bulletins_dynamic(logger, Path(directory))
            self._process_data(bu_raw, logger)

    def _process_data(self, bu_raw: pl.LazyFrame, logger: Logger):
        bu_raw = bu_raw.filter(~pl.col("tipo_eleicao_normalizado").is_in(["2"]))
        tse_municipalities = pl.scan_parquet(TSE_MUNICIPALITIES_RAW_PARQUETS / "*.parquet")
        cd_legislatures = (
                    pl.scan_parquet(CD_LEGISLATURES_OUTPUT_PARQUETS)
                    .rename({"id": "legislatura_id"})
                )

        bu_raw = with_electoral_locality(
            bu_raw, tse_municipalities, "CD_CARGO_PERGUNTA", "CD_MUNICIPIO"
        )

        bu_with_place = bu_raw.with_columns([
            pl.when(
                pl.col("CD_CARGO_PERGUNTA") == "6"
            )
            .then(pl.lit("cd", dtype=pl.String))
            .otherwise(pl.lit(None, dtype=pl.Null))
            .alias("orgao_id"),

            pl.col("ANO_ELEICAO").cast(pl.String).str.to_date("%Y").alias("ano_eleicao"),
            pl.col("CD_ELEICAO").alias("codigo_tse").cast(pl.Int32)
        ]).filter(pl.col("codigo_local").is_not_null())

        bu_with_place = bu_with_place.join(
            other=cd_legislatures,
            left_on=["orgao_id", pl.col("ano_eleicao").dt.year() + 1],
            right_on=["orgao_id", pl.col("data_inicio").dt.year()],
            how="left",
            suffix="_legislature"
        )

        # Materialize distinct metadata once, rather than rescanning all vote rows
        # for each output and identity validation.
        bu_with_place = (
            bu_with_place
            .select(
                "ano_eleicao", "codigo_local", "CD_ELEICAO", "codigo_tse",
                "orgao_id", "legislatura_id", "tipo_eleicao_normalizado",
                "CD_CARGO_PERGUNTA", "DT_PLEITO", "NR_TURNO",
            )
            .unique()
            .collect(engine="streaming")
            .lazy()
        )

        pleitos_lazy, pleito_lookup = build_pleitos(bu_with_place)
        bu_with_place = bu_with_place.join(
            pleito_lookup,
            on=[
                "ano_eleicao", "codigo_local", "tipo_eleicao_normalizado",
                "DT_PLEITO", "NR_TURNO",
            ],
            how="left",
            validate="m:1",
        )

        elections_lazy = (
            bu_with_place
            .select([
                "ano_eleicao",
                "pleito_id",
                "codigo_local",
                "CD_ELEICAO",
                "codigo_tse",
                "orgao_id",
                "legislatura_id",
                "tipo_eleicao_normalizado",
                "CD_CARGO_PERGUNTA"
            ])
            .unique()
            .with_columns([
                election_id_expr().alias("id"),
                tse_bulletin_election_type_expr("tipo_eleicao_normalizado").alias("tipo"),
                tse_bulletin_election_role_expr("CD_CARGO_PERGUNTA").alias("cargo"),
                pl.col("ano_eleicao").dt.year().alias("ano")
            ])
            .select(["id", "pleito_id", "ano", "codigo_local", "orgao_id", "legislatura_id", "tipo", "cargo"])
            .unique(subset="id")
        )

        elections_lazy = elections_lazy.sort(
            by=[
                "ano",
                "codigo_local",
                "tipo",
                "cargo",
                "orgao_id"
            ]
        )

        rounds_lazy = (
            bu_with_place
            .select([
                "ano_eleicao",
                "codigo_local",
                "DT_PLEITO",
                "tipo_eleicao_normalizado",
                "CD_ELEICAO",
                "NR_TURNO",
                "codigo_tse"
            ])
            .unique()
            .with_columns([
                pl.coalesce([
                    pl.col("DT_PLEITO").str.to_date("%Y-%m-%d %H:%M:%S", strict=False),
                    pl.col("DT_PLEITO").str.to_date("%d/%m/%Y", strict=False),
                    pl.col("DT_PLEITO").str.to_date("%Y-%m-%d", strict=False)
                ]).alias("data_turno"),
                election_id_expr().alias("eleicao_id"),
                pl.col("NR_TURNO").cast(pl.Int32).alias("numero_turno")
            ])
            .with_columns([
                election_round_id_expr().alias("id")
            ])
            .select(["id", "eleicao_id", "numero_turno", "data_turno", "codigo_tse"])
        )

        # An existing election ID must never silently point to two events.
        ambiguous = (
            bu_with_place
            .with_columns(election_id_expr().alias("id"))
            .group_by("id")
            .agg(
                pl.col("pleito_id").n_unique().alias("pleitos"),
                pl.col("pleito_id").is_null().any().alias("sem_pleito"),
            )
            .filter((pl.col("pleitos") != 1) | pl.col("sem_pleito"))
            .limit(1)
            .collect()
        )

        if ambiguous.height:
            raise ValueError("Election identity maps to multiple pleitos")

        PLEITOS_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True, parents=True)
        ELECTIONS_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True, parents=True)
        rounds_lazy = rounds_lazy.sort(
            by=FINAL_PARQUET_SORT_KEYS["opendata_election_round"]
        )

        ELECTIONS_ROUNDS_OUTPUT_PARQUETS.parent.mkdir(exist_ok=True, parents=True)

        pleitos_lazy.sink_parquet(PLEITOS_OUTPUT_PARQUETS, compression="snappy")
        elections_lazy.sink_parquet(ELECTIONS_OUTPUT_PARQUETS, compression="snappy")
        rounds_lazy.sink_parquet(ELECTIONS_ROUNDS_OUTPUT_PARQUETS, compression="snappy")

        logger.info("done")


def _scan_tse_bulletins_dynamic(logger: Logger, directory: Path) -> pl.LazyFrame:
    files = sorted(ELECTIONS_RAW_PARQUETS.glob("*.parquet"))
    if not files:
        raise FileNotFoundError("Nenhum arquivo Parquet encontrado")
    logger.info("found %d bulletin files", len(files))
    frames = [
        normalize_tse_bulletin(pl.scan_parquet(file)).select(
            "ANO_ELEICAO", "SG_UF", "CD_MUNICIPIO", "CD_CARGO_PERGUNTA",
            "CD_ELEICAO", "DT_PLEITO", "NR_TURNO", "tipo_eleicao_normalizado",
        )
        for file in files
    ]
    schema = pl.concat(frames, how="diagonal_relaxed").collect_schema()
    parts = []

    for index, frame in enumerate(frames):
        part = directory / f"metadata-{index:05d}.parquet"
        frame.cast(schema).unique().sink_parquet(part, compression="zstd", row_group_size=16_384)
        parts.append(part)

    return pl.scan_parquet(parts)


script_instance = ElectionsDataScript()
