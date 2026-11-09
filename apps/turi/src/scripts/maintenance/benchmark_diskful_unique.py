"""Progressive, isolated measurements; never publish or replace production dumps."""
import argparse
from datetime import datetime, timezone
import json
from logging import getLogger
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter, sleep

from datafusion import RuntimeEnvBuilder, SessionConfig, SessionContext
import polars as pl
import psutil
import pyarrow.parquet as pq

from infra.diskful_unique import diskful_unique, diskful_unique_session


def _run_producer(case: dict, actual: Path, work: Path) -> None:
    from scripts.operations.evm import evm, evm_bulletin

    raw = work / "raw"
    raw.mkdir()
    (raw / "source.parquet").symlink_to(case["source"])

    if case["kind"] == "evm":
        evm.EVM_RAW_PARQUETS = raw
        evm.EVM_OUTPUT_PARQUETS = actual
        evm.EvmDataScript().process_data(getLogger(__name__))
    else:
        evm_bulletin.EVM_BULLETINS_RAW_PARQUETS = raw
        evm_bulletin.EVM_BULLETINS_OUTPUT_PARQUETS = actual
        evm_bulletin.EvmBulletinDataScript().process_data(getLogger(__name__))


def _producer_reference(kind: str, path: Path, columns: list[str]) -> None:
    from config.projectsettings.settings import NUMERIC_HASH_SEED

    frame = pl.scan_parquet(path)

    if kind == "evm":
        frame = frame.select(
            pl.col("NR_URNA_EFETIVADA").hash(seed=NUMERIC_HASH_SEED).alias("id"),
            pl.col("NR_URNA_EFETIVADA").alias("numero_serie_urna"),
        )
    else:
        localities = frame.group_by("id").agg(
            pl.when(pl.col("codigo_municipio_ibge").drop_nulls().n_unique() == 1)
            .then(pl.col("codigo_municipio_ibge").drop_nulls().first())
            .otherwise(pl.lit(None, dtype=pl.String))
            .alias("codigo_municipio_ibge")
        )
        # The reference has already been reduced by independent DataFusion
        # DISTINCT. Apply the original consolidation to this small result.
        frame = frame.drop("codigo_municipio_ibge").unique(subset="id", keep="first")
        frame = frame.join(localities, on="id", how="left")

    staging = path.with_suffix(".staging")
    frame.select(columns).sink_parquet(staging, compression="zstd", engine="streaming")
    os.replace(staging, path)


def _write_reference(source: Path, destination: Path) -> SessionContext:
    spill = destination.parent / "reference_spill"
    spill.mkdir()
    runtime = (
        RuntimeEnvBuilder()
        .with_fair_spill_pool(128 * 1024**2)
        .with_disk_manager_specified(str(spill))
    )
    context = SessionContext(SessionConfig().with_target_partitions(1), runtime)
    context.register_parquet("source", str(source))
    reference = context.sql("SELECT DISTINCT * FROM source")

    with pq.ParquetWriter(destination, reference.schema(), compression="zstd") as writer:
        for batch in reference.execute_stream():
            writer.write_batch(batch.to_pyarrow())

    return context


