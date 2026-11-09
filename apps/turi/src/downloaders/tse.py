from datetime import timedelta
import logging
import os
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit
from config.projectsettings.settings import RQ_USER_AGENT
from infra.downloader.downloader import Downloader, DownloaderError, DynamicURL
from downloaders.constants import TSE_CKAN_BASE_URL, TSE_ELECTION_YEARS
import ckanapi
from curl_cffi.requests.session import Session

logger = logging.getLogger(__name__)

session = Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": 'Linux',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
})

ckan_cookie = os.getenv("TSE_CKAN_COOKIE", "").strip()
if ckan_cookie:
    session.headers["Cookie"] = ckan_cookie

tse_ckan_agent = ckanapi.RemoteCKAN(TSE_CKAN_BASE_URL, user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
tse_ckan_agent.session = session

# Instância base do Downloader para candidatos (Substitui application/TuriPipe/downloaders_instance.py)
tse_candidates_downloader = Downloader(
    meta_name="tse_candidates",
    concurrent_downloads=1,
    files_path=Path("tse/candidates"),
    http_client=None,
    driver_mode="playwright",
    limiter_throttle_time=3.0,
    meta_age_tolerance=timedelta(weeks=4),
    meta_path=Path("tse/candidates") / "meta",
    sources=[
        "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2018.zip",
        "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2020.zip",
        "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2022.zip",
        "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2026.zip"
    ],
    playwright_headless=False,
    dynamic_sources=None,
    csv_separator=";",
    default_encoding="iso-8859-1"
)

tse_political_parties_directory_downloader = Downloader(
    meta_name="tse_political_parties_directory",
    concurrent_downloads=1,
    files_path=Path("tse/political_parties_directory"),
    driver_mode="playwright",
    limiter_throttle_time=3.0,
    meta_age_tolerance=timedelta(weeks=4),
    meta_path=Path("tse/political_parties_directory") / "meta",
    sources=[
        "https://cdn.tse.jus.br/estatistica/sead/odsele/orgao_partidario/orgao_partidario.zip"
    ],
    dynamic_sources=None,
    csv_separator=";",
    default_encoding="iso-8859-1"
)

def _bulletin_archive_url(url: str) -> str:
    parts = urlsplit(url)
    if not parts.path.lower().endswith(".zip.sha512"):
        return url

    archive_path = parts.path[:-len(".sha512")]
    archive_url = urlunsplit(parts._replace(path=archive_path))
    logger.warning("Catálogo TSE aponta para checksum; usando ZIP: %s", archive_url)

    return archive_url


class tse_evm_bulletins_sources(DynamicURL):
    def gen_urls(self) -> list[str]:
        urls = []

        for year in TSE_ELECTION_YEARS:
            try:
                package = tse_ckan_agent.call_action(
                    "package_show",
                    {"id": f"resultados-{year}-boletim-de-urna"},
                    requests_kwargs={"timeout": (15.0, 60.0)},
                )
                resources = package["resources"]

                for resource in resources:
                    if resource["format"] == "CSV":
                        urls.append(_bulletin_archive_url(resource["url"]))
            except ckanapi.NotFound:
                logger.warning("Catálogo de boletins de %s não encontrado no TSE", year)
            except Exception as error:
                raise RuntimeError(
                    f"Falha ao consultar o catálogo de boletins de {year} no TSE, "
                    "antes de iniciar o Playwright"
                ) from error

        if not urls:
            raise RuntimeError("Nenhuma URL de boletim de urna encontrada no catálogo TSE")

        return list(dict.fromkeys(urls))


class TSEBulletinsDownloader(Downloader):
    def download_from_sources(
        self,
        ext: str,
        content_type: str,
        sources_override: list[str] | None = None,
        is_retry: bool = False,
    ) -> tuple[list[str], list[DownloaderError]]:
        retry_sources = None
        if sources_override is not None:
            retry_sources = list(dict.fromkeys(
                _bulletin_archive_url(url) for url in sources_override
            ))

        return super().download_from_sources(
            ext,
            content_type,
            sources_override=retry_sources,
            is_retry=is_retry,
        )


tse_evm_bulletins_downloader = TSEBulletinsDownloader(
    meta_name="tse_evm_bulletin",
    concurrent_downloads=4,
    files_path=Path("tse/evm_bulletin"),
    http_client=None,
    driver_mode="playwright",
    limiter_throttle_time=3.0,
    meta_age_tolerance=timedelta(weeks=4),
    meta_path=Path("tse/evm_bulletin") / "meta",
    sources=[],
    dynamic_sources=tse_evm_bulletins_sources(),
    csv_separator=";",
    playwright_headless=False,
    default_encoding="iso-8859-1"
)

tse_municipalities_downloader = Downloader(
    meta_name="tse_municipalities",
    concurrent_downloads=1,
    files_path=Path("tse/municipalities"),
    http_client=None,
    driver_mode="playwright",
    limiter_throttle_time=3.0,
    meta_age_tolerance=timedelta(weeks=4),
    meta_path=Path("tse/municipalities") / "meta",
    sources=[
        "https://cdn.tse.jus.br/estatistica/sead/odsele/municipio_tse_ibge/municipio_tse_ibge.zip"
    ],
    dynamic_sources=None,
    csv_separator=";",
    default_encoding="iso-8859-1"
)

class tse_candidatures_photos_sources(DynamicURL):
    def gen_urls(self) -> list[str]:
        urls = []
        start = 0
        page_size = 100

        while True:
            page = tse_ckan_agent.call_action(
                "package_search",
                {
                    "fq": "groups:candidatos",
                    "rows": page_size,
                    "start": start,
                },
                requests_kwargs={"timeout": (15.0, 60.0)},
            )

            for package in page["results"]:
                if not re.fullmatch(r"candidatos-\d{4}(?:-subtemas)?", package["name"]):
                    continue

                for resource in package["resources"]:
                    name = resource.get("name", "").casefold()
                    mime_type = resource.get("mimetype", "").casefold()

                    if "fotos de candidatos" in name and mime_type == "application/zip":
                        urls.append(resource["url"])

            start += len(page["results"])
            if start >= page["count"] or not page["results"]:
                break

        return list(dict.fromkeys(urls))


tse_candidatures_photos = Downloader(
    meta_name="tse_candidatures_photos",
    concurrent_downloads=2,
    files_path=Path("tse/candidatures_photos"),
    driver_mode="httpx",
    limiter_throttle_time=3.0,
    meta_age_tolerance=timedelta(weeks=4),
    meta_path=Path("tse/candidatures_photos") / "meta",
    sources=[],
    dynamic_sources=tse_candidatures_photos_sources(),
    keep_raw=True,
)
