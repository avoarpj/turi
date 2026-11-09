from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from infra.resource_guard import run_guarded


class ResourceGuardTests(unittest.TestCase):
    def test_run_all_scripts_runs_directly_without_global_memory_limits(self):
        import run_all_scripts

        with (
            patch("scripts.entrypoints.opendata_dumps.OpendataDumpsEntrypoint.run") as operation,
            patch.dict("os.environ", {"TURI_MAX_MEMORY_MIB": "0", "TURI_MAX_SWAP_MIB": "0"}),
            patch("subprocess.Popen", side_effect=AssertionError("Unexpected supervisor")),
        ):
            run_all_scripts.main([])

        operation.assert_called_once_with(script_ids=None, no_update_venato=False)

    def test_success_and_failed_exit_are_propagated(self):
        result = run_guarded(
            [sys.executable, "-c", "pass"], max_memory=128 * 1024**2, max_swap=0,
        )
        self.assertGreater(result.seconds, 0)

        import subprocess
        with self.assertRaises(subprocess.CalledProcessError):
            run_guarded(
                [sys.executable, "-c", "raise SystemExit(7)"],
                max_memory=128 * 1024**2, max_swap=0,
            )

    def test_real_allocation_is_interrupted_before_worker_finishes(self):
        with TemporaryDirectory() as directory:
            marker = Path(directory) / "finished"
            code = (
                "import time; from pathlib import Path; "
                "payload = bytearray(128 * 1024**2); time.sleep(5); "
                f"Path({str(marker)!r}).touch()"
            )
            with self.assertRaises(MemoryError):
                run_guarded(
                    [sys.executable, "-c", code], max_memory=64 * 1024**2, max_swap=0,
                )

            self.assertFalse(marker.exists())

    def test_swap_is_counted_even_when_resident_memory_is_low(self):
        with patch("infra.resource_guard._memory_usage", return_value=(1024, 32 * 1024**2)):
            with self.assertRaises(MemoryError):
                run_guarded(
                    [sys.executable, "-c", "import time; time.sleep(5)"],
                    max_memory=128 * 1024**2, max_swap=16 * 1024**2,
                )
