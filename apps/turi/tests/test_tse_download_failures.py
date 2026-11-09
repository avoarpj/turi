from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import ckanapi
import httpx

from downloaders.tse import TSEBulletinsDownloader, tse_evm_bulletins_sources
from infra.downloader.downloader import Downloader, DownloaderError, DownloaderMeta
from scripts.entrypoints import opendata_downloads


class TSEDownloadFailuresTests(TestCase):
    def test_catalog_checksum_url_resolves_to_archive_without_duplicates(self):
        archive_url = "https://example.org/bweb_2t_RR.zip?download=1"
        checksum_url = "https://example.org/bweb_2t_RR.zip.sha512?download=1"

        with patch("downloaders.tse.TSE_ELECTION_YEARS", [2026]), patch(
            "downloaders.tse.tse_ckan_agent.call_action",
            return_value={"resources": [
                {"format": "CSV", "url": archive_url},
                {"format": "CSV", "url": checksum_url},
            ]},
        ), self.assertLogs("downloaders.tse", level="WARNING"):
            urls = tse_evm_bulletins_sources().gen_urls()

        self.assertEqual(urls, [archive_url])

    def test_saved_checksum_retry_preserves_files_and_retries_the_archive(self):
        archive_url = "https://example.org/bweb_2t_RR.zip"

        for succeeds in (True, False):
            with self.subTest(succeeds=succeeds):
                with TemporaryDirectory() as directory, httpx.Client() as client:
                    root = Path(directory)
                    previous = root / "previous.parquet"
                    previous.write_bytes(b"existing bulletin")
                    recovered = root / "recovered.parquet"
                    recovered.write_bytes(b"recovered bulletin")

                    downloader = TSEBulletinsDownloader(
                        meta_name="bulletins",
                        meta_age_tolerance=timedelta(days=1),
                        meta_path=Path("bulletins/meta"),
                        files_path=Path("bulletins"),
                        sources=[],
                        http_client=client,
                    )
                    error = DownloaderError(archive_url, "unavailable", None)
                    pool_result = (
                        ([str(recovered)], [], []) if succeeds
                        else ([], [error], [archive_url])
                    )

                    with patch("infra.downloader.downloader.BASE_DIR", root), patch.object(
                        downloader, "_run_execution_pool", return_value=pool_result
                    ) as execution_pool, self.assertLogs("downloaders.tse", level="WARNING"):
                        downloader.create_meta(DownloaderMeta(
                            downloaded_at=datetime.now(),
                            files=[str(previous)],
                            failed_sources=[f"{archive_url}.sha512"],
                            successful=False,
                        ))

                        files, errors = downloader.get_meta_files_or_download(
                            "zip", "application/zip"
                        )
                        meta = downloader.get_meta()

                    execution_pool.assert_called_once_with([archive_url], "zip")
                    self.assertEqual(previous.read_bytes(), b"existing bulletin")
                    self.assertIn(str(previous), files)
                    self.assertEqual(meta.successful, succeeds)
                    self.assertEqual(meta.failed_sources, [] if succeeds else [archive_url])
                    self.assertEqual(errors, [] if succeeds else [error])
                    if succeeds:
                        self.assertIn(str(recovered), files)

    def test_catalog_error_is_not_treated_as_an_empty_successful_download(self):
        with patch("downloaders.tse.TSE_ELECTION_YEARS", [2022]), patch(
            "downloaders.tse.tse_ckan_agent.call_action",
            side_effect=RuntimeError("catalog blocked"),
        ):
            with self.assertRaisesRegex(RuntimeError, "2022.*antes de iniciar o Playwright"):
                tse_evm_bulletins_sources().gen_urls()

    def test_unpublished_year_is_skipped_without_hiding_other_resources(self):
        with patch("downloaders.tse.TSE_ELECTION_YEARS", [2022, 2026]), patch(
            "downloaders.tse.tse_ckan_agent.call_action",
            side_effect=[
                {"resources": [
                    {"format": "CSV", "url": "https://example.org/2022.zip"},
                    {"format": "PDF", "url": "https://example.org/readme.pdf"},
                ]},
                ckanapi.NotFound("unpublished year"),
            ],
        ), self.assertLogs("downloaders.tse", level="WARNING"):
            urls = tse_evm_bulletins_sources().gen_urls()

        self.assertEqual(urls, ["https://example.org/2022.zip"])

    def test_catalog_without_any_resources_does_not_start_downloads(self):
        with patch("downloaders.tse.TSE_ELECTION_YEARS", [2026]), patch(
            "downloaders.tse.tse_ckan_agent.call_action",
            return_value={"resources": []},
        ):
            with self.assertRaisesRegex(RuntimeError, "Nenhuma URL"):
                tse_evm_bulletins_sources().gen_urls()

    def test_browser_startup_error_is_logged_and_persisted_as_failed(self):
        source = "https://example.org/candidates.zip"

        with TemporaryDirectory() as directory, httpx.Client() as client:
            root = Path(directory)
            downloader = Downloader(
                meta_name="candidates",
                meta_age_tolerance=timedelta(days=1),
                meta_path=Path("candidates/meta"),
                files_path=Path("candidates"),
                sources=[source],
                driver_mode="playwright",
                http_client=client,
                concurrent_downloads=1,
                limiter_throttle_time=0,
            )

            with patch("infra.downloader.downloader.BASE_DIR", root), patch(
                "infra.downloader.downloader._PlaywrightDriver",
                side_effect=RuntimeError("Chromium executable missing"),
            ), self.assertLogs("infra.downloader.downloader", level="INFO") as logs:
                files, errors = downloader.get_meta_files_or_download(
                    "zip", "application/zip"
                )
                meta = downloader.get_meta()

        self.assertEqual(files, [])
        self.assertEqual(len(errors), 1)
        self.assertEqual(meta.failed_sources, [source])
        self.assertFalse(meta.successful)
        self.assertTrue(any("Starting Playwright" in line for line in logs.output))
        self.assertTrue(any("Chromium executable missing" in line for line in logs.output))

    def test_entrypoint_stops_on_bulletin_or_candidate_download_errors(self):
        downloaders = [
            opendata_downloads.tse_voting_locations_downloader,
            opendata_downloads.tse_evm_bulletins_downloader,
            opendata_downloads.tse_candidates_downloader,
            opendata_downloads.cd_federal_deputies,
        ]
        error = DownloaderError("https://example.org/archive.zip", "browser failed", None)

        for failed_index, expected in [(1, "boletins de urna"), (2, "candidaturas")]:
            with self.subTest(failed_index=failed_index):
                with patch.object(
                    downloaders[0], "get_meta_files_or_download", return_value=([], [])
                ), patch.object(
                    downloaders[1],
                    "get_meta_files_or_download",
                    return_value=([], [error] if failed_index == 1 else []),
                ), patch.object(
                    downloaders[2],
                    "get_meta_files_or_download",
                    return_value=([], [error] if failed_index == 2 else []),
                ) as candidates, patch.object(
                    downloaders[3], "get_meta_files_or_download"
                ) as next_source:
                    with self.assertRaisesRegex(RuntimeError, expected):
                        opendata_downloads.OpendataDownloadsEntrypoint().run()

                if failed_index == 1:
                    candidates.assert_not_called()

                next_source.assert_not_called()
