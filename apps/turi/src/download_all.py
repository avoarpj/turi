import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    logger.info("Starting download process")

    try:
        from pipelines.registry import downloaders_registry

        for downloader in downloaders_registry:
            print(f"Download #{downloader.id}\nLogs:")
            downloader.func(**downloader.kwargs or {})
            print("End.")
    except (KeyboardInterrupt, SystemExit):
        logger.info("Interrupt signal received, exiting...")
        exit()

if __name__ == "__main__":
    main()
