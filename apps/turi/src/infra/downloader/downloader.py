import json
import hashlib
import logging
import queue
import shutil
import threading
import time
import uuid
import zipfile
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Callable, List, Literal, Optional, Tuple, Union
from urllib.parse import unquote, urlsplit

import httpx
import pandas as pd
import polars as pl
from pydantic import BaseModel

try:
    from playwright.sync_api import Browser, sync_playwright
except ImportError:
    sync_playwright = None
    Browser = None

from apps.turi.src.config.projectsettings.settings import BASE_DIR
from apps.turi.src.infra.csv_to_parquet_stream import csv_to_parquet_stream
from apps.turi.src.infra.downloader.dynamic_url import DynamicURL

DOWNLOADER_META_PREFIX = "__DownloaderMeta;"
logger = logging.getLogger(__name__)


class DownloaderMeta(BaseModel):
    downloaded_at: datetime
    files: List[str]
    failed_sources: List[str] = []
    successful: bool


class DownloaderError(Exception):
    def __init__(self, path: str, message: str, original_err: Exception | None):
        self.path = path
        self.message = message
        self.original_err = original_err
        super().__init__(self.message)


class _PlaywrightDriver:
    """
    Mantém UMA única instância do navegador viva, controlada por uma thread
    dedicada. A API síncrona do Playwright não é segura para chamadas
    concorrentes vindas de threads diferentes -- cada `sync_playwright()`
    abre sua própria conexão com o processo driver, e subir várias
    concorrentemente (uma por thread do pool) é o cenário clássico que trava
    o IPC indefinidamente sem lançar nenhuma exceção.

    Aqui, as threads de download apenas enfileiram um pedido ("entra nesse
    link e espera o download"); quem efetivamente conversa com o navegador
    é sempre a mesma thread, uma solicitação de cada vez -- exatamente como
    um único navegador real seria usado por uma pessoa.

    O navegador usa um único `BrowserContext` (não um novo por download):
    cookies de sessão setados pelo site em uma navegação (ex.: cookie de
    autenticação/CKAN) continuam valendo nas navegações seguintes, porque
    é o mesmo cookie jar o tempo todo -- exatamente como aconteceria numa
    aba de navegador real sendo reaproveitada.
    """

    def __init__(self, headless: bool, warmup_url: Optional[str] = None):
        if sync_playwright is None:
            raise ImportError(
                "Playwright não está instalado. Execute: "
                "uv sync && uv run playwright install chromium"
            )
        self.headless = headless
        self.warmup_url = warmup_url
        self._jobs: "queue.Queue" = queue.Queue()
        self._ready = threading.Event()
        self._start_error: Optional[BaseException] = None
        self._thread = threading.Thread(
            target=self._run, name="playwright-driver", daemon=True
        )
        self._thread.start()
        self._ready.wait()
        if self._start_error:
            raise self._start_error

    def _run(self):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless)
                try:
                    context = browser.new_context(accept_downloads=True)
                    try:
                        if self.warmup_url:
                            warmup_page = context.new_page()
                            try:
                                warmup_page.goto(self.warmup_url, timeout=30_000)
                            except Exception:
                                pass
                            finally:
                                warmup_page.close()

                        self._ready.set()
                        while True:
                            job = self._jobs.get()
                            if job is None:
                                break
                            url, target_file, goto_timeout_ms, download_timeout_ms, done = job
                            try:
                                self._download_one(
                                    context, url, target_file, goto_timeout_ms, download_timeout_ms
                                )
                                done.set_result(None)
                            except Exception as e:
                                done.set_exception(e)
                    finally:
                        context.close()
                finally:
                    browser.close()
        except Exception as e:
            self._start_error = e
            self._ready.set()

    def _download_one(
        self,
        context,
        url: str,
        target_file: Path,
        goto_timeout_ms: int,
        download_timeout_ms: int,
    ):
        page = context.new_page()
        try:
            with page.expect_download(timeout=download_timeout_ms) as download_info:
                try:
                    page.goto(url, timeout=goto_timeout_ms)
                except Exception:
                    pass
            download_info.value.save_as(target_file)
        finally:
            page.close()

    def download(
        self,
        url: str,
        target_file: Path,
        goto_timeout_ms: int,
        download_timeout_ms: int,
    ) -> None:
        done: "Future" = Future()
        self._jobs.put((url, target_file, goto_timeout_ms, download_timeout_ms, done))

        done.result()

    def close(self):
        self._jobs.put(None)
        self._thread.join(timeout=30)


