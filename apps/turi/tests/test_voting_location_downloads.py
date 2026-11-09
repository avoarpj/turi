from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import zipfile

import httpx
import polars as pl

from downloaders.constants import TSE_ELECTION_YEARS
from downloaders.tse_voting_locations import tse_voting_locations_downloader


class VotingLocationDownloadsTests(TestCase):
    def test_sources_follow_the_same_years_as_electoral_downloads(self):
        self.assertEqual(
            [
                int(url.rsplit("_", 1)[1][:-4])
                for url in tse_voting_locations_downloader.sources
            ],
            TSE_ELECTION_YEARS,
        )

    def test_state_csvs_are_all_converted_without_requiring_a_national_file(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.zip"
            with zipfile.ZipFile(source, "w") as archive:
                for uf, name in [("SP", "Escola São José"), ("AC", "Colégio Acre")]:
                    csv = f'"SG_UF";"NM_LOCAL_VOTACAO"\n"{uf}";"{name}"\n'
                    archive.writestr(
                        f"eleitorado_local_votacao_2026_{uf}.csv",
                        csv.encode("latin-1"),
                    )

                archive.writestr("leiame.pdf", b"not converted")

            with httpx.Client(transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, content=source.read_bytes())
            )) as client:
                with patch("infra.downloader.downloader.BASE_DIR", root), patch.object(
                    tse_voting_locations_downloader, "http_client", client,
                ):
                    files, error = tse_voting_locations_downloader.download_and_process(
                        "https://example.org/locations.zip", "zip"
                    )

            self.assertIsNone(error)
            result = pl.concat([pl.read_parquet(file) for file in files])
            self.assertEqual(set(result["SG_UF"]), {"SP", "AC"})
            self.assertEqual(
                set(result["NM_LOCAL_VOTACAO"]),
                {"Escola São José", "Colégio Acre"},
            )
