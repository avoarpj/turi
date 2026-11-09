from abc import ABC, abstractmethod
from datetime import UTC, datetime
from logging import Logger
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel

from config.projectsettings.settings import SCRIPTS_OPERATIONS_METADATA_DIR
from infra.datascript.metadata import write_metadata


VENATO_INCLUDED = "VENATO_INCLUDED"


class Metadata(BaseModel):
    """Execution checkpoint, compatible with the existing JSON history."""

    filepath: Path
    last_successful_execution: datetime | None = None

    @classmethod
    def load(cls, filepath: Path):
        if filepath.exists():
            metadata = cls.model_validate_json(filepath.read_text("utf-8"))
            metadata.filepath = filepath
            return metadata

        return cls(filepath=filepath)

    def refresh_metadata(self, executed_at: datetime):
        updated = self.model_copy(update={"last_successful_execution": executed_at})
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.filepath.with_name(f".{self.filepath.name}.{uuid4().hex}.tmp")

        try:
            temporary.write_text(updated.model_dump_json(indent=4), encoding="utf-8")
            temporary.replace(self.filepath)
        finally:
            temporary.unlink(missing_ok=True)

        self.last_successful_execution = executed_at


class DataScript(ABC):
    script_id: str
    lifetime: str

    source: str
    source_url: str
    description: str

    input_paths: list[Path] = []
    output_paths: list[Path]
    dependencies: list[str] = []
    tags: list[str] = []

    def __init__(self) -> None:
        self.input_paths = list(self.input_paths)
        self.output_paths = list(self.output_paths)
        self.dependencies = list(self.dependencies)
        self.tags = list(self.tags)

        if not self.output_paths:
            raise ValueError(f"Script {self.script_id} must declare its output_paths")

        self._cron_instance = CronTrigger.from_crontab(self.lifetime)
        self._metadata = Metadata.load(
            filepath=SCRIPTS_OPERATIONS_METADATA_DIR / f"{self.script_id}.json"
        )

    @property
    def last_successful_execution(self) -> datetime | None:
        return self._metadata.last_successful_execution

    @abstractmethod
    def process_data(self, logger: Logger):
        pass

    def run(self, logger: Logger) -> bool:
        if not self.should_run(datetime.now(UTC)):
            logger.info("Script %s: lifetime not reached", self.script_id)
            return False

        started = perf_counter()
        logger.info("Starting script %s", self.script_id)

        for path in self.output_paths:
            path.parent.mkdir(parents=True, exist_ok=True)

        self.process_data(logger)

        executed_at = datetime.now(UTC)
        write_metadata(self, executed_at)
        self._metadata.refresh_metadata(executed_at)

        logger.info("Finished script %s in %.3f seconds", self.script_id, perf_counter() - started)
        return True

    def should_run(self, basedate: datetime) -> bool:
        if self.last_successful_execution is None:
            return True

        next_run = self._cron_instance.get_next_fire_time(
            self.last_successful_execution,
            basedate,
        )

        return next_run is not None and basedate >= next_run
