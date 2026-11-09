import logging
import tempfile
import unittest
from pathlib import Path

import polars as pl

from scripts.operations.candidatures.candidatures import _publish_candidature_photos


class CandidaturePhotosTest(unittest.TestCase):
    def test_year_namespaces_photos_and_replaces_existing_asset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "downloads"
            target_root = root / "assets"

            photo_2018 = source_root / "foto_cand2018_AC_div_12345678_12345678"
            photo_2022 = source_root / "foto_cand2022_AC_div_87654321_87654321"
            photo_2018.mkdir(parents=True)
            photo_2022.mkdir(parents=True)
            target_root.mkdir()

            (photo_2018 / "FAC123_div.jpg").write_bytes(b"photo 2018")
            (photo_2022 / "FAC123_div.jpeg").write_bytes(b"photo 2022")
            (photo_2022 / "FAC456_div.jpg").write_bytes(b"first")
            (photo_2022 / "FAC456_div.jpeg").write_bytes(b"second")
            (photo_2022 / "leiame.pdf").write_bytes(b"documentation")
            (target_root / "111.jpg").write_bytes(b"old photo")
            (target_root / "222.png").write_bytes(b"old format")

            photo_keys = pl.DataFrame({
                "id": [111, 222, 333],
                "ANO_ELEICAO": ["2018", "2022", "2022"],
                "SG_UF": ["AC", "AC", "AC"],
                "SQ_CANDIDATO": ["123", "123", "456"],
                "_photo_key_count": [1, 1, 1],
            })

            _publish_candidature_photos(
                photo_keys, source_root, target_root, logging.getLogger(__name__)
            )

            self.assertEqual((target_root / "111.jpg").read_bytes(), b"photo 2018")
            self.assertEqual((target_root / "222.jpeg").read_bytes(), b"photo 2022")
            self.assertFalse((target_root / "222.png").exists())
            self.assertFalse((photo_2018 / "FAC123_div.jpg").exists())
            self.assertFalse((photo_2022 / "FAC123_div.jpeg").exists())
            self.assertFalse((target_root / "333.jpg").exists())
            self.assertTrue((photo_2022 / "FAC456_div.jpg").exists())
            self.assertTrue((photo_2022 / "leiame.pdf").exists())

            _publish_candidature_photos(
                photo_keys, source_root, target_root, logging.getLogger(__name__)
            )
            self.assertEqual((target_root / "111.jpg").read_bytes(), b"photo 2018")
            self.assertEqual((target_root / "222.jpeg").read_bytes(), b"photo 2022")

    def test_ambiguous_candidate_key_does_not_move_photo(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_root = root / "downloads"
            photo_dir = source_root / "foto_cand2022_AC_div_12345678_12345678"
            photo_dir.mkdir(parents=True)
            photo = photo_dir / "FAC123_div.jpg"
            photo.write_bytes(b"photo")

            photo_keys = pl.DataFrame({
                "id": [111, 222],
                "ANO_ELEICAO": ["2022", "2022"],
                "SG_UF": ["AC", "AC"],
                "SQ_CANDIDATO": ["123", "123"],
                "_photo_key_count": [1, 1],
            })

            _publish_candidature_photos(
                photo_keys, source_root, root / "assets", logging.getLogger(__name__)
            )

            self.assertTrue(photo.exists())
            self.assertFalse((root / "assets").exists())


if __name__ == "__main__":
    unittest.main()
