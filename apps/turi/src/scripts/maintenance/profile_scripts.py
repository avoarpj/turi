"""Profile producers sequentially against local inputs without publishing dumps.

Run with uv run python apps/turi/src/scripts/maintenance/profile_scripts.py.
Memory samples and producer logs stay beside the JSON report.
"""
import argparse
from datetime import UTC, datetime
import importlib
import hashlib
import json
import logging
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import sys
from tempfile import mkdtemp
import time
import traceback

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'apps/turi/src'))


def worker(script_id: str, directory: Path) -> None:
    from infra.datascript.discovery import discover_scripts
    import pyarrow.parquet as pq

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    scripts = discover_scripts()
    script = scripts[script_id]
    module = importlib.import_module(type(script).__module__)
    module_path = Path(module.__file__)
    outputs = {p: directory / 'outputs' / p.relative_to(ROOT / 'parquet_dumps') for p in script.output_paths}
    input_root = os.getenv('TURI_PROFILE_INPUTS')
    overrides = {}
    redirected = set()

    for name, value in list(vars(module).items()):
        if isinstance(value, Path) and value in outputs:
            setattr(module, name, outputs[value])
            redirected.add(value)
        elif isinstance(value, Path) and input_root and value.is_relative_to(ROOT / 'downloads'):
            alternative = Path(input_root).resolve() / value.relative_to(ROOT / 'downloads')
            if alternative.exists() or ('*' in alternative.name and alternative.parent.exists()):
                setattr(module, name, alternative)
                overrides[name] = str(alternative)

    if redirected != set(outputs):
        raise ValueError(f'Cannot redirect every output for {script_id}')

    script.output_paths = list(outputs.values())

    if script_id == 'camaradosdeputados_mandate_office' and overrides:
        module.files = [str(p) for p in module.CD_MANDATE_OFFICE_RAW_PARQUETS.parent.glob('*.parquet')]

    for path in outputs.values():
        path.parent.mkdir(parents=True, exist_ok=True)

    if script_id == 'candidatures':
        from unittest.mock import patch

        publish_photos = module._publish_candidature_photos

        def plan_photos(photo_keys, source_root, target_root, logger):
            diagnostic_target = directory / 'assets'

            def simulate_move(source, destination):
                destination = Path(destination)
                if not source.is_relative_to(source_root) or not destination.is_relative_to(diagnostic_target):
                    raise ValueError('Unexpected photo move during profiling')
                return destination

            logger.info('Profiling photo selection with simulated file moves')
            with patch.object(Path, 'replace', simulate_move):
                publish_photos(photo_keys, source_root, diagnostic_target, logger)

        module._publish_candidature_photos = plan_photos

    def offline(event, args):
        if event in ('socket.connect', 'socket.getaddrinfo'):
            raise RuntimeError('Network disabled during profiling')

    sys.addaudithook(offline)
    started = time.monotonic()
    result = {
        'input_overrides': overrides,
        'producer_sha256': hashlib.sha256(module_path.read_bytes()).hexdigest(),
    }

    try:
        script.process_data(logging.getLogger(script_id))
        result['status'] = 'ok'
        result['outputs'] = [
            {'path': str(old.relative_to(ROOT)), 'rows': pq.read_metadata(new).num_rows,
             'bytes': new.stat().st_size, 'schema': str(pq.read_schema(new))}
            for old, new in outputs.items()
        ]
    except BaseException as exc:
        result.update(status='error', error=f'{type(exc).__name__}: {exc}')
        traceback.print_exc()
    finally:
        result.update(process_seconds=time.monotonic() - started,
                      peak_rss_kernel_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)
        (directory / 'result.json').write_text(json.dumps(result, indent=2))


