from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from importlib import import_module
import json
from logging import getLogger
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import polars as pl

from infra.datascript.DataScript import VENATO_INCLUDED, DataScript
from infra.datascript.discovery import discover_scripts, resolve_scripts
from infra.datascript.metadata import write_metadata
from scripts.entrypoints import opendata_dumps


logger = getLogger(__name__)
datascript_module = import_module("infra.datascript.DataScript")


class DataScriptTests(TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(TemporaryDirectory()))
        self.stack.enter_context(patch.object(
            datascript_module, "SCRIPTS_OPERATIONS_METADATA_DIR", self.root / "history",
        ))
        self.calls = []

    def script(self, script_id, *, dependencies=(), tags=(), outputs=None, fail=False):
        calls = self.calls

        def process_data(script, logger):
            calls.append(script.script_id)
            if fail:
                raise RuntimeError("processing failed")

            for path in script.output_paths:
                pl.DataFrame({"id": [1, 2]}).write_parquet(path)

        cls = type(f"Script_{script_id}", (DataScript,), {
            "script_id": script_id,
            "lifetime": "0 0 * * *",
            "source": "Fonte pública",
            "source_url": "https://example.com/dataset",
            "description": "Descrição com acentos",
            "input_paths": [self.root / "raw" / "*.parquet"],
            "output_paths": outputs or [self.root / "opendata" / script_id / "data.parquet"],
            "dependencies": list(dependencies),
            "tags": list(tags),
            "process_data": process_data,
        })

        return cls()

    def test_run_publishes_avro_and_checkpoint_then_skips_within_lifetime(self):
        script = self.script("test", tags=[VENATO_INCLUDED])

        self.assertTrue(script.run(logger))
        record = pl.read_avro(script.output_paths[0].parent / "metadata.avro").to_dicts()[0]

        self.assertEqual(record["script_id"], script.script_id)
        self.assertEqual(record["source"], script.source)
        self.assertEqual(record["source_url"], script.source_url)
        self.assertEqual(record["description"], script.description)
        self.assertEqual(record["lifetime"], script.lifetime)
        self.assertEqual(record["input_paths"], [str(path) for path in script.input_paths])
        self.assertEqual(record["output_paths"], [str(path) for path in script.output_paths])
        self.assertEqual(record["dependencies"], [])
        self.assertEqual(record["tags"], [VENATO_INCLUDED])
        self.assertEqual(record["last_successful_execution"], script.last_successful_execution.isoformat())

        reloaded = type(script)()
        self.assertEqual(reloaded.last_successful_execution, script.last_successful_execution)
        self.assertFalse(reloaded.run(logger))
        self.assertEqual(self.calls, ["test"])

    def test_existing_json_history_preserves_lifetime_and_cron_boundaries(self):
        script = self.script("existing")
        cron_timezone = script._cron_instance.timezone
        last_execution = datetime(2026, 11, 6, 23, 59, tzinfo=cron_timezone)
        history = self.root / "history" / "existing.json"
        history.parent.mkdir()
        history.write_text(json.dumps({
            "filepath": "/old/location/existing.json",
            "last_successful_execution": last_execution.astimezone(UTC).isoformat(),
        }))
        script = type(script)()
        boundary = datetime(2026, 11, 7, tzinfo=cron_timezone).astimezone(UTC)

        self.assertEqual(script._metadata.filepath, history)
        self.assertFalse(script.should_run(boundary - timedelta(seconds=1)))
        self.assertTrue(script.should_run(boundary))

    def test_shared_output_directories_keep_each_producer_and_replace_its_row(self):
        shared = self.root / "shared"
        other = self.root / "other"
        first = self.script("first", outputs=[shared / "a.parquet", other / "a.parquet"])
        second = self.script("second", outputs=[shared / "b.parquet"])
        timestamp = datetime(2026, 11, 7, tzinfo=UTC)

        write_metadata(first, timestamp)
        write_metadata(second, timestamp)
        first.description = "Descrição atualizada"
        write_metadata(first, timestamp + timedelta(days=1))

        records = pl.read_avro(shared / "metadata.avro").to_dicts()
        self.assertEqual([record["script_id"] for record in records], ["first", "second"])
        self.assertEqual(records[0]["description"], first.description)
        self.assertEqual(records[1]["last_successful_execution"], timestamp.isoformat())
        self.assertEqual(pl.read_avro(other / "metadata.avro").to_dicts(), [records[0]])
        self.assertFalse(list(self.root.rglob("*.tmp")))

    def test_failures_do_not_mark_execution_successful(self):
        script = self.script("failure", fail=True)

        with self.assertRaisesRegex(RuntimeError, "processing failed"):
            script.run(logger)

        self.assertIsNone(script.last_successful_execution)
        self.assertFalse(script._metadata.filepath.exists())
        self.assertFalse((script.output_paths[0].parent / "metadata.avro").exists())

        successful = self.script("metadata_failure")
        with patch.object(datascript_module, "write_metadata", side_effect=OSError("avro failed")):
            with self.assertRaisesRegex(OSError, "avro failed"):
                successful.run(logger)

        self.assertIsNone(successful.last_successful_execution)
        self.assertFalse(successful._metadata.filepath.exists())

    def test_avro_write_failure_preserves_previous_metadata(self):
        script = self.script("test")
        write_metadata(script, datetime(2026, 11, 7, tzinfo=UTC))
        target = script.output_paths[0].parent / "metadata.avro"
        original = target.read_bytes()

        with patch.object(pl.DataFrame, "write_avro", side_effect=OSError("write failed")):
            with self.assertRaisesRegex(OSError, "write failed"):
                write_metadata(script, datetime.now(UTC))

        self.assertEqual(target.read_bytes(), original)
        self.assertFalse(list(self.root.rglob("*.tmp")))

    def test_dependencies_are_ordered_deduplicated_and_do_not_select_unrelated_scripts(self):
        scripts = {script.script_id: script for script in [
            self.script("root", dependencies=["left", "right"]),
            self.script("left", dependencies=["shared"]),
            self.script("right", dependencies=["shared"]),
            self.script("shared"),
            self.script("unrelated"),
        ]}

        ordered = resolve_scripts(scripts, ["root", "left", "root"])
        self.assertEqual([script.script_id for script in ordered], ["shared", "left", "right", "root"])
        self.assertEqual(resolve_scripts(scripts, []), [])

    def test_invalid_graphs_fail_before_any_processing(self):
        scripts = {"one": self.script("one", dependencies=["missing"])}

        with self.assertRaisesRegex(ValueError, "Unknown script_id: missing.*required by one"):
            resolve_scripts(scripts)
        with self.assertRaisesRegex(ValueError, "Unknown script_id: unknown"):
            resolve_scripts(scripts, ["unknown"])

        scripts["one"].dependencies = ["two"]
        scripts["two"] = self.script("two", dependencies=["one"])
        with self.assertRaisesRegex(ValueError, "one -> two -> one"):
            resolve_scripts(scripts, ["one"])

        self.assertEqual(self.calls, [])

    def test_namespace_discovery_finds_new_scripts_without_a_manual_registry(self):
        package_name = "turi_discovery_fixture"
        package = self.root / package_name
        nested = package / "nested"
        nested.mkdir(parents=True)
        template = (
            "from pathlib import Path\n"
            "from infra.datascript.DataScript import DataScript\n"
            "class Script(DataScript):\n"
            "    script_id = 'discovered'\n"
            "    lifetime = '0 0 * * *'\n"
            "    source = 'fixture'\n"
            "    source_url = 'https://example.com'\n"
            "    description = 'fixture'\n"
            "    output_paths = [Path('unused.parquet')]\n"
            "    def process_data(self, logger):\n"
            "        raise AssertionError('discovery must not process data')\n"
            "script_instance = Script()\n"
        )
        (nested / "producer.py").write_text(template)
        (nested / "helper.py").write_text("value = 1\n")

        try:
            with patch.object(sys, "path", [str(self.root), *sys.path]):
                scripts = discover_scripts(package_name)
                self.assertEqual(list(scripts), ["discovered"])

                (nested / "duplicate.py").write_text(template)
                with self.assertRaisesRegex(ValueError, "Duplicate script_id: discovered"):
                    discover_scripts(package_name)
        finally:
            for name in list(sys.modules):
                if name == package_name or name.startswith(package_name + "."):
                    del sys.modules[name]

    def test_real_operation_catalog_has_valid_metadata_and_dependency_order(self):
        # Discovery must not initialize NLTK resources or run ETL/downloads.
        with patch("infra.nltk_setup.setup_nltk", side_effect=AssertionError("discovery downloaded data")):
            scripts = discover_scripts()

        ordered = resolve_scripts(scripts)
        positions = {script.script_id: index for index, script in enumerate(ordered)}
        for script in ordered:
            self.assertTrue(script.source)
            self.assertTrue(script.source_url.startswith(("http://", "https://")))
            self.assertTrue(script.description)
            self.assertTrue(script.output_paths)
            for dependency in script.dependencies:
                self.assertLess(positions[dependency], positions[script.script_id])

        selected = resolve_scripts(scripts, ["evm_bulletin_items"])
        self.assertEqual(
            [script.script_id for script in selected],
            ["camaradosdeputados_legislatures", "elections", "candidatures", "evm_bulletin_items"],
        )

    def test_entrypoint_runs_prerequisites_and_only_rewrites_generated_outputs(self):
        dependency = self.script("dependency", tags=[VENATO_INCLUDED])
        selected = self.script("selected", dependencies=["dependency"])
        unrelated = self.script("unrelated")
        unrelated.output_paths[0].parent.mkdir(parents=True)
        pl.DataFrame({"id": [3]}).write_parquet(unrelated.output_paths[0])
        original = unrelated.output_paths[0].read_bytes()

        entrypoint = opendata_dumps.OpendataDumpsEntrypoint()
        with (
            patch.object(opendata_dumps, "discover_scripts", return_value={
                script.script_id: script for script in [selected, dependency, unrelated]
            }),
            patch.object(opendata_dumps, "DUMPS_OUTPUT_DIR", self.root),
            patch.object(entrypoint, "update_venato") as update,
        ):
            executed = entrypoint.run(["selected"])

        self.assertEqual(self.calls, ["dependency", "selected"])
        self.assertEqual(executed, [dependency, selected])
        update.assert_called_once_with()
        self.assertEqual(unrelated.output_paths[0].read_bytes(), original)
        report = json.loads((self.root / "bloom_filters_report.json").read_text())
        self.assertEqual(
            {record["file"] for record in report["files"]},
            {str(script.output_paths[0]) for script in executed},
        )

    def test_venato_flag_tags_and_lifetime_skips(self):
        for tags, no_update, recent in [
            ([VENATO_INCLUDED], True, False),
            ([], False, False),
            ([VENATO_INCLUDED], False, True),
        ]:
            with self.subTest(tags=tags, no_update=no_update, recent=recent):
                script = self.script("indexed", tags=tags)
                if recent:
                    script._metadata.last_successful_execution = datetime.now(UTC)
                else:
                    script._metadata.last_successful_execution = None

                entrypoint = opendata_dumps.OpendataDumpsEntrypoint()
                with (
                    patch.object(opendata_dumps, "discover_scripts", return_value={"indexed": script}),
                    patch.object(opendata_dumps, "rewrite_final_parquets") as bloom,
                    patch.object(entrypoint, "update_venato") as update,
                ):
                    entrypoint.run(["indexed"], no_update_venato=no_update)

                update.assert_not_called()
                self.assertEqual(bloom.call_count, 0 if recent else 1)

    def test_skipped_dependency_does_not_skip_its_consumer_or_trigger_venato(self):
        dependency = self.script("dependency", tags=[VENATO_INCLUDED])
        dependency._metadata.last_successful_execution = datetime.now(UTC)
        selected = self.script("selected", dependencies=["dependency"])
        entrypoint = opendata_dumps.OpendataDumpsEntrypoint()

        with (
            patch.object(opendata_dumps, "discover_scripts", return_value={
                script.script_id: script for script in [selected, dependency]
            }),
            patch.object(opendata_dumps, "rewrite_final_parquets"),
            patch.object(entrypoint, "update_venato") as update,
        ):
            self.assertEqual(entrypoint.run(["selected"]), [selected])

        self.assertEqual(self.calls, ["selected"])
        update.assert_not_called()

    def test_cli_passes_selected_ids_and_venato_flag_and_defaults_to_all(self):
        from run_all_scripts import main

        with patch.object(opendata_dumps.OpendataDumpsEntrypoint, "run") as run:
            main(["elections", "candidatures", "--no-update-venato"])
            run.assert_called_once_with(
                script_ids=["elections", "candidatures"], no_update_venato=True,
            )

            run.reset_mock()
            main([])
            run.assert_called_once_with(script_ids=None, no_update_venato=False)
