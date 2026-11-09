"""Polling-place archives for the configured electoral years."""

from datetime import timedelta
from pathlib import Path

from downloaders.constants import TSE_ELECTION_YEARS
from infra.downloader.downloader import Downloader


tse_voting_locations_downloader = Downloader(
    meta_name="tse_voting_locations",
    meta_age_tolerance=timedelta(weeks=4),
    meta_path=Path("tse/voting_locations/meta"),
    files_path=Path("tse/voting_locations"),
    sources=[
        "https://cdn.tse.jus.br/estatistica/sead/odsele/"
        f"eleitorado_locais_votacao/eleitorado_local_votacao_{year}.zip"
        for year in TSE_ELECTION_YEARS
    ],
    concurrent_downloads=1,
    limiter_throttle_time=3.0,
    csv_separator=";",
    default_encoding="iso-8859-1",
)