def sample(pid: int) -> dict[str, int]:
    try:
        values = dict(line.split(':', 1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
        usage = {
            k: int(values.get(k, '0 kB').split()[0]) * 1024
            for k in ('VmRSS', 'VmHWM', 'VmSwap', 'RssAnon', 'RssFile', 'RssShmem')
        }
        rollup = dict(
            line.split(':', 1) for line in Path(f'/proc/{pid}/smaps_rollup').read_text().splitlines()
            if ':' in line
        )
        usage.update({
            k: int(rollup.get(k, '0 kB').split()[0]) * 1024 for k in ('Pss', 'LazyFree')
        })
        return usage
    except (FileNotFoundError, ProcessLookupError):
        return dict.fromkeys(('VmRSS', 'VmHWM', 'VmSwap', 'RssAnon', 'RssFile', 'RssShmem', 'Pss', 'LazyFree'), 0)


def sample_tree(pid: int) -> dict[str, int]:
    pending = [pid]
    descendants = []

    while pending:
        parent = pending.pop()
        try:
            children = Path(f'/proc/{parent}/task/{parent}/children').read_text().split()
        except (FileNotFoundError, ProcessLookupError):
            continue

        for child in children:
            child_pid = int(child)
            descendants.append(child_pid)
            pending.append(child_pid)

    usage = sample(pid)
    for child in descendants:
        child_usage = sample(child)
        for key in ('VmRSS', 'VmSwap', 'RssAnon', 'RssFile', 'RssShmem', 'Pss', 'LazyFree'):
            usage[key] += child_usage[key]

    # A child's HWM need not coincide with the parent's HWM. Sum only live RSS.
    return usage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ids', nargs='*')
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--input-root', type=Path,
                        help='Optional staged download tree, relative to downloads/')
    parser.add_argument('--unique-root', type=Path,
                        help='Optional disk scratch directory for deduplication and external sorting')
    parser.add_argument('--worker', help=argparse.SUPPRESS)
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)

    if args.worker:
        worker(args.worker, directory)
        return

    from infra.datascript.discovery import discover_scripts, resolve_scripts
    scripts = discover_scripts()
    ids = args.ids or [s.script_id for s in resolve_scripts(scripts)]

    for script_id in ids:
        if script_id not in scripts:
            parser.error(f'Unknown script_id: {script_id}')
    originals = {p: (p.stat().st_size, p.stat().st_mtime_ns) if p.exists() else None
                 for s in scripts.values() for p in s.output_paths}
    metadata = ROOT / 'apps/turi/src/scripts/__metadata__'
    originals.update({p: (p.stat().st_size, p.stat().st_mtime_ns) for p in metadata.glob('*.json')})
    report = {'started_at': datetime.now(UTC).isoformat(), 'sample_seconds': 0.1,
              'polars_max_threads': os.getenv('POLARS_MAX_THREADS'),
              'input_root': str(args.input_root.resolve()) if args.input_root else None,
              'unique_root': str(args.unique_root.resolve()) if args.unique_root else None,
              'scope': 'process_data only; existing published dependencies; no checkpoint, bloom or Venato; photo moves simulated',
              'memory_scope': 'worker plus live descendant processes; RSS sums may include shared pages',
              'results': []}
    report_path = directory / 'report.json'

    if report_path.exists():
        report = json.loads(report_path.read_text())
        completed = {r['script_id'] for r in report['results']}
        ids = [script_id for script_id in ids if script_id not in completed]

    for script_id in ids:
        work = directory / script_id
        work.mkdir(exist_ok=True)
        (work / 'result.json').unlink(missing_ok=True)

        unique_directory = work / 'unique'
        if args.unique_root:
            args.unique_root.mkdir(parents=True, exist_ok=True)
            unique_directory = Path(mkdtemp(prefix=f'{script_id}-', dir=args.unique_root.resolve()))

        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
                           TURI_UNIQUE_TEMP_DIRECTORY=str(unique_directory))
        if args.input_root:
            environment['TURI_PROFILE_INPUTS'] = str(args.input_root.resolve())
        log = work / 'process.log'
        started = time.monotonic()
        peak_rss = peak_swap = peak_total = 0
        peak_anon = peak_file = 0
        peak_pss = peak_lazy_free = 0
        minimum_available = None
        initial_available = None
        last_progress = started
        interrupted = False
        print('START', script_id, flush=True)

        with log.open('w') as output, (work / 'memory.csv').open('w') as samples:
            samples.write('seconds,rss_bytes,swap_bytes,system_available_bytes,rss_anon_bytes,rss_file_bytes,pss_bytes,lazy_free_bytes\n')
            process = subprocess.Popen([sys.executable, __file__, '--worker', script_id,
                                        '--directory', str(work)], stdout=output, stderr=subprocess.STDOUT,
                                       env=environment, start_new_session=True)

            try:
                while process.poll() is None:
                    usage = sample_tree(process.pid)
                    peak_rss = max(peak_rss, usage['VmRSS'], usage['VmHWM'])
                    peak_swap = max(peak_swap, usage['VmSwap'])
                    peak_total = max(peak_total, usage['VmRSS'] + usage['VmSwap'])
                    peak_anon = max(peak_anon, usage['RssAnon'])
                    peak_file = max(peak_file, usage['RssFile'])
                    peak_pss = max(peak_pss, usage['Pss'])
                    peak_lazy_free = max(peak_lazy_free, usage['LazyFree'])
                    memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
                    available = int(memory['MemAvailable'].split()[0]) * 1024
                    if initial_available is None:
                        initial_available = available
                    minimum_available = (
                        available if minimum_available is None
                        else min(minimum_available, available)
                    )
                    samples.write(
                        f'{time.monotonic()-started:.3f},{usage["VmRSS"]},{usage["VmSwap"]},{available},'
                        f'{usage["RssAnon"]},{usage["RssFile"]},{usage["Pss"]},{usage["LazyFree"]}\n'
                    )
                    samples.flush()

                    if time.monotonic() - last_progress >= 30:
                        print(
                            'MEMORY', script_id,
                            f'RSS={usage["VmRSS"] / 1024**2:.1f}MiB',
                            f'PSS={usage["Pss"] / 1024**2:.1f}MiB',
                            f'swap={usage["VmSwap"] / 1024**2:.1f}MiB',
                            f'available={available / 1024**2:.1f}MiB',
                            flush=True,
                        )
                        last_progress = time.monotonic()

                    if (directory / 'stop-current').exists():
                        (directory / 'stop-current').unlink()
                        interrupted = True
                        os.killpg(process.pid, signal.SIGINT)
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                        break

                    time.sleep(0.1)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()

        result_file = work / 'result.json'
        result = json.loads(result_file.read_text()) if result_file.exists() else {'status': 'killed'}
        result.setdefault('status', 'interrupted' if interrupted else 'error')
        if interrupted:
            result['status'] = 'interrupted'
        result.update(script_id=script_id, peak_rss_bytes=max(peak_rss, result.get('peak_rss_kernel_bytes', 0)),
                      peak_swap_bytes=peak_swap, peak_rss_plus_swap_bytes=peak_total,
                      peak_rss_anon_bytes=peak_anon, peak_rss_file_bytes=peak_file,
                      peak_pss_bytes=peak_pss, peak_lazy_free_bytes=peak_lazy_free,
                      initial_system_available_bytes=initial_available,
                      minimum_system_available_bytes=minimum_available,
                      wall_seconds=time.monotonic()-started, returncode=process.returncode,
                      interrupted_by_operator=interrupted)
        report['results'].append(result)
        report['original_outputs_and_checkpoints_unchanged'] = all(
            ((p.stat().st_size, p.stat().st_mtime_ns) if p.exists() else None) == previous
            for p, previous in originals.items()
        )
        report_path.write_text(json.dumps(report, indent=2))
        print('DONE', script_id, result['status'], f'RSS={result["peak_rss_bytes"]/1024**2:.1f}MiB',
              f'swap={peak_swap/1024**2:.1f}MiB', f'{result["wall_seconds"]:.1f}s', flush=True)
        shutil.rmtree(work / 'outputs', ignore_errors=True)
        shutil.rmtree(unique_directory, ignore_errors=True)

        if not report['original_outputs_and_checkpoints_unchanged']:
            raise RuntimeError('Published files changed during profiling')

    report['finished_at'] = datetime.now(UTC).isoformat()
    report_path.write_text(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
