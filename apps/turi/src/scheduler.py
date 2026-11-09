import logging
from config.scheduler import start_scheduler
from pipelines.registry import register_all_pipelines

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    logger.info("Inicializando o Turi Refatorado...")
    
    # Registra todos os pipelines no APScheduler
    register_all_pipelines()
    
    # Inicia o Loop do Agendador
    try:
        start_scheduler()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Encerrando execução.")


if __name__ == "__main__":
    main()
