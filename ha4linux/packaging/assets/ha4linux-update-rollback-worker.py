#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import posixpath
import shutil
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path

DATA_DIR = Path('/var/lib/ha4linux')
INSTALL_DIR = Path('/opt/ha4linux')
BACKUP_ROOT = DATA_DIR / 'update-backups'
LAST_BACKUP_FILE = DATA_DIR / 'last-update-backup.json'
BACKUP_PATHS = (
    Path('/opt/ha4linux/app'), Path('/opt/ha4linux/tray'),
    Path('/opt/ha4linux/requirements.txt'), Path('/opt/ha4linux/update'),
    Path('/opt/ha4linux/ha4linux-message-root.py'), Path('/opt/ha4linux/ha4linux-icon.png'),
    Path('/etc/ha4linux'), Path('/etc/xdg/autostart/ha4linux-tray.desktop'),
    Path('/etc/systemd/system/ha4linux.service'), Path('/etc/systemd/system/ha4linux.service.d'),
    Path('/etc/sudoers.d/ha4linux'),
)
OWNED_DIRS = (Path('/opt/ha4linux/app'), Path('/opt/ha4linux/tray'), Path('/opt/ha4linux/update'))


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


def rebuild_virtualenv(helper: Path) -> None:
    subprocess.run(['python3', str(helper), str(INSTALL_DIR)], check=True)


def restore_files(extract_dir: Path) -> None:
    for path in BACKUP_PATHS:
        source = extract_dir / path.relative_to('/')
        # Only touch what the backup contains: backups made by older workers cover fewer
        # paths, and a missing entry must never delete the installed file.
        if not (source.exists() or source.is_symlink()):
            continue
        if path in OWNED_DIRS and source.is_dir():
            # Directories owned by ha4linux are replaced to drop files added by the failed update.
            if path.exists():
                shutil.rmtree(path)
            shutil.copytree(source, path, symlinks=True)
        elif source.is_dir():
            shutil.copytree(source, path, dirs_exist_ok=True, symlinks=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, path, follow_symlinks=False)


def schedule_service_restart() -> None:
    unit_name = f"ha4linux-delayed-restart-{int(time.time())}-{os.getpid()}"
    subprocess.run(
        [
            'systemd-run',
            f'--unit={unit_name}',
            '--on-active=2',
            '--collect',
            '--property=Type=oneshot',
            '--description=HA4Linux delayed service restart',
            '/usr/bin/systemctl',
            'restart',
            'ha4linux.service',
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def restore_backup(backup_dir: Path) -> None:
    archive_path = backup_dir / 'state.tar.gz'
    if not archive_path.exists():
        raise SystemExit(f'backup archive not found: {archive_path}')

    with tempfile.TemporaryDirectory(prefix='ha4linux-rollback-', dir=str(DATA_DIR)) as tmp_dir:
        helper = Path(tmp_dir) / 'ha4linux-venv.py'
        shutil.copy2(INSTALL_DIR / 'update/ha4linux-venv.py', helper)
        extract_dir = Path(tmp_dir) / 'extract'
        extract_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, 'r:gz') as archive:
            safe_extract_tar(archive, extract_dir)
        restore_files(extract_dir)
        rebuild_virtualenv(helper)

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
