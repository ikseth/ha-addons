#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import posixpath
import subprocess
import tarfile
import tempfile
from pathlib import Path

DATA_DIR = Path('/var/lib/ha4linux')
BACKUP_ROOT = DATA_DIR / 'update-backups'
LAST_BACKUP_FILE = DATA_DIR / 'last-update-backup.json'


def log(message: str) -> None:
    print(f'[ha4linux-update-rollback] {message}', flush=True)


def require_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit('This command must run as root')


def latest_backup_dir() -> Path:
    if LAST_BACKUP_FILE.exists():
        payload = json.loads(LAST_BACKUP_FILE.read_text(encoding='utf-8'))
        candidate = Path(str(payload.get('backup_dir', '')).strip())
        if candidate.exists():
            return candidate

    candidates = sorted([path for path in BACKUP_ROOT.iterdir() if path.is_dir()], reverse=True)
    if not candidates:
        raise SystemExit('no update backup available for rollback')
    return candidates[0]


def safe_extract_tar(archive: tarfile.TarFile, destination: Path) -> None:
    base = destination.resolve()
    for member in archive.getmembers():
        member_path = Path(posixpath.normpath(member.name))
        if member_path.is_absolute():
            raise RuntimeError('refusing to extract absolute path from archive')
        resolved_target = (base / member_path).resolve()
        try:
            resolved_target.relative_to(base)
        except ValueError as exc:
            raise RuntimeError('refusing to extract path outside destination') from exc
    extract_kwargs = {'path': destination}
    if 'filter' in tarfile.TarFile.extractall.__code__.co_varnames:
        extract_kwargs['filter'] = 'data'
    archive.extractall(**extract_kwargs)


def rebuild_virtualenv() -> None:
    requirements = Path('/opt/ha4linux/requirements.txt')
    if not requirements.exists():
        raise RuntimeError(f'requirements file not found: {requirements}')

    subprocess.run(['python3', '-m', 'venv', '/opt/ha4linux/.venv'], check=True)
    subprocess.run(['/opt/ha4linux/.venv/bin/pip', 'install', '--upgrade', 'pip'], check=True)
    subprocess.run(['/opt/ha4linux/.venv/bin/pip', 'install', '-r', str(requirements)], check=True)


def schedule_service_restart() -> None:
    subprocess.Popen(
        ['/bin/sh', '-c', 'sleep 2; systemctl restart ha4linux.service >/dev/null 2>&1'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def restore_backup(backup_dir: Path) -> None:
    archive_path = backup_dir / 'state.tar.gz'
    if not archive_path.exists():
        raise SystemExit(f'backup archive not found: {archive_path}')

    with tempfile.TemporaryDirectory(prefix='ha4linux-rollback-', dir=str(DATA_DIR)) as tmp_dir:
        extract_dir = Path(tmp_dir) / 'extract'
        extract_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, 'r:gz') as archive:
            safe_extract_tar(archive, extract_dir)
        for child in extract_dir.iterdir():
            target = Path('/') / child.name
            subprocess.run(['cp', '-a', f'{child}/.' if child.is_dir() else str(child), str(target)], check=True)

    rebuild_virtualenv()
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    schedule_service_restart()


def main() -> None:
    require_root()
    backup_dir = latest_backup_dir()
    restore_backup(backup_dir)
    log(f'rollback staged successfully from {backup_dir}')
    log('ha4linux.service restart scheduled')


if __name__ == '__main__':
    main()
