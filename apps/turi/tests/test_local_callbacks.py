from datetime import datetime, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import httpx
import polars as pl

from apps.turi.src.downloaders import sds_callbacks
from apps.turi.src.downloaders._sds.infra.scripts import centroide_municipios_brasileiros
from infra.downloader.downloader import Downloader, DownloaderMeta


class LocalCallbackTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        base = patch("infra.downloader.downloader.BASE_DIR", self.root)
        base.start()
        self.addCleanup(base.stop)
        self.client = httpx.Client(transport=httpx.MockTransport(
            lambda request: self.fail("Callback unexpectedly made an HTTP request")
        ))
        self.addCleanup(self.client.close)

    def downloader(self, callback):
        return Downloader(
            meta_name="local",
            meta_age_tolerance=timedelta(days=1),
            meta_path=Path("local/meta"),
            files_path=Path("local"),
            sources=["https://example.org/source"],
            http_client=self.client,
            limiter_throttle_time=0,
            download_callback=callback,
        )

    def test_callback_replaces_transfer_and_uses_normal_conversion_and_cache(self):
        callback = Mock(side_effect=lambda downloader, source, target: target.write_text(
            '[{"id":1,"nome":"Município"}]', encoding="utf-8"
        ))
        downloader = self.downloader(callback)

        files, errors = downloader.get_meta_files_or_download("json", "application/json")
        self.assertEqual(errors, [])
        self.assertEqual(pl.read_parquet(files[0]).to_dicts(), [{"id": 1, "nome": "Município"}])
        self.assertEqual(downloader.get_meta_files_or_download("json", "application/json"), (files, []))
        callback.assert_called_once()

    def test_failed_refresh_preserves_published_cache_and_retry_replaces_it(self):
        callback = Mock(side_effect=RuntimeError("source unavailable"))
        downloader = self.downloader(callback)
        old = self.root / "old.parquet"
        pl.DataFrame({"id": [1]}).write_parquet(old)
        downloader.create_meta(DownloaderMeta(
            downloaded_at=datetime.now() - timedelta(days=2),
            files=[str(old)],
            successful=True,
        ))

        files, errors = downloader.get_meta_files_or_download("json", "application/json")
        self.assertEqual(files, [str(old)])
        self.assertEqual(len(errors), 1)
        self.assertTrue(old.exists())
        self.assertFalse(downloader.get_meta().successful)

        callback.side_effect = lambda downloader, source, target: target.write_text('[{"id":2}]')
        files, errors = downloader.get_meta_files_or_download("json", "application/json")
        self.assertEqual(errors, [])
        self.assertEqual(len(files), 1)
        self.assertEqual(pl.read_parquet(files[0])["id"].to_list(), [2])
        self.assertFalse(old.exists())
        self.assertTrue(downloader.get_meta().successful)

    def test_missing_or_empty_callback_output_is_an_error(self):
        for callback in (
            lambda downloader, source, target: None,
            lambda downloader, source, target: target.write_text("[]"),
            lambda downloader, source, target: target.write_text("invalid json"),
        ):
            with self.subTest(callback=callback):
                files, errors = self.downloader(callback).download_from_sources("json", "application/json")
                self.assertEqual(files, [])
                self.assertEqual(len(errors), 1)

    def test_real_centroid_callback_resolves_paths_and_preserves_output_schema(self):
        import geopandas as gpd
        from shapely.geometry import Polygon

        records = gpd.GeoDataFrame(
            {"CD_MUN": ["3550308"], "NM_MUN": ["São Paulo"], "SIGLA_UF": ["SP"]},
            geometry=[Polygon([(-47, -24), (-46, -24), (-46, -23), (-47, -23)])],
            crs="EPSG:4674",
        )
        target = self.root / "centroides.json"
        seen = []

        def skip_download(dataset, extractor=None):
            seen.append(dataset.getProcessFile().path)

        with (
            patch.object(sds_callbacks, "BASE_DIR", self.root),
            patch.object(centroide_municipios_brasileiros, "BASE_DIR", self.root),
            patch.object(sds_callbacks.DatasetMeta, "downloadIfNecessary", skip_download),
            patch.object(gpd, "read_file", return_value=records),
        ):
            sds_callbacks.municipalities_centroid(None, "source", target)

        self.assertTrue(Path(seen[0]).is_absolute())
        row = json.loads(target.read_text())[0]
        self.assertEqual(row["codigo_municipio"], "3550308")
        self.assertEqual(row["nome_municipio"], "São Paulo")
        self.assertEqual(row["uf"], "SP")
        self.assertAlmostEqual(row["latitude"], -23.5, delta=0.1)
        self.assertAlmostEqual(row["longitude"], -46.5, delta=0.1)

    def test_history_bootstrap_then_incremental_selection(self):
        target = self.root / "result.json"
        with patch.object(sds_callbacks, "BASE_DIR", self.root), patch.object(sds_callbacks, "_generate") as generate:
            sds_callbacks.federal_deputies_history(None, "source", target)
            self.assertEqual(generate.call_args.args[1], "historico_deputados_federais")

            output = self.root / "public/datasets/historico_deputados_federais/historico.json"
            output.parent.mkdir(parents=True)
            output.write_text('{"dados": []}')
            sds_callbacks.federal_deputies_history(None, "source", target)
            self.assertEqual(generate.call_args.args[1], "historico_deputados_federais_incremental")
