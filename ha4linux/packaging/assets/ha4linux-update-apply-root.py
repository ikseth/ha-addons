#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REQUEST_FILE = Path('/var/lib/ha4linux/update-request.json')
WORKER_PATH = Path('/opt/ha4linux/update/ha4linux-update-apply-worker.py')


def require_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit('This command must run as root')


def main() -> None:
    require_root()

    if not REQUEST_FILE.exists():
        raise SystemExit(f'request file not found: {REQUEST_FILE}')
    if not WORKER_PATH.exists():
        raise SystemExit(f'update worker not found: {WORKER_PATH}')

    systemd_run = shutil.which('systemd-run')
    if not systemd_run:
        raise SystemExit('systemd-run command not available')

    unit_name = f'ha4linux-update-apply-{int(time.time())}-{os.getpid()}'
    completed = subprocess.run(
        [
            systemd_run,
            f'--unit={unit_name}',
            '--wait',
            '--pipe',
            '--collect',
            '--property=Type=oneshot',
            '--description=HA4Linux remote update apply',
            str(WORKER_PATH),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    if completed.stdout:
        sys.stdout.write(completed.stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)

    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or f'update worker failed ({completed.returncode})'
        raise SystemExit(message)


if __name__ == '__main__':
    main()
