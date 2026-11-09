"""Run the actual item producer under supervision, with temporary output and raw vote audits."""
import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from infra.resource_guard import run_guarded


def _worker(request: Path) -> dict:
    import polars as pl
    from polars.testing import assert_frame_equal
    import pyarrow.parquet as pq

    from scripts.bricks.candidature_identity import with_electoral_locality
    from scripts.bricks.evm_bulletin_vote_type_expr import tse_evm_bulletin_vote_type_expr
    from scripts.bricks.tse_bulletin_schema import normalize_tse_bulletin
    from scripts.maintenance.sort_final_parquets import is_sorted
    from scripts.operations.evm import evm_bulletin_item as producer

    sources = json.loads(request.read_text())["sources"]
    work = request.parent
    raw_directory = work / "raw"
    raw_directory.mkdir()
    for index, source in enumerate(sources):
        (raw_directory / f"{index:04d}.parquet").symlink_to(source)

    output = work / "output.parquet"
    producer.EVM_BULLETIN_ITEMS_RAW_PARQUETS = raw_directory
    producer.EVM_BULLETIN_ITEMS_OUTPUT_PARQUETS = output
    os.environ["TURI_UNIQUE_TEMP_DIRECTORY"] = str(work)
    producer.EvmBulletinItemDataScript().process_data(logging.getLogger(__name__))

    municipalities = pl.scan_parquet(producer.TSE_MUNICIPALITIES_RAW_PARQUETS / "*.parquet")
    grouping = ["codigo_local", "codigo_cargo_tse", "tipo"]
    aggregates = []
    raw_partitions = []

    for source in sources:
        raw = normalize_tse_bulletin(pl.scan_parquet(source)).filter(
            ~pl.col("tipo_eleicao_normalizado").is_in(["2"])
        )
        partitions = raw.group_by(
            "ANO_ELEICAO", "SG_UF", "tipo_eleicao_normalizado", "NR_TURNO",
        ).agg(
            pl.len().alias("rows"),
            pl.col("QT_VOTOS").cast(pl.Int64).sum().alias("votes"),
        ).collect(engine="streaming")
        raw_partitions.append({"source": source, "partitions": partitions.to_dicts()})

        facts = raw.select(
            "SG_UF", "CD_MUNICIPIO", "CD_CARGO_PERGUNTA",
            pl.col("NR_VOTAVEL").cast(pl.String),
            pl.col("CD_TIPO_VOTAVEL").cast(pl.String),
            pl.col("QT_VOTOS").cast(pl.Int64).alias("quantidade"),
        )
        expected = with_electoral_locality(
            facts, municipalities, "CD_CARGO_PERGUNTA", "CD_MUNICIPIO",
        ).with_columns(
            pl.col("CD_CARGO_PERGUNTA").cast(pl.Int32).alias("codigo_cargo_tse"),
            tse_evm_bulletin_vote_type_expr("NR_VOTAVEL", "CD_TIPO_VOTAVEL").alias("tipo"),
        ).group_by(grouping).agg(
            pl.len().cast(pl.UInt64).alias("rows"),
            pl.col("quantidade").sum().alias("votes"),
        ).collect(engine="streaming")
        aggregates.append(expected)

    expected = pl.concat(aggregates).group_by(grouping).agg(
        pl.col("rows").sum(), pl.col("votes").sum(),
    ).sort(grouping)
    actual = pl.scan_parquet(output).group_by(grouping).agg(
        pl.len().cast(pl.UInt64).alias("rows"),
        pl.col("quantidade").cast(pl.Int64).sum().alias("votes"),
    ).sort(grouping).collect(engine="streaming")
    assert_frame_equal(actual, expected)

    if not is_sorted(output, tuple(producer.SORT_KEYS)):
        raise AssertionError("Output is not globally sorted")

    with pq.ParquetFile(output) as parquet:
        return {
            "files": len(sources),
            "output_rows": parquet.metadata.num_rows,
            "output_votes": int(actual["votes"].sum()),
            "groups_checked": actual.height,
            "output_bytes": output.stat().st_size,
            "raw_partitions": raw_partitions,
            "checks": [
                "rows and votes per input file before sorting",
                "rows and votes after sorting before publication",
                "raw vs final counts and vote sums by locality, office and vote type",
                "global sort order, including batch boundaries",
            ],
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--raw", type=Path, action="append", default=[])
    parser.add_argument("--memory-mib", type=int, default=4096)
    parser.add_argument("--swap-mib", type=int, default=512)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--report", type=Path, default=Path("docs/audits/bulletin_items_validation.json"))
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    if args.worker is not None:
        result = _worker(args.worker)
        args.worker.with_name("response.json").write_text(json.dumps(result, indent=2) + "\n")
        return

    from scripts.operations.evm.evm_bulletin_item import EVM_BULLETIN_ITEMS_RAW_PARQUETS

    sources = sorted(EVM_BULLETIN_ITEMS_RAW_PARQUETS.glob("*.parquet")) if args.all else args.raw
    if not sources:
        parser.error("Select --all or at least one --raw source")

    root = Path(os.getenv("TURI_UNIQUE_TEMP_DIRECTORY", ".turi_unique_tmp")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "status": "running"}
    args.report.write_text(json.dumps(report, indent=2) + "\n")

    try:
        with TemporaryDirectory(prefix="validate-items-", dir=root) as directory:
            request = Path(directory) / "request.json"
            request.write_text(json.dumps({"sources": [str(source.resolve()) for source in sources]}))
            environment = dict(os.environ)
            environment.setdefault("POLARS_MAX_THREADS", "2")
            usage = run_guarded(
                [sys.executable, "-m", "scripts.maintenance.validate_bulletin_items", "--worker", str(request)],
                max_memory=args.memory_mib * 1024**2,
                max_swap=args.swap_mib * 1024**2,
                timeout=args.timeout,
                env=environment,
                work_directory=root,
            )
            report.update(json.loads(request.with_name("response.json").read_text()))
            report.update(
                status="passed",
                peak_rss_mib=round(usage.peak_rss / 1024**2, 1),
                peak_swap_mib=round(usage.peak_swap / 1024**2, 1),
                seconds=round(usage.seconds, 3),
            )
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        args.report.write_text(json.dumps(report, indent=2) + "\n")

    print(json.dumps({key: value for key, value in report.items() if key != "raw_partitions"}), flush=True)


if __name__ == "__main__":
    main()