class Downloader:
    def __init__(
        self,
        meta_name: str,
        meta_age_tolerance: timedelta,
        meta_path: Path,
        files_path: Path,
        sources: List[str],
        dynamic_sources: Optional[DynamicURL] = None,
        concurrent_downloads: int = 5,
        limiter_throttle_time: float = 1.0,
        http_client: Optional[httpx.Client] = None,
        driver_mode: Literal["httpx", "playwright"] = "httpx",
        csv_separator: str = ",",
        default_encoding: str = "utf-8",
        hard_suffix: str | None = None,
        csv_has_header: bool = True,
        csv_header: list[str] | None = None,
        referer: Optional[str] = None,
        playwright_headless: bool = False,
        playwright_goto_timeout_ms: int = 30_000,
        playwright_download_timeout_ms: int = 60_000,
        playwright_warmup_url: Optional[str] = None,
        keep_raw: bool = False,
        keep_zip: bool = False,
        download_callback: Callable[["Downloader", str, Path], None] | None = None,
    ):
        self.download_callback = download_callback

        self.meta_name = meta_name
        self.meta_age_tolerance = meta_age_tolerance
        self.meta_path = meta_path
        self.files_path = files_path
        self.sources = list(sources)
        self.dynamic_sources = dynamic_sources
        self._dynamic_sources_resolved = False
        self.concurrent_downloads = concurrent_downloads
        self.limiter_throttle_time = limiter_throttle_time
        self.driver_mode = driver_mode
        self.referer = referer
        self.keep_raw = keep_raw
        self.keep_zip = keep_zip

        self.playwright_headless = playwright_headless
        self.playwright_goto_timeout_ms = playwright_goto_timeout_ms
        self.playwright_download_timeout_ms = playwright_download_timeout_ms
        self.playwright_warmup_url = playwright_warmup_url
        self._playwright_driver: Optional[_PlaywrightDriver] = None
        self._playwright_driver_lock = Lock()

        self.http_client = http_client or httpx.Client(
            follow_redirects=True,
            headers={"Referer": self.referer} if self.referer else None,
            timeout=60.0,
        )

        self.last_downloads = datetime.min
        self.lock = Lock()

        self.csv_separator = csv_separator
        self.default_encoding = default_encoding
        self.csv_has_header = csv_has_header
        self.csv_header = csv_header

        self.hard_suffix = hard_suffix

    def _resolve_sources(self) -> List[str]:
        if self.dynamic_sources is not None and not self._dynamic_sources_resolved:
            logger.info("Resolving dynamic sources for %s", self.meta_name)

            sources = self.dynamic_sources.gen_urls()
            self.sources.extend(sources)
            self._dynamic_sources_resolved = True

        return self.sources

    def get_meta_filename(self) -> Path:
        filename = f"{DOWNLOADER_META_PREFIX}{self.meta_name}.json"
        return BASE_DIR / "downloads" / self.meta_path / filename

    def get_meta(self) -> Optional[DownloaderMeta]:
        file_path = self.get_meta_filename()
        if not file_path.exists():
            return None
        try:
            data = json.loads(file_path.read_text())
            meta = DownloaderMeta(**data)

            if meta.files and not all(Path(f).exists() for f in meta.files):
                return None
            return meta
        except Exception:
            return None

    def create_meta(self, data: DownloaderMeta) -> None:
        file_path = self.get_meta_filename()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(data.model_dump_json(indent=2))

    def get_meta_files_or_download(
        self, ext: str, content_type: str
    ) -> Tuple[List[str], List[DownloaderError]]:
        meta = self.get_meta()
        now = datetime.now()

        if meta:
            is_valid_age = (now - meta.downloaded_at) <= self.meta_age_tolerance

            if is_valid_age and meta.successful:
                logger.info(
                    "Using cached files for %s (%d files)", self.meta_name, len(meta.files)
                )
                return meta.files, []

            if is_valid_age and meta.failed_sources:
                return self.download_from_sources(
                    ext, content_type, sources_override=meta.failed_sources, is_retry=True
                )

        return self.download_from_sources(ext, content_type)

    def _convert_to_parquet(self, source_path: Path) -> Optional[str]:
        try:
            target_path = (
                BASE_DIR
                / "downloads"
                / self.files_path
                / f"{uuid.uuid4().hex[:16]}.parquet"
            )
            target_path.parent.mkdir(parents=True, exist_ok=True)

            ext = source_path.suffix.lower()
            if self.hard_suffix is not None:
                ext = self.hard_suffix

            df = None

            if ext == ".csv":
                csv_to_parquet_stream(
                    source_path,
                    target_path,
                    sep=self.csv_separator,
                    encoding=self.default_encoding,
                    has_header=self.csv_has_header,
                    headers=self.csv_header,
                )
                return str(target_path)

            elif ext == ".json":
                try:
                    df = pl.read_json(source_path)
                except Exception:
                    df = pl.read_ndjson(source_path)

            elif ext == ".xml":
                df = pl.from_pandas(pd.read_xml(source_path))

            if df is None or df.height == 0:
                return None

            df.write_parquet(target_path, compression="snappy")
            return str(target_path)

        except Exception as e:
            print(f"Erro ao converter {source_path.name}: {e}")
            return None

    def _run_execution_pool(
        self, target_sources: List[str], ext: str
    ) -> Tuple[List[str], List[DownloaderError], List[str]]:
        new_parquet_files = []
        errors: List[DownloaderError] = []
        failed_urls: List[str] = []

        try:
            with ThreadPoolExecutor(max_workers=self.concurrent_downloads) as executor:
                future_to_url = {
                    executor.submit(self.download_and_process, src, ext): src
                    for src in target_sources
                }
                for i, future in enumerate(as_completed(future_to_url)):
                    src_url = future_to_url[future]
                    try:
                        parquets, err = future.result()
                        if err:
                            errors.append(err)
                            failed_urls.append(src_url)
                            logger.error("Download failed for %s: %s", src_url, err)
                        else:
                            new_parquet_files.extend(parquets)
                    except Exception as e:
                        errors.append(DownloaderError(src_url, str(e), e))
                        failed_urls.append(src_url)
                        logger.exception("Download failed for %s", src_url)

                    if (i + 1) % self.concurrent_downloads == 0:
                        self._apply_rate_limit()
        finally:
            self._close_playwright_driver()

        return new_parquet_files, errors, failed_urls

    def download_from_sources(
        self,
        ext: str,
        content_type: str,
        sources_override: Optional[List[str]] = None,
        is_retry: bool = False,
    ) -> Tuple[List[str], List[DownloaderError]]:

        target_sources = (
            sources_override if sources_override is not None else self._resolve_sources()
        )
        old_meta = self.get_meta()

        if self.download_callback is not None:
            return self._download_from_callback(self._resolve_sources(), ext, old_meta)

        if not is_retry and old_meta and old_meta.files:
            for old_file_path_str in old_meta.files:
                old_file = Path(old_file_path_str)
                try:
                    if old_file.is_dir() and self.keep_raw:
                        target_root = (BASE_DIR / "downloads" / self.files_path).resolve()
                        if old_file.resolve().parent != target_root:
                            raise ValueError(f"Diretório fora da pasta de downloads: {old_file}")

                        shutil.rmtree(old_file)
                    else:
                        old_file.unlink(missing_ok=True)
                except Exception as e:
                    print(f"Aviso: Falha ao limpar arquivo antigo {old_file}: {e}")

        # Executa o pool (o driver_mode selecionado cuidará de httpx ou playwright em cada worker)
        new_parquet_files, errors, failed_urls = self._run_execution_pool(
            target_sources, ext
        )

        combined_parquet_files = list(new_parquet_files)
        if is_retry and old_meta:
            combined_parquet_files.extend(old_meta.files)

        is_successful = len(failed_urls) == 0

        meta = DownloaderMeta(
            downloaded_at=datetime.now(),
            files=combined_parquet_files,
            failed_sources=failed_urls,
            successful=is_successful,
        )
        self.create_meta(meta)

        return combined_parquet_files, errors

    def _download_from_callback(
        self,
        sources: List[str],
        ext: str,
        old_meta: DownloaderMeta | None,
    ) -> Tuple[List[str], List[DownloaderError]]:
        files, errors, failed_sources = self._run_execution_pool(sources, ext)

        if errors:
            # Keep the published cache available until every callback succeeds.
            for file in files:
                Path(file).unlink(missing_ok=True)

            files = list(old_meta.files) if old_meta else []
        elif old_meta:
            for old_file in old_meta.files:
                if old_file not in files:
                    Path(old_file).unlink(missing_ok=True)

        self.create_meta(DownloaderMeta(
            downloaded_at=datetime.now(),
            files=files,
            failed_sources=failed_sources,
            successful=not errors,
        ))

        return files, errors

    def _get_playwright_driver(self) -> "_PlaywrightDriver":
        with self._playwright_driver_lock:
            if self._playwright_driver is None:
                logger.info(
                    "Starting Playwright Chromium for %s (headless=%s)",
                    self.meta_name,
                    self.playwright_headless,
                )

                self._playwright_driver = _PlaywrightDriver(
                    headless=self.playwright_headless,
                    warmup_url=self.playwright_warmup_url,
                )
        return self._playwright_driver

    def _close_playwright_driver(self):
        with self._playwright_driver_lock:
            if self._playwright_driver is not None:
                self._playwright_driver.close()
                self._playwright_driver = None

    def _download_via_playwright(self, source: str, target_file: Path):
        driver = self._get_playwright_driver()
        driver.download(
            source,
            target_file,
            goto_timeout_ms=self.playwright_goto_timeout_ms,
            download_timeout_ms=self.playwright_download_timeout_ms,
        )

    def _download_via_httpx(self, source: str, target_file: Path):
        with self.http_client.stream("GET", source) as response:
            response.raise_for_status()

            with target_file.open("wb") as output:
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    output.write(chunk)

    def download_and_process(
        self, source: str, ext: str
    ) -> Tuple[List[str], Optional[DownloaderError]]:
        temp_dir = BASE_DIR / "downloads" / "temp" / uuid.uuid4().hex[:8]
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            downloaded_file = temp_dir / f"raw.{ext}"

            if self.download_callback is not None:
                self.download_callback(self, source, downloaded_file)
                if not downloaded_file.is_file():
                    raise FileNotFoundError("Download callback did not produce its target file")
            elif self.driver_mode == "playwright":
                self._download_via_playwright(source, downloaded_file)
            else:
                self._download_via_httpx(source, downloaded_file)

            parquets_generated = []
            if ext == "zip":
                if self.keep_zip or self.keep_raw:
                    filename = Path(unquote(urlsplit(source).path)).name
                    if not filename.lower().endswith(".zip"):
                        filename = "archive.zip"

                    source_id = hashlib.sha256(source.encode()).hexdigest()[:8]
                    target_root = BASE_DIR / "downloads" / self.files_path
                    target_root.mkdir(parents=True, exist_ok=True)

                if self.keep_zip and not self.keep_raw:
                    if not zipfile.is_zipfile(downloaded_file):
                        raise zipfile.BadZipFile(f"Arquivo ZIP inválido: {source}")

                    target_zip = target_root / f"{source_id}_{filename}"
                    shutil.move(downloaded_file, target_zip)

                    return [str(target_zip)], None

                extract_path = temp_dir / "extracted"
                with zipfile.ZipFile(downloaded_file, "r") as z:
                    z.extractall(extract_path)

                if self.keep_raw:
                    archive_name = Path(filename).stem
                    target_dir = target_root / f"{archive_name}_{source_id}_{uuid.uuid4().hex[:8]}"
                    shutil.move(extract_path, target_dir)

                    saved_files = [str(target_dir)]
                    if self.keep_zip:
                        target_zip = target_root / f"{source_id}_{filename}"
                        shutil.move(downloaded_file, target_zip)
                        saved_files.append(str(target_zip))

                    return saved_files, None

                for f in extract_path.rglob("*"):
                    if self.hard_suffix is not None:
                        p = self._convert_to_parquet(f)
                        if p:
                            parquets_generated.append(p)
                        continue

                    if f.is_file() and f.suffix.lower() in [".json", ".csv", ".xml"]:
                        p = self._convert_to_parquet(f)
                        if p:
                            parquets_generated.append(p)
            else:
                if self.keep_raw:
                    filename = Path(unquote(urlsplit(source).path)).name or f"raw.{ext}"
                    source_id = hashlib.sha256(source.encode()).hexdigest()[:8]
                    target_dir = BASE_DIR / "downloads" / self.files_path
                    target_dir.mkdir(parents=True, exist_ok=True)

                    target_file = target_dir / f"{source_id}_{filename}"
                    shutil.move(downloaded_file, target_file)

                    return [str(target_file)], None

                p = self._convert_to_parquet(downloaded_file)
                if p:
                    parquets_generated.append(p)

            if self.download_callback is not None and not parquets_generated:
                raise ValueError("Download callback produced no usable records")

            return parquets_generated, None
        except Exception as e:
            return [], DownloaderError(source, str(e), e)
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)

    def _apply_rate_limit(self):
        with self.lock:
            now = datetime.now()
            diff = (now - self.last_downloads).total_seconds()
            if diff < self.limiter_throttle_time:
                time.sleep(self.limiter_throttle_time - diff)
            self.last_downloads = datetime.now()
