import tempfile
import unittest
import zipfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import httpx

from infra.downloader.downloader import Downloader


class TSEPhotoArchiveTest(unittest.TestCase):
    def test_http_download_streams_zip_before_extracting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            source_zip = base_dir / "source.zip"
            with zipfile.ZipFile(source_zip, "w") as archive:
                archive.writestr("fotos/123.jpg", b"image data")

            transport = httpx.MockTransport(
                lambda _request: httpx.Response(200, content=source_zip.read_bytes())
            )
            with httpx.Client(transport=transport) as client:
                downloader = Downloader(
                    meta_name="photos",
                    meta_age_tolerance=timedelta(days=1),
                    meta_path=Path("photos/meta"),
                    files_path=Path("photos"),
                    sources=[],
                    http_client=client,
                    keep_raw=True,
                )

                with patch("infra.downloader.downloader.BASE_DIR", base_dir):
                    files, error = downloader.download_and_process(
                        "https://example.org/foto_cand2026_AC_div.zip", "zip"
                    )

            self.assertIsNone(error)
            self.assertEqual(len(files), 1)
            self.assertEqual((Path(files[0]) / "fotos" / "123.jpg").read_bytes(), b"image data")

    def test_keep_zip_alone_or_with_extracted_files(self):
        for keep_raw in (False, True):
            with self.subTest(keep_raw=keep_raw):
                with tempfile.TemporaryDirectory() as temp_dir:
                    base_dir = Path(temp_dir)
                    source_zip = base_dir / "source.zip"
                    with zipfile.ZipFile(source_zip, "w") as archive:
                        archive.writestr("fotos/123.jpg", b"image data")

                    downloader = Downloader(
                        meta_name="photos",
                        meta_age_tolerance=timedelta(days=1),
                        meta_path=Path("photos/meta"),
                        files_path=Path("photos"),
                        sources=[],
                        keep_zip=True,
                        keep_raw=keep_raw,
                    )

                    def copy_zip(_source, target_file):
                        target_file.write_bytes(source_zip.read_bytes())

                    with patch("infra.downloader.downloader.BASE_DIR", base_dir):
                        with patch.object(
                            downloader, "_download_via_httpx", side_effect=copy_zip
                        ):
                            files, error = downloader.download_and_process(
                                "https://example.org/foto_cand2026_AC_div.zip", "zip"
                            )

                    self.assertIsNone(error)
                    self.assertEqual(len(files), 2 if keep_raw else 1)
                    self.assertTrue(zipfile.is_zipfile(files[-1]))

                    if keep_raw:
                        self.assertEqual(
                            (Path(files[0]) / "fotos" / "123.jpg").read_bytes(),
                            b"image data",
                        )
                    else:
                        self.assertEqual(
                            [path for path in (base_dir / "downloads" / "photos").iterdir()],
                            [Path(files[0])],
                        )

    def test_zip_is_extracted_and_replaced_without_converting_photos(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            source_zip = base_dir / "source.zip"
            with zipfile.ZipFile(source_zip, "w") as archive:
                archive.writestr("foto_cand2026_AC/123.jpg", b"image data")

            downloader = Downloader(
                meta_name="photos",
                meta_age_tolerance=timedelta(days=1),
                meta_path=Path("photos/meta"),
                files_path=Path("photos"),
                sources=["https://example.org/foto_cand2026_AC_div.zip"],
                keep_raw=True,
            )

            def copy_zip(_source, target_file):
                target_file.write_bytes(source_zip.read_bytes())

            with patch("infra.downloader.downloader.BASE_DIR", base_dir):
                with patch.object(downloader, "_download_via_httpx", side_effect=copy_zip):
                    files, errors = downloader.download_from_sources("zip", "application/zip")

                    self.assertEqual(errors, [])
                    self.assertEqual(len(files), 1)

                    extracted_dir = Path(files[0])
                    photo = extracted_dir / "foto_cand2026_AC" / "123.jpg"
                    self.assertEqual(photo.read_bytes(), b"image data")
                    self.assertEqual(list(extracted_dir.rglob("*.zip")), [])
                    self.assertEqual(downloader.get_meta().files, files)

                    new_files, new_errors = downloader.download_from_sources(
                        "zip", "application/zip"
                    )

            self.assertEqual(new_errors, [])
            self.assertEqual(len(new_files), 1)
            self.assertFalse(extracted_dir.exists())
            self.assertTrue((Path(new_files[0]) / "foto_cand2026_AC" / "123.jpg").is_file())


if __name__ == "__main__":
    unittest.main()
