from datetime import datetime, timedelta
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import httpx

from infra.downloader.downloader import Downloader, DownloaderMeta


class DownloaderStartupTests(TestCase):
    def make_downloader(self, client, dynamic_sources):
        return Downloader(
            meta_name="startup",
            meta_age_tolerance=timedelta(days=1),
            meta_path=Path("startup/meta"),
            files_path=Path("startup"),
            sources=["https://example.org/static.csv"],
            dynamic_sources=dynamic_sources,
            http_client=client,
            limiter_throttle_time=0,
        )

    def test_valid_metadata_avoids_source_discovery_and_downloads(self):
        dynamic_sources = Mock()
        dynamic_sources.gen_urls.side_effect = AssertionError("Unexpected discovery")

        with TemporaryDirectory() as directory, httpx.Client() as client:
            root = Path(directory)
            cached = root / "cached.parquet"
            cached.write_bytes(b"existing data")

            downloader = self.make_downloader(client, dynamic_sources)

            with patch("infra.downloader.downloader.BASE_DIR", root):
                downloader.create_meta(DownloaderMeta(
                    downloaded_at=datetime.now(),
                    files=[str(cached)],
                    successful=True,
                ))

                files, errors = downloader.get_meta_files_or_download("csv", "text/csv")

        self.assertEqual(files, [str(cached)])
        self.assertEqual(errors, [])
        dynamic_sources.gen_urls.assert_not_called()

    def test_needed_download_discovers_sources_once_and_uses_both_lists(self):
        dynamic_sources = Mock()
        dynamic_sources.gen_urls.return_value = ["https://example.org/dynamic.csv"]

        with TemporaryDirectory() as directory, httpx.Client() as client:
            root = Path(directory)
            downloader = self.make_downloader(client, dynamic_sources)
            dynamic_sources.gen_urls.assert_not_called()

            with patch("infra.downloader.downloader.BASE_DIR", root), patch.object(
                downloader, "_run_execution_pool", return_value=([], [], [])
            ) as execution_pool:
                downloader.get_meta_files_or_download("csv", "text/csv")
                downloader.download_from_sources("csv", "text/csv")

        dynamic_sources.gen_urls.assert_called_once_with()
        for call in execution_pool.call_args_list:
            self.assertEqual(call.args, (
                ["https://example.org/static.csv", "https://example.org/dynamic.csv"],
                "csv",
            ))

    def test_discovery_failure_preserves_old_files_and_can_be_retried(self):
        dynamic_sources = Mock()
        dynamic_sources.gen_urls.side_effect = [
            RuntimeError("catalog unavailable"),
            ["https://example.org/dynamic.csv"],
        ]

        with TemporaryDirectory() as directory, httpx.Client() as client:
            root = Path(directory)
            cached = root / "cached.parquet"
            cached.write_bytes(b"existing data")

            downloader = self.make_downloader(client, dynamic_sources)

            with patch("infra.downloader.downloader.BASE_DIR", root), patch.object(
                downloader, "_run_execution_pool", return_value=([], [], [])
            ) as execution_pool:
                downloader.create_meta(DownloaderMeta(
                    downloaded_at=datetime.now() - timedelta(days=2),
                    files=[str(cached)],
                    successful=True,
                ))

                with self.assertRaisesRegex(RuntimeError, "catalog unavailable"):
                    downloader.get_meta_files_or_download("csv", "text/csv")

                self.assertEqual(cached.read_bytes(), b"existing data")
                self.assertEqual(downloader.get_meta().files, [str(cached)])
                execution_pool.assert_not_called()

                downloader.get_meta_files_or_download("csv", "text/csv")

        self.assertEqual(dynamic_sources.gen_urls.call_count, 2)
        execution_pool.assert_called_once()

    def test_retry_uses_failed_urls_without_discovery(self):
        dynamic_sources = Mock()
        dynamic_sources.gen_urls.side_effect = AssertionError("Unexpected discovery")

        with TemporaryDirectory() as directory, httpx.Client() as client:
            root = Path(directory)
            downloader = self.make_downloader(client, dynamic_sources)

            with patch("infra.downloader.downloader.BASE_DIR", root), patch.object(
                downloader, "_run_execution_pool", return_value=([], [], [])
            ) as execution_pool:
                downloader.create_meta(DownloaderMeta(
                    downloaded_at=datetime.now(),
                    files=[],
                    failed_sources=["https://example.org/failed.csv"],
                    successful=False,
                ))

                downloader.get_meta_files_or_download("csv", "text/csv")

        execution_pool.assert_called_once_with(["https://example.org/failed.csv"], "csv")
        dynamic_sources.gen_urls.assert_not_called()

    def test_real_registry_import_does_not_call_remote_services(self):
        project_root = Path(__file__).resolve().parents[3]
        script = """
from unittest.mock import patch

with (
    patch('ckanapi.RemoteCKAN.call_action', side_effect=AssertionError('CKAN on import')),
    patch('httpx.AsyncClient.request', side_effect=AssertionError('Async HTTP on import')),
    patch('httpx.Client.send', side_effect=AssertionError('HTTP on import')),
):
    from pipelines.registry import downloaders_registry

assert downloaders_registry
"""
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join([
            str(project_root / "apps/turi/src"),
            str(project_root),
        ])

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=project_root / "apps/turi",
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
