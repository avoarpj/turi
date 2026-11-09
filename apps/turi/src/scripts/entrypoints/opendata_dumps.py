import logging
from collections.abc import Iterable

from config.projectsettings.settings import DUMPS_OUTPUT_DIR
from infra.datascript.DataScript import DataScript, VENATO_INCLUDED
from infra.datascript.discovery import discover_scripts, resolve_scripts
from scripts.maintenance.bloom_final_parquets import rewrite_final_parquets


logger = logging.getLogger(__name__)


class OpendataDumpsEntrypoint:
    def run(
        self,
        script_ids: Iterable[str] | None = None,
        *,
        no_update_venato: bool = False,
    ) -> list[DataScript]:
        scripts = discover_scripts()
        execution_plan = resolve_scripts(scripts, script_ids)
        logger.info("Script execution order: %s", [script.script_id for script in execution_plan])

        executed = []

        for script in execution_plan:
            if script.run(logger):
                executed.append(script)

        if not executed:
            return executed

        outputs = [path for script in executed for path in script.output_paths]

        logger.info("Adding Bloom filters to generated Parquets")
        rewrite_final_parquets(DUMPS_OUTPUT_DIR / "opendata", paths=outputs)

        update_venato = any(VENATO_INCLUDED in script.tags for script in executed)

        if update_venato and not no_update_venato:
            self.update_venato()

        return executed

    def update_venato(self) -> None:
        from avoar.infra.venato.core import Venato, VenatoConfig
        from avoar.projectsettings.globals import VENATO_DATA_DIR

        logger.info("Creating tantivy indexes")
        venato = Venato(config=VenatoConfig(data_dir=VENATO_DATA_DIR))

        venato.prune_all()
        venato.ingest_all()
