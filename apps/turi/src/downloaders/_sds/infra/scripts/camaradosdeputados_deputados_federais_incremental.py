from datetime import datetime

import aiohttp

from apps.turi.src.downloaders._sds.core.dataset_meta.dataset import DatasetMeta
from apps.turi.src.downloaders._sds.infra.BulkDownloader import BulkDownloader
from apps.turi.src.downloaders._sds.infra.scripts.camaradosdeputados_deputados_federais import _onDownload, _update_deputies

MAX_SIZE = 256
FTAG_MAX_AGE = 259200.0 # in seconds

_downloader = BulkDownloader(
    rate=2,
    concurrency=2,
    retry_base_delay=1,
    retry_max_delay=480,
    connector_kwargs=dict(
        limit=2,
        keepalive_timeout=4,
        ttl_dns_cache=300,
        force_close=False
    ),
    timeout_kwargs=dict(
        total=120,
        connect=30,
        sock_read=60
    ),
    task_delay=30,
    task_jitter=1800,
    callback=_onDownload
)

"""
Aqui é necessário um jitter alto para pulverizar as requests para momentos diferentes, pois rajadas mínimas sobrecarregam o endpoint da Câmara.
"""

async def Callback(dataset: DatasetMeta) -> None:
    current_legislature = await _get_last_legislature()
    await _update_deputies(
        dataset,
        _downloader,
        current_legislature=current_legislature,
        max_size=MAX_SIZE,
        ftag_max_age=FTAG_MAX_AGE,
    )


async def _get_legislatures():
    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://dadosabertos.camara.leg.br/api/v2/legislaturas",
            params={"data": datetime.now().date().isoformat(), "ordem": "DESC", "ordenarPor": "id"},
            headers={**_downloader.headers, "Accept": "application/json"},
        ) as res:
            res.raise_for_status()
            return await res.json()


async def _get_last_legislature() -> int:
    legislatures = await _get_legislatures()
    # Filtrar pela data evita selecionar uma legislatura futura já cadastrada.
    return legislatures["dados"][0]["id"]
