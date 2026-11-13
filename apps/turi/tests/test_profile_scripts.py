import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import polars as pl

from scripts.maintenance import profile_scripts
from scripts.operations.candidatures import candidatures


class ProfileScriptsTests(unittest.TestCase):
    def test_worker_measures_photo_selection_without_moving_sources_or_published_assets(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            original_output = root / "parquet_dumps" / "candidates.parquet"
            original_output.parent.mkdir()
            pl.DataFrame({"id": [42]}).write_parquet(original_output)
            source_root = root / "photos"
            folder = source_root / "foto_cand2026_AC_div_12345678_abcdef12"
            folder.mkdir(parents=True)
            source = folder / "FAC123_div.jpg"
            source.write_bytes(b"source photo")
            published = root / "published"
            published.mkdir()
            (published / "301.jpg").write_bytes(b"published photo")
            work = root / "work"
            work.mkdir()

            class Script:
                output_paths = [original_output]

                def process_data(self, logger):
                    pl.DataFrame({"id": [301]}).write_parquet(candidatures.CANDIDATURES_OUTPUT_PARQUETS)
                    keys = pl.DataFrame({
                        "id": [301], "ANO_ELEICAO": [2026], "SG_UF": ["AC"],
                        "SQ_CANDIDATO": ["123"], "_photo_key_count": [1],
                    })
                    candidatures._publish_candidature_photos(keys, source_root, published, logger)

            Script.__module__ = candidatures.__name__

            with patch.object(profile_scripts, "ROOT", root), patch(
                "infra.datascript.discovery.discover_scripts", return_value={"candidatures": Script()},
            ), patch.object(candidatures, "CANDIDATURES_OUTPUT_PARQUETS", original_output), patch.object(
                candidatures, "_publish_candidature_photos", candidatures._publish_candidature_photos,
            ), patch.object(profile_scripts.sys, "addaudithook"):
                profile_scripts.worker("candidatures", work)

            result = json.loads((work / "result.json").read_text())
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["outputs"][0]["rows"], 1)
            self.assertEqual(pl.read_parquet(original_output)["id"].to_list(), [42])
            self.assertEqual(source.read_bytes(), b"source photo")
            self.assertEqual((published / "301.jpg").read_bytes(), b"published photo")
            self.assertEqual(list((work / "assets").iterdir()), [])
