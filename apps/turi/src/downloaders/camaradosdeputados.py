from datetime import timedelta
from pathlib import Path
from infra.downloader.downloader import Downloader
from config.projectsettings.settings import SDS_BASE_URL
from infra.downloader.dynamic_url import DynamicURL
from datetime import datetime

class _cd_ceap_DynamicSources(DynamicURL):
    def gen_urls(self) -> list[str]:
        current_date = datetime.now()
        min_year = 2008
        max_year = current_date.year

        if current_date.month <= 2:
            # a câmara dos deputados divulga novos dados 2 meses após a virada do ano, nesse caso baixamos até o ano passado
            max_year -= 1

        sources = []

        for year in range(min_year, max_year+1):
            sources.append(f"https://www.camara.leg.br/cotas/Ano-{year}.json.zip")

        return sources

cd_federal_deputies = Downloader(
    meta_name="cd_federal_deputies",
    concurrent_downloads=1,
    files_path=Path("camaradosdeputados/federal_deputies"),
    http_client=None,
    limiter_throttle_time=3.0,
    meta_age_tolerance=timedelta(weeks=4),
    meta_path=Path("camaradosdeputados/federal_deputies") / "meta",
    sources=[
        "https://dadosabertos.camara.leg.br/arquivos/deputados/json/deputados.json"
    ],
    dynamic_sources=None
)

cd_legislatures = Downloader(
    meta_name="cd_legislatures",
    concurrent_downloads=1,
    files_path=Path("camaradosdeputados/legislatures"),
    http_client=None,
    limiter_throttle_time=3.0,
    meta_age_tolerance=timedelta(days=3),
    meta_path=Path("camaradosdeputados/legislatures") / "meta",
    sources=[
        "https://dadosabertos.camara.leg.br/arquivos/legislaturas/json/legislaturas.json"
    ],
    dynamic_sources=None
)

cd_ceaps = Downloader(
    meta_name="cd_ceaps",
    concurrent_downloads=1,
    files_path=Path("camaradosdeputados/ceaps"),
    http_client=None,
    limiter_throttle_time=3.0,
    meta_age_tolerance=timedelta(days=3),
    meta_path=Path("camaradosdeputados/ceaps") / "meta",
    sources=[],
    dynamic_sources=_cd_ceap_DynamicSources()
)