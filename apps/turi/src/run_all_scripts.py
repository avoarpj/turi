import argparse
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        description="Run discovered Turi scripts and their prerequisites, respecting lifetimes.",
    )
    parser.add_argument(
        "script_ids",
        nargs="*",
        help="Script IDs to run; omit to run all discovered scripts.",
    )
    parser.add_argument(
        "--no-update-venato",
        action="store_true",
        help="Skip Venato index updates even when indexed datasets are generated.",
    )
    args = parser.parse_args(argv)

    from scripts.entrypoints.opendata_dumps import OpendataDumpsEntrypoint

    logger.info("Running scripts: %s", args.script_ids or "all")

    try:
        OpendataDumpsEntrypoint().run(
            script_ids=args.script_ids or None,
            no_update_venato=args.no_update_venato,
        )
    except (KeyboardInterrupt, SystemExit):
        logger.info("Interrupt signal received, exiting...")
        raise


if __name__ == "__main__":
    main()