def _worker(case: dict, work: Path) -> dict:
    with diskful_unique_session(work):
        phase = work / "phase.txt"
        phase.write_text("preparing_input")
        if case["kind"] == "synthetic":
            rows = case["rows"]
            cardinality = min(rows // 2, 100_000)
            frame = pl.LazyFrame().select(pl.int_range(0, rows).alias("row"))
            frame = frame.select((pl.col("row") % cardinality).cast(pl.UInt64).alias("id"))
            frame = frame.with_columns(
                pl.concat_str(pl.lit("key-"), pl.col("id")).alias("value")
            )
        else:
            from config.projectsettings.scripts import TSE_MUNICIPALITIES_RAW_PARQUETS
            from scripts.bricks.tse_bulletin_schema import normalize_tse_bulletin
            from scripts.operations.evm.evm_bulletin import _process_data

            raw = pl.scan_parquet(case["source"])
            frame = raw.select("NR_URNA_EFETIVADA")

            if case["kind"] == "bulletins":
                municipalities = pl.scan_parquet(TSE_MUNICIPALITIES_RAW_PARQUETS / "*.parquet")
                frame = _process_data(normalize_tse_bulletin(raw), municipalities)

        # Snapshot the transformed input for an independent reference. Both
        # engines read the same values, and production files remain read-only.
        source = work / "input.parquet"
        actual = work / "actual.parquet"
        reference = work / "reference.parquet"
        frame.sink_parquet(
            source,
            compression="zstd",
            row_group_size=16_384,
            engine="streaming",
        )
        input_rows = pq.ParquetFile(source).metadata.num_rows
        started = perf_counter()
        phase.write_text("diskful_unique")

        if case.get("producer", False):
            _run_producer(case, actual, work)
        else:
            result = diskful_unique(pl.scan_parquet(source))
            result.sink_parquet(actual, compression="zstd", engine="streaming")

        seconds = perf_counter() - started
        peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        output_rows = pq.ParquetFile(actual).metadata.num_rows
        phase.write_text("independent_reference_and_audit")
        context = _write_reference(source, reference)

        if case.get("producer", False):
            _producer_reference(case["kind"], reference, pq.read_schema(actual).names)

        context.register_parquet("actual", str(actual))
        context.register_parquet("reference", str(reference))

        for left, right in (("actual", "reference"), ("reference", "actual")):
            query = f"SELECT * FROM {left} EXCEPT ALL SELECT * FROM {right}"
            for batch in context.sql(query).execute_stream():
                if batch.to_pyarrow().num_rows:
                    raise AssertionError(f"Content differs: {left} EXCEPT ALL {right}")

        return {
            **case,
            "input_rows": input_rows,
            "output_rows": output_rows,
            "dedup_seconds": round(seconds, 3),
            "pipeline_peak_rss_mib": round(peak_rss / 1024**2, 1),
            "audit": "bidirectional EXCEPT ALL against independent DataFusion DISTINCT",
        }


def _run_case(case: dict, root: Path, max_rss_mib: int, timeout: int) -> dict:
    with TemporaryDirectory(prefix="benchmark-", dir=root) as directory:
        work = Path(directory)
        request = work / "request.json"
        response = work / "response.json"
        errors = work / "stderr.log"
        request.write_text(json.dumps(case))
        command = [
            sys.executable, "-m", "scripts.maintenance.benchmark_diskful_unique",
            "--worker", str(request), "--response", str(response),
        ]
        started = perf_counter()
        peak = 0

        with errors.open("w") as stderr:
            process = subprocess.Popen(command, stderr=stderr, start_new_session=True)

            try:
                while process.poll() is None:
                    try:
                        usage = psutil.Process(process.pid).memory_info().rss
                        peak = max(peak, usage)
                    except psutil.NoSuchProcess:
                        pass

                    if peak > max_rss_mib * 1024**2:
                        phase = work / "phase.txt"
                        current = phase.read_text() if phase.exists() else "startup"
                        raise RuntimeError(
                            f"Worker exceeded {max_rss_mib} MiB RSS during {current} "
                            f"(observed {peak / 1024**2:.1f} MiB)"
                        )
                    if perf_counter() - started > timeout:
                        raise TimeoutError(f"Worker exceeded {timeout} seconds")
                    if psutil.disk_usage(root).free < 4 * 1024**3:
                        raise RuntimeError("Less than 4 GiB free disk space remains")

                    sleep(0.1)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()

        if process.returncode:
            raise RuntimeError(errors.read_text()[-8000:])

        return {
            **json.loads(response.read_text()),
            "worker_peak_rss_mib": round(peak / 1024**2, 1),
            "total_seconds": round(perf_counter() - started, 3),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", nargs="+", type=int, default=[10_000, 100_000, 1_000_000])
    parser.add_argument("--skip-synthetic", action="store_true")
    parser.add_argument("--producer-scripts", action="store_true")
    parser.add_argument("--raw", action="append", type=Path, default=[])
    parser.add_argument("--max-rss-mib", type=int, default=1536)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--report", type=Path, default=Path("docs/audits/diskful_unique.json"))
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--response", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.worker is not None:
        result = _worker(json.loads(args.worker.read_text()), args.worker.parent)
        args.response.write_text(json.dumps(result, indent=2) + "\n")
        return

    if any(rows < 2 for rows in args.rows):
        parser.error("--rows must be at least 2")
    if args.max_rss_mib <= 0 or args.timeout <= 0:
        parser.error("RSS and timeout limits must be positive")

    root = Path(os.getenv("TURI_UNIQUE_TEMP_DIRECTORY", ".turi_unique_tmp")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    cases = (
        [] if args.skip_synthetic
        else [{"kind": "synthetic", "rows": rows} for rows in sorted(args.rows)]
    )

    for path in sorted(args.raw, key=lambda item: pq.ParquetFile(item).metadata.num_rows):
        cases.extend(
            {"kind": kind, "source": str(path.resolve()), "producer": args.producer_scripts}
            for kind in ("evm", "bulletins")
        )

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "polars": pl.__version__,
        "limits": {"worker_rss_mib": args.max_rss_mib, "timeout_seconds": args.timeout},
        "cases": [],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)

    for case in cases:
        print("Starting:", json.dumps(case), flush=True)
        try:
            record = _run_case(case, root, args.max_rss_mib, args.timeout)
        except Exception as error:
            report["cases"].append({**case, "error": str(error)})
            args.report.write_text(json.dumps(report, indent=2) + "\n")
            raise

        report["cases"].append(record)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
