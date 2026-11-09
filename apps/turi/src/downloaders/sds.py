from datetime import timedelta
from pathlib import Path
from infra.downloader.downloader import Downloader
from apps.turi.src.downloaders.sds_callbacks import (
    municipalities_centroid,
    federal_deputies_history,
    federal_deputies_detailed,
)

sds_municipalities_centroid = Downloader(
    meta_name="sds_municipalities_centroid",
    concurrent_downloads=1,
    files_path=Path("sds/municipalities_centroid"),
    http_client=None,
    limiter_throttle_time=3.0,
    meta_age_tolerance=timedelta(weeks=4),
    meta_path=Path("sds/municipalities_centroid") / "meta",
    sources=[
        "https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_2024/Brasil/BR_Municipios_2024.zip"
    ],
    dynamic_sources=None,
    download_callback=municipalities_centroid,
)

sds_federal_deputies_history = Downloader(
    meta_name="sds_federal_deputies_history",
    concurrent_downloads=1,
    files_path=Path("sds/federal_deputies_history"),
    http_client=None,
    limiter_throttle_time=3.0,
    meta_age_tolerance=timedelta(days=3),
    meta_path=Path("sds/federal_deputies_history") / "meta",
    sources=[
        "https://dadosabertos.camara.leg.br/arquivos/deputados/json/deputados.json"
    ],
    dynamic_sources=None,
    download_callback=federal_deputies_history,
)

sds_federal_deputies_detailed = Downloader(
    meta_name="sds_federal_deputies_detailed",
    concurrent_downloads=1,
    files_path=Path("sds/federal_deputies_detailed"),
    http_client=None,
    limiter_throttle_time=3.0,
    meta_age_tolerance=timedelta(weeks=4),
    meta_path=Path("sds/federal_deputies_detailed") / "meta",
    sources=[
        "https://dadosabertos.camara.leg.br/arquivos/deputados/json/deputados.json"
    ],
    dynamic_sources=None,
    download_callback=federal_deputies_detailed,
)
