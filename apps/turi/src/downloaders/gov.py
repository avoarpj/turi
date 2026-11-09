from datetime import timedelta
from pathlib import Path
from infra.downloader.downloader import Downloader

gov_amendments = Downloader(
    meta_name="gov_amendments",
    concurrent_downloads=1,
    files_path=Path("gov/amendments"),
    http_client=None,
    limiter_throttle_time=3.0,
    meta_age_tolerance=timedelta(weeks=4),
    meta_path=Path("gov/amendments") / "meta",
    sources=[
        "https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares/UNICO"
    ],
    dynamic_sources=None,
    default_encoding="ISO-8859-1",
    csv_separator=";"
)

gov_municipalities = Downloader(
    meta_name="gov_municipalities",
    concurrent_downloads=1,
    files_path=Path("gov/municipalities"),
    http_client=None,
    limiter_throttle_time=3.0,
    meta_age_tolerance=timedelta(weeks=8),
    meta_path=Path("gov/municipalities") / "meta",
    sources=[
        "https://www.tesourotransparente.gov.br/ckan/dataset/abb968cb-3710-4f85-89cf-875c91b9c7f6/resource/eebb3bc6-9eea-4496-8bcf-304f33155282/download/TABMUN.CSV"
    ],
    dynamic_sources=None,
    default_encoding="ISO-8859-1",
    csv_separator=";",
    csv_header=[
        'codigo_siafi',
        'cnpj_prefeitura',
        'nome',
        'uf',
        'codigo_ibge'
    ]
)