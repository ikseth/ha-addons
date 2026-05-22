#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

WORKER_PATH = Path('/opt/ha4linux/update/ha4linux-update-rollback-worker.py')
TRANSIENT_SYSTEMD_ERRORS = (
    'Connection reset by peer',
    'Connection timed out',
    'Failed to start transient service unit',
    'Transport endpoint is not connected',
)


def require_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit('This command must run as root')


def run_systemd_worker(systemd_run: str, unit_name: str, *, pipe: bool) -> subprocess.CompletedProcess[str]:
    command = [
        systemd_run,
        f'--unit={unit_name}',
        '--wait',
        '--collect',
        '--property=Type=oneshot',
        '--description=HA4Linux remote update rollback',
        str(WORKER_PATH),
    ]
    if pipe:
        command.insert(3, '--pipe')

    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )


def is_transient_systemd_error(completed: subprocess.CompletedProcess[str]) -> bool:
    output = f'{completed.stderr}\n{completed.stdout}'
    return any(token in output for token in TRANSIENT_SYSTEMD_ERRORS)


def run_with_retries(systemd_run: str) -> subprocess.CompletedProcess[str]:
    attempts: list[tuple[bool, float]] = [
        (True, 0.0),
        (True, 1.0),
        (True, 3.0),
        (False, 1.0),
        (False, 3.0),
    ]
    last_result: subprocess.CompletedProcess[str] | None = None

    for index, (use_pipe, delay) in enumerate(attempts, start=1):
        if delay:
            time.sleep(delay)
        unit_name = f'ha4linux-update-rollback-{int(time.time())}-{os.getpid()}-{index}'
        completed = run_systemd_worker(systemd_run, unit_name, pipe=use_pipe)
        if completed.returncode == 0:
            return completed

        last_result = completed
        if not is_transient_systemd_error(completed):
            return completed

        sys.stderr.write(
            'systemd-run transient failure; retrying '
            f'(attempt {index}/{len(attempts)}, pipe={use_pipe})\n'
        )

    return last_result if last_result is not None else run_systemd_worker(
        systemd_run,
        f'ha4linux-update-rollback-{int(time.time())}-{os.getpid()}-final',
        pipe=False,
    )


def main() -> None:
    require_root()

    if not WORKER_PATH.exists():
        raise SystemExit(f'rollback worker not found: {WORKER_PATH}')

    systemd_run = shutil.which('systemd-run')
    if not systemd_run:
        raise SystemExit('systemd-run command not available')

    completed = run_with_retries(systemd_run)

    if completed.stdout:
        sys.stdout.write(completed.stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)

    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or f'rollback worker failed ({completed.returncode})'
        raise SystemExit(message)


if __name__ == '__main__':
    main()
