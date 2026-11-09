import logging
from dataclasses import dataclass
from typing import Callable, Any
from datetime import timedelta

from scripts.entrypoints.opendata_dumps import OpendataDumpsEntrypoint
from scripts.entrypoints.opendata_downloads import OpendataDownloadsEntrypoint
from config.scheduler import add_cron_job

logger = logging.getLogger(__name__)

def generic_runner(task_name: str, task_func: Callable[..., Any], func_kwargs: dict | None = None):
    """Executável genérico para capturar erros sem derrubar o scheduler."""
    kwargs_to_pass = func_kwargs or {}
    
    def run():
        try:
            task_func(**kwargs_to_pass)
        except Exception as e:
            logger.error(f"[{task_name}] Falha na execução: {e}")

    return run

@dataclass
class ScheduledTask:
    id: str
    cron_expr: str
    func: Callable[..., Any]
    kwargs: dict | None = None

downloaders_registry = [
    ScheduledTask(
        id="download_alldata",
        cron_expr="0 2 * * *",
        func=OpendataDownloadsEntrypoint().run
    )
]

scripts_registry = [
    ScheduledTask(
        id="script_generate_opendata_dumps",
        cron_expr="*/15 * * * *",
        func=OpendataDumpsEntrypoint().run
    )
]

def register_all_pipelines():
    """Registra todos os downloaders e scripts na fila do APScheduler de forma independente."""
    all_tasks = downloaders_registry + scripts_registry
    
    for task in all_tasks:
        add_cron_job(
            func=generic_runner(task.id, task.func, task.kwargs),
            cron_expr=task.cron_expr,
            job_id=task.id,
            kwargs={
                "task_name": task.id,
                "task_func": task.func,
                "func_kwargs": task.kwargs
            }
        )
