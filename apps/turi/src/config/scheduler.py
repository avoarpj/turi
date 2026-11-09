import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.schedulers.background import BackgroundScheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Podemos usar um BackgroundScheduler para rodar em paralelo ou BlockingScheduler se rodar como processo principal
scheduler = BlockingScheduler()

def add_cron_job(func, cron_expr: str, job_id: str, kwargs: dict | None = None):
    """
    Adiciona um job baseado numa expressão cron tradicional (ex: '0 0 * * *' para meia-noite todos os dias)
    APScheduler nativamente usa argumentos ano, mes, dia... mas o CronTrigger suporta 'from_crontab'.
    """
    from apscheduler.triggers.cron import CronTrigger
    
    trigger = CronTrigger.from_crontab(cron_expr)
    scheduler.add_job(
        func,
        trigger=trigger,
        kwargs=kwargs or {},
        id=job_id,
        replace_existing=True,
        max_instances=1
    )
    logger.info(f"Job {job_id} registrado com schedule '{cron_expr}'")

def start_scheduler():
    logger.info("Iniciando APScheduler...")
    scheduler.start()
