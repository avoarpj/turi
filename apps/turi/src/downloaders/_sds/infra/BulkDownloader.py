import asyncio
import aiohttp
import time
import random
import aiofiles
from pathlib import Path
from pydantic import BaseModel


class Item(BaseModel):
    url: str
    path: Path


class BulkDownloader:
    def __init__(
        self,
        rate: int,
        concurrency: int = 5,
        callback=None,
        retry_base_delay: int = 1,
        retry_max_delay: int = 3600,
        timeout_kwargs: dict | None = None,
        connector_kwargs: dict | None = None,
        headers: dict | None = None,
        task_delay: float | None = None,
        task_jitter: float | None = None,
    ):
        self.rate = rate
        self.interval = 1 / rate
        self.concurrency = concurrency
        self.callback = callback

        self._last = 0.0
        self._rate_lock = asyncio.Lock()

        self._session: aiohttp.ClientSession | None = None
        self._session_lock = asyncio.Lock()

        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay

        self._timeout_kwargs = timeout_kwargs or {}
        self._connector_kwargs = connector_kwargs or {}
        self.headers = headers or {}

        self.task_delay = task_delay
        self.task_jitter = task_jitter

        self.headers["User-Agent"] = "Avoar SDS (https://github.com/avoarpj/simple-data-service)"

    async def _rate_limit(self):
        async with self._rate_lock:
            now = time.monotonic()
            delta = now - self._last

            if delta < self.interval:
                await asyncio.sleep(self.interval - delta)

            self._last = time.monotonic()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session and not self._session.closed:
            return self._session

        async with self._session_lock:
            if self._session and not self._session.closed:
                return self._session

            timeout = aiohttp.ClientTimeout(**self._timeout_kwargs)
            connector = aiohttp.TCPConnector(**self._connector_kwargs)

            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector
            )
            return self._session

    async def _stagger(self):
        if self.task_delay is None:
            return

        delay = self.task_delay
        if self.task_jitter:
            delay += random.uniform(0, self.task_jitter)

        await asyncio.sleep(delay)

    async def _worker(self, queue: asyncio.Queue):
        while True:
            item = await queue.get()
            try:
                await self._process_item(item)
            finally:
                queue.task_done()

    async def _process_item(self, item: Item):
        await self._stagger()
        attempt = 0

        while True:
            try:
                await self._rate_limit()
                session = await self._get_session()
                
                item.path.parent.mkdir(parents=True, exist_ok=True)

                async with session.get(item.url, headers=self.headers) as resp:
                    resp.raise_for_status()

                    async with aiofiles.open(item.path.with_suffix(item.path.suffix + ".part"), mode="wb") as f:
                        async for chunk in resp.content.iter_chunked(8192):
                            await f.write(chunk)

                item.path.with_suffix(item.path.suffix + ".part").replace(item.path)

                if self.callback:
                    self.callback(item)
                return

            except aiohttp.ClientResponseError as e:
                if e.status == 404:
                    print(f"[404 NOT FOUND] Pulando: {item.url}")
                    return 
                
                attempt += 1
                delay = min(self.retry_base_delay * (2 ** (attempt - 1)), self.retry_max_delay)
                delay *= 0.9 + (0.2 * random.random())
                await asyncio.sleep(delay)

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                attempt += 1
                delay = min(self.retry_base_delay * (2 ** (attempt - 1)), self.retry_max_delay)
                delay *= 0.9 + (0.2 * random.random())
                print(f"[RETRY CONNECTION] {item.url} - Tentativa {attempt}")
                await asyncio.sleep(delay)
            
            except Exception as e:
                self._errors.append(e)
                return

    async def download_all(self, items: list[Item], timeout: float | None = None):
        # Callbacks may invoke the same downloader in successive asyncio.run loops.
        self._rate_lock = asyncio.Lock()
        self._session_lock = asyncio.Lock()
        self._errors = []
        queue = asyncio.Queue()
        for item in items:
            await queue.put(item)

        workers = [asyncio.create_task(self._worker(queue)) for _ in range(self.concurrency)]

        try:
            await asyncio.wait_for(queue.join(), timeout=timeout)
            if self._errors:
                raise RuntimeError("SDS bulk download failed") from self._errors[0]
        except asyncio.TimeoutError:
            print(f"\n[!] Timeout de {timeout}s atingido. Cancelando tarefas pendentes...")
            raise TimeoutError(f"Bulk download exceeded timeout of {timeout}s")
        finally:
            for w in workers:
                w.cancel()
            
            await asyncio.gather(*workers, return_exceptions=True)

            if self._session and not self._session.closed:
                await self._session.close()