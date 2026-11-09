"""Supervise owned subprocesses using resident plus swapped memory."""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import signal
import subprocess
from time import monotonic, sleep

import psutil


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessResources:
    peak_rss: int
    peak_swap: int
    seconds: float


def _memory_usage(pid: int) -> tuple[int, int]:
    process = psutil.Process(pid)
    processes = [process, *process.children(recursive=True)]
    rss = 0
    swap = 0

    for child in processes:
        try:
            info = child.memory_full_info()
            rss += info.rss
            swap += info.swap
        except psutil.NoSuchProcess:
            continue

    return rss, swap


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return

    try:
        os.killpg(process.pid, signal.SIGINT)
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
    except ProcessLookupError:
        process.wait()


def run_guarded(
    command: Sequence[str],
    *,
    max_memory: int,
    max_swap: int,
    timeout: float | None = None,
    env: Mapping[str, str] | None = None,
    work_directory: Path | None = None,
    min_free_disk: int = 4 * 1024**3,
) -> ProcessResources:
    if max_memory <= 0 or max_swap < 0:
        raise ValueError("Memory limit must be positive and swap limit nonnegative")

    process = subprocess.Popen(command, env=env, start_new_session=True)
    started = monotonic()
    last_log = started
    peak_rss = 0
    peak_swap = 0

    try:
        while process.poll() is None:
            try:
                rss, swap = _memory_usage(process.pid)
            except psutil.NoSuchProcess:
                continue

            peak_rss = max(peak_rss, rss)
            peak_swap = max(peak_swap, swap)

            if rss + swap > max_memory or swap > max_swap:
                raise MemoryError(
                    f"Turi memory limit exceeded: RSS={rss / 1024**2:.1f} MiB, "
                    f"swap={swap / 1024**2:.1f} MiB; "
                    f"limits total={max_memory / 1024**2:.1f} MiB, "
                    f"swap={max_swap / 1024**2:.1f} MiB"
                )
            if timeout is not None and monotonic() - started > timeout:
                raise TimeoutError(f"Turi subprocess exceeded {timeout} seconds")
            if work_directory is not None and psutil.disk_usage(work_directory).free < min_free_disk:
                raise OSError("Turi stopped: less than the required free disk space remains")

            if monotonic() - last_log >= 30:
                logger.info(
                    "Turi resources: RSS=%.1f MiB swap=%.1f MiB",
                    rss / 1024**2, swap / 1024**2,
                )
                last_log = monotonic()

            sleep(0.1)

        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)

        return ProcessResources(peak_rss, peak_swap, monotonic() - started)
    finally:
        _stop(process)
