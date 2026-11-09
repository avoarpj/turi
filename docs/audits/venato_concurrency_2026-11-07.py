"""Read-only, bounded audit of the local Venato indexes and real Fons ASGI app.

Run from the repository root with PYTHONPATH=apps/fons:. and uv run --no-sync.
Each invocation is a separate process so its RSS high-water mark is independent.
This is a diagnostic sample, not an HTTP capacity or production load test.
"""
import argparse
import asyncio
import ctypes
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import statistics
import sys
import time


def memory():
    return {"max_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024}


def describe(values):
    ordered = sorted(values)

    return {
        "samples": len(values),
        "median_ms": statistics.median(values) * 1000 if values else None,
        "max_ms": ordered[-1] * 1000 if values else None,
    }


def venato():
    from avoar.infra.venato.core import Venato, VenatoConfig
    from avoar.projectsettings.globals import VENATO_DATA_DIR

    instance = Venato(VenatoConfig(VENATO_DATA_DIR))
    instance.load_index("opendata_public_people")

    return instance


def census():
    from tantivy import Index
    from avoar.projectsettings.globals import VENATO_DATA_DIR

    rows = []

    for path in sorted((VENATO_DATA_DIR / "indexes").iterdir()):
        if not path.is_dir():
            continue

        index = Index.open(str(path))
        searcher = index.searcher()
        fields, terms = {
            "opendata_public_people": (["nome"], ["Silva", "*"]),
            "opendata_business": (["razao_social"], ["Petrobras", "comercio", "*"]),
            "opendata_business_establishment": (["nome_fantasia"], ["Petrobras", "comercio", "*"]),
            "opendata_address": (["endereco_completo"], ["*"]),
        }[path.name]
        queries = []

        for term in terms:
            started = time.perf_counter()
            result = searcher.search(index.parse_query(term, fields), limit=20, count=True)
            queries.append({
                "query": term,
                "matches": result.count,
                "top20_and_count_ms": (time.perf_counter() - started) * 1000,
            })

        rows.append({
            "index": path.name,
            "documents": searcher.num_docs,
            "segments": searcher.num_segments,
            "allocated_mib": sum(p.stat().st_blocks * 512 for p in path.rglob("*") if p.is_file()) / 2**20,
            "queries": queries,
        })

    return {"indexes": rows, **memory()}


def stages(term, repeats):
    instance = venato()
    index = instance._indexes["opendata_public_people"]
    measurements = []

    for _ in range(repeats):
        started = time.perf_counter()
        declaration = instance.read_index_declaration(
            Path("avoar/infra/venato/indexes/opendata_public_people.yaml")
        )
        unsigned = [c.name for c in declaration.columns if c.stored and c.type == "u64"]
        query = index.parse_query(term, ["nome"])
        searcher = index.searcher()
        prepared = time.perf_counter()

        result = searcher.search(query, limit=searcher.num_docs, count=False)
        searched = time.perf_counter()
        hits = result.hits
        converted = time.perf_counter()
        ids = []

        for _, address in hits:
            document = searcher.doc(address).to_dict()

            for field in unsigned:
                if field in document:
                    document[field] = [ctypes.c_uint64(value).value for value in document[field]]

            ids.extend(document.get("id", []))

        finished = time.perf_counter()
        measurements.append({
            "matches": len(ids),
            "prepare_ms": (prepared - started) * 1000,
            "native_search_ms": (searched - prepared) * 1000,
            "hits_to_python_ms": (converted - searched) * 1000,
            "stored_docs_and_ids_ms": (finished - converted) * 1000,
            "total_ms": (finished - started) * 1000,
        })

        # Match the lifetime of a request: do not retain a prior full hit list.
        del result, hits, ids

    return {"query": term, "measurements": measurements, **memory()}


async def api(term, concurrency, repeats, search_slots):
    # Set before importing the app: no Redis writes and no warmup of large tables.
    os.environ["REDIS_URL"] = ""
    os.environ["DATAFUSION_WARMUP_ENABLED"] = "false"
    os.environ["DATAFUSION_MEMORY_LIMIT"] = "512MiB"
    os.environ["DATAFUSION_TARGET_PARTITIONS"] = "2"

    import httpx
    from apps.fons.main import app

    async def heartbeat(lags, stop):
        # Same wakeup workaround documented in development_notes.md, also
        # measuring loop delay. Shared by baseline and loaded samples.
        while not stop.is_set():
            expected = time.perf_counter() + .01
            await asyncio.sleep(.01)
            lags.append(max(0, time.perf_counter() - expected))

    loop_lags = []
    startup_stop = asyncio.Event()
    startup_tick = asyncio.create_task(heartbeat(loop_lags, startup_stop))

    try:
        async with app.lifespan():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://audit",
            ) as client:
                # Real dependency assembly, real Parquets and actual Venato.
                service = app.state.fons_services["public_people"]["queryservice"]
                instance = service._venato
                instance.load_index("opendata_public_people")

                if search_slots:
                    # Audit-only admission experiment; production code is untouched.
                    original_search = service.search
                    gate = asyncio.Semaphore(search_slots)

                    async def bounded_search(*args, **kwargs):
                        async with gate:
                            return await original_search(*args, **kwargs)

                    service.search = bounded_search

                async def request(path, params=None):
                    started = time.perf_counter()
                    response = await client.get(path, params=params)
                    elapsed = time.perf_counter() - started
                    response.raise_for_status()

                    return elapsed, len(response.json())

                for _ in range(3):
                    await request("/opendata/organ/")

                baseline = []

                for _ in range(25):
                    elapsed, _ = await request("/opendata/organ/")
                    baseline.append(elapsed)
                    await asyncio.sleep(.02)

                rounds = []

                for _ in range(repeats):
                    probes = []
                    loop_lags.clear()
                    started = time.perf_counter()
                    jobs = [asyncio.create_task(request(
                        "/opendata/public_people/search",
                        {"input": term, "limit": 20, "pull_by": "relevance"},
                    )) for _ in range(concurrency)]

                    while not all(job.done() for job in jobs):
                        elapsed, _ = await request("/opendata/organ/")
                        probes.append(elapsed)
                        await asyncio.sleep(.02)

                    searches = await asyncio.gather(*jobs)
                    elapsed = time.perf_counter() - started
                    rounds.append({
                        "wall_seconds": elapsed,
                        "completed_searches_per_second": concurrency / elapsed,
                        "search_ms": [duration * 1000 for duration, _ in searches],
                        "search_rows": [count for _, count in searches],
                        "organ_during_search": describe(probes),
                        "loop_lag": describe(loop_lags),
                    })

                return {
                    "query": term,
                    "concurrency": concurrency,
                    "transport": "in-process ASGITransport; real app lifespan and dependencies",
                    "redis": "disabled",
                    "datafusion_memory": "512MiB",
                    "datafusion_partitions": 2,
                    "anyio_tokens": 650,
                    "audit_search_slots": search_slots or "unmodified",
                    "organ_baseline": describe(baseline),
                    "rounds": rounds,
                    **memory(),
                }
    finally:
        startup_stop.set()
        await startup_tick


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["census", "stages", "api"])
    parser.add_argument("--query", default="*")
    parser.add_argument("--concurrency", type=int, choices=range(1, 9), default=1)
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--search-slots", type=int, choices=range(0, 9), default=0)
    args = parser.parse_args()

    if args.mode == "census":
        result = census()
    elif args.mode == "stages":
        result = stages(args.query, args.repeats)
    else:
        result = asyncio.run(api(args.query, args.concurrency, args.repeats, args.search_slots))

    result["environment"] = {
        "python": sys.version,
        "gil_enabled": sys._is_gil_enabled(),
        "logical_cpus": os.cpu_count(),
        "versions": {p: importlib.metadata.version(p) for p in (
            "tantivy", "anyio", "litestar", "datafusion", "httpx",
        )},
    }
    print(json.dumps(result, indent=2))
