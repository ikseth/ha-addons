#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import posixpath
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

DATA_DIR = Path('/var/lib/ha4linux')
REQUEST_FILE = DATA_DIR / 'update-request.json'
BACKUP_ROOT = DATA_DIR / 'update-backups'
LAST_BACKUP_FILE = DATA_DIR / 'last-update-backup.json'
INSTALL_DIR = Path('/opt/ha4linux')

BACKUP_PATHS = (
    Path('/opt/ha4linux/app'),
    Path('/opt/ha4linux/requirements.txt'),
    Path('/opt/ha4linux/update'),
    Path('/etc/ha4linux'),
    Path('/etc/systemd/system/ha4linux.service'),
    Path('/etc/systemd/system/ha4linux.service.d'),
    Path('/etc/sudoers.d/ha4linux'),
)


def log(message: str) -> None:
    print(f'[ha4linux-update-apply] {message}', flush=True)


def require_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit('This command must run as root')


def read_request() -> dict[str, str]:
    if not REQUEST_FILE.exists():
        raise SystemExit(f'request file not found: {REQUEST_FILE}')
    payload = json.loads(REQUEST_FILE.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise SystemExit('request payload must be a JSON object')

    request = {
        'target_version': str(payload.get('target_version', '')).strip(),
        'installed_version': str(payload.get('installed_version', '')).strip(),
        'channel': str(payload.get('channel', '')).strip(),
        'manifest_url': str(payload.get('manifest_url', '')).strip(),
        'asset_url': str(payload.get('asset_url', '')).strip(),
        'asset_sha256': str(payload.get('asset_sha256', '')).strip(),
    }
    if not request['target_version']:
        raise SystemExit('target_version missing in request')
    return request


def fetch_manifest(manifest_url: str, channel: str) -> dict[str, str]:
    if not manifest_url:
        raise RuntimeError('manifest_url missing in request')

    with urllib.request.urlopen(manifest_url, timeout=30) as response:
        raw = response.read().decode('utf-8')

    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError('manifest payload must be a JSON object')

    channels = payload.get('channels')
    if isinstance(channels, dict):
        selected = channels.get(channel or 'stable')
        if not isinstance(selected, dict):
            raise RuntimeError(f"manifest channel '{channel or 'stable'}' not found")
        payload = selected

    version = str(payload.get('version', '')).strip()
    asset_url = str(payload.get('asset_url', '')).strip()
    asset_sha256 = str(payload.get('sha256', '')).strip()
    changelog_url = str(payload.get('changelog_url', '')).strip()
    return {
        'version': version,
        'asset_url': asset_url,
        'asset_sha256': asset_sha256,
        'changelog_url': changelog_url,
    }


def enrich_request(request: dict[str, str]) -> dict[str, str]:
    if request['asset_url']:
        return request

    manifest = fetch_manifest(request['manifest_url'], request['channel'])
    manifest_version = manifest['version']
    if manifest_version and manifest_version != request['target_version']:
        raise RuntimeError(
            f"manifest version mismatch: requested {request['target_version']} but manifest provides {manifest_version}"
        )
    if not manifest['asset_url']:
        raise RuntimeError('asset_url missing in manifest')

    enriched = dict(request)
    enriched['asset_url'] = manifest['asset_url']
    if manifest['asset_sha256']:
        enriched['asset_sha256'] = manifest['asset_sha256']
    return enriched


def add_path(archive: tarfile.TarFile, path: Path) -> None:
    if not path.exists():
        return
    archive.add(path, arcname=str(path).lstrip('/'), recursive=True)


def create_backup(request: dict[str, str]) -> Path:
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    source_version = request['installed_version'] or 'unknown'
    backup_dir = BACKUP_ROOT / f"{timestamp}_{source_version}_to_{request['target_version']}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(backup_dir / 'state.tar.gz', 'w:gz') as archive:
        for path in BACKUP_PATHS:
            add_path(archive, path)

    metadata = {
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'installed_version': request['installed_version'],
        'target_version': request['target_version'],
        'channel': request['channel'],
        'manifest_url': request['manifest_url'],
        'asset_url': request['asset_url'],
        'asset_sha256': request['asset_sha256'],
    }
    (backup_dir / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    shutil.copy2(REQUEST_FILE, backup_dir / 'request.json')
    LAST_BACKUP_FILE.write_text(json.dumps({'backup_dir': str(backup_dir)}, indent=2) + '\n', encoding='utf-8')
    return backup_dir


def download_asset(asset_url: str, destination: Path) -> None:
    with urllib.request.urlopen(asset_url, timeout=60) as response:
        with destination.open('wb') as handle:
            shutil.copyfileobj(response, handle)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def locate_installer(extract_root: Path) -> Path:
    matches = sorted(extract_root.glob('**/ha4linux/packaging/common/install-client.sh'))
    if not matches:
        raise RuntimeError('install-client.sh not found in update asset')
    return matches[0]


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
    requirements = INSTALL_DIR / 'requirements.txt'
    if not requirements.exists():
        raise RuntimeError(f'requirements file not found: {requirements}')

    subprocess.run(['python3', '-m', 'venv', '/opt/ha4linux/.venv'], check=True)
    subprocess.run(['/opt/ha4linux/.venv/bin/pip', 'install', '--upgrade', 'pip'], check=True)
    subprocess.run(['/opt/ha4linux/.venv/bin/pip', 'install', '-r', str(requirements)], check=True)


def restore_backup(backup_dir: Path) -> None:
    archive_path = backup_dir / 'state.tar.gz'
    if not archive_path.exists():
        raise RuntimeError(f'backup archive not found: {archive_path}')

    with tempfile.TemporaryDirectory(prefix='ha4linux-restore-', dir=str(DATA_DIR)) as tmp_dir:
        extract_dir = Path(tmp_dir) / 'extract'
        extract_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, 'r:gz') as archive:
            safe_extract_tar(archive, extract_dir)
        for child in extract_dir.iterdir():
            target = Path('/') / child.name
            subprocess.run(['cp', '-a', f'{child}/.' if child.is_dir() else str(child), str(target)], check=True)

    rebuild_virtualenv()
    subprocess.run(['systemctl', 'daemon-reload'], check=True)


def schedule_service_restart() -> None:
    subprocess.Popen(
        ['/bin/sh', '-c', 'sleep 2; systemctl restart ha4linux.service >/dev/null 2>&1'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def apply_update(request: dict[str, str]) -> Path:
    request = enrich_request(request)
    backup_dir = create_backup(request)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='ha4linux-update-', dir=str(DATA_DIR)) as tmp_dir:
        tmp_path = Path(tmp_dir)
        asset_path = tmp_path / 'update-asset.tar.gz'
        extract_dir = tmp_path / 'extract'
        extract_dir.mkdir(parents=True, exist_ok=True)

        log(f"downloading asset {request['asset_url']}")
        download_asset(request['asset_url'], asset_path)

        expected_sha256 = request['asset_sha256']
        if expected_sha256:
            actual_sha256 = sha256_file(asset_path)
            if actual_sha256.lower() != expected_sha256.lower():
                raise RuntimeError('update asset checksum mismatch')

        with tarfile.open(asset_path, 'r:gz') as archive:
            safe_extract_tar(archive, extract_dir)

        installer = locate_installer(extract_dir)
        log(f'running installer from {installer}')
        subprocess.run([str(installer), '--skip-deps', '--no-start'], check=True)

    schedule_service_restart()
    return backup_dir


def main() -> None:
    require_root()
    request = read_request()
    backup_dir: Path | None = None

    try:
        backup_dir = apply_update(request)
    except Exception as exc:
        if backup_dir is not None:
            log(f'update failed, restoring backup from {backup_dir}')
            restore_backup(backup_dir)
        raise SystemExit(str(exc)) from exc

    REQUEST_FILE.unlink(missing_ok=True)
    log(f'update staged successfully; backup stored in {backup_dir}')
    log('ha4linux.service restart scheduled')


if __name__ == '__main__':
    main()
