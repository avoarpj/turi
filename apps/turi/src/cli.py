"""Installed entrypoints retain the existing producer import structure."""
import argparse
import sys
from pathlib import Path


def _prepare_imports() -> None:
    source = str(Path(__file__).resolve().parent)
    if source not in sys.path:
        sys.path.insert(0, source)


def dumps() -> None:
    _prepare_imports()

    from apps.turi.src.run_all_scripts import main

    main()


def downloads() -> None:
    argparse.ArgumentParser(description="Run enabled Turi downloaders.").parse_args()
    _prepare_imports()

    from apps.turi.src.download_all import main

    main()


def schedule() -> None:
    argparse.ArgumentParser(description="Start the Turi pipeline scheduler.").parse_args()
    _prepare_imports()

    from apps.turi.src.scheduler import main

    main()


def indexes() -> None:
    argparse.ArgumentParser(
        description="Rebuild Venato indexes from the existing Parquet dumps.",
    ).parse_args()
    _prepare_imports()

    from scripts.entrypoints.opendata_dumps import OpendataDumpsEntrypoint

    OpendataDumpsEntrypoint().update_venato()
