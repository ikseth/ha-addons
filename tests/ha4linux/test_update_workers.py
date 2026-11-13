"""Update worker failure recovery and virtual environment safety."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

ASSETS = Path(__file__).resolve().parents[2] / 'ha4linux/packaging/assets'


def load_asset(name: str):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ASSETS / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('restore_error', [None, RuntimeError('restore error')])
def test_apply_failure_restores_backup(monkeypatch, tmp_path, restore_error):
    worker = load_asset('ha4linux-update-apply-worker.py')
    backup = tmp_path / 'backup'
    restore = Mock(side_effect=restore_error)
    monkeypatch.setattr(worker, 'require_root', lambda: None)
    monkeypatch.setattr(worker, 'read_request', lambda: {'target_version': '0.5.18'})
    monkeypatch.setattr(worker, 'enrich_request', lambda request: request)
    monkeypatch.setattr(worker, 'create_backup', lambda request: backup)
    monkeypatch.setattr(worker, 'apply_update', Mock(side_effect=RuntimeError('install error')))
    monkeypatch.setattr(worker, 'restore_backup', restore)
    with pytest.raises(SystemExit) as exc:
        worker.main()
    restore.assert_called_once_with(backup)
    assert 'install error' in str(exc.value)
    assert ('restore error' in str(exc.value)) == (restore_error is not None)


def test_no_direct_pip_entrypoint():
    packaging = ASSETS.parent
    for path in packaging.rglob('*'):
        if path.is_file() and path.suffix in {'.py', '.sh'}:
            assert '.venv/bin/pip' not in path.read_text()


def test_healthy_venv_is_preserved(monkeypatch, tmp_path):
    helper = load_asset('ha4linux-venv.py')
    (tmp_path / 'requirements.txt').write_text('example\n')
    python = tmp_path / '.venv/bin/python'
    python.parent.mkdir(parents=True)
    python.write_text('')
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return Mock(returncode=0)

    monkeypatch.setattr(helper.subprocess, 'run', run)
    helper.setup_venv(tmp_path)
    assert python.exists()
    assert list(calls[-1]) == [str(python), '-m', 'pip', 'install', '-r', str(tmp_path / 'requirements.txt')]


def test_broken_venv_survives_failed_replacement(monkeypatch, tmp_path):
    import subprocess

    helper = load_asset('ha4linux-venv.py')
    (tmp_path / 'requirements.txt').write_text('example\n')
    old = tmp_path / '.venv/bin/python'
    old.parent.mkdir(parents=True)
    old.write_text('old')

    def run(args, **kwargs):
        if '-c' in args:
            return Mock(returncode=1)
        if 'venv' in args:
            raise subprocess.CalledProcessError(1, args)
        raise AssertionError(args)

    monkeypatch.setattr(helper.subprocess, 'run', run)
    with pytest.raises(RuntimeError, match='python3-venv'):
        helper.setup_venv(tmp_path)
    assert old.read_text() == 'old'
    assert not list(tmp_path.glob('.venv.new-*'))


def test_update_entity_pending_timeout_and_error(monkeypatch):
    from datetime import UTC, datetime

    from homeassistant.components.update import UpdateEntityFeature

    from custom_components.ha4linux.update import HA4LinuxApiUpdateEntity

    status = {'supported': True, 'enabled': True, 'supports_apply': True,
              'installed_version': '0.5.17', 'target_version': '0.5.18', 'state': 'idle'}
    coordinator = Mock(data={'update': status}, last_update_success=True)
    entry = Mock(entry_id='test', data={'host': '192.0.2.10'}, options={})
    entity = HA4LinuxApiUpdateEntity(coordinator, entry)
    monkeypatch.setattr(entity, 'async_write_ha_state', Mock())
    assert UpdateEntityFeature.PROGRESS in entity.supported_features
    status['supports_apply'] = False
    assert entity.supported_features == UpdateEntityFeature(0)
    status['supports_apply'] = True
    entity._pending_target = '0.5.18'
    entity._pending_started = datetime.now(UTC)
    entity._pending_monotonic = 0
    coordinator.last_update_success = False
    assert entity.available and entity.in_progress
    entity._handle_coordinator_update()
    assert not entity.in_progress
    assert entity.extra_state_attributes['last_update_issue'] == 'update to 0.5.18 did not complete within 300 s'

    entity._pending_target = '0.5.18'
    entity._pending_started = datetime.now(UTC)
    entity._pending_monotonic = 10**15
    coordinator.last_update_success = True
    coordinator.data = {'update': {**status, 'state': 'error', 'error': 'failed'}}
    # A stale error from an earlier attempt does not close the pending update...
    entity._handle_coordinator_update()
    assert entity._pending_target == '0.5.18'
    # ...an error after the agent confirmed the apply does.
    entity._apply_confirmed = True
    entity._handle_coordinator_update()
    assert entity._pending_target is None



@pytest.mark.parametrize('name', ['ha4linux-update-apply-worker.py', 'ha4linux-update-rollback-worker.py'])
def test_restore_files_keeps_paths_missing_from_older_backups(monkeypatch, tmp_path, name):
    worker = load_asset(name)
    app, tray, icon = tmp_path / 'opt/app', tmp_path / 'opt/tray', tmp_path / 'opt/icon.png'
    (app / 'added_by_failed_update.py').parent.mkdir(parents=True)
    (app / 'added_by_failed_update.py').write_text('new')
    tray.mkdir()
    (tray / 'ha4linux-tray').write_text('tray')
    icon.write_text('icon')
    extract = tmp_path / 'extract'
    backed_up_app = extract / app.relative_to('/')
    backed_up_app.mkdir(parents=True)
    (backed_up_app / 'main.py').write_text('old')
    monkeypatch.setattr(worker, 'BACKUP_PATHS', (app, tray, icon))
    monkeypatch.setattr(worker, 'OWNED_DIRS', (app, tray))

    worker.restore_files(extract)

    # Owned directory present in the backup is replaced (drops files added by the failed update).
    assert (app / 'main.py').read_text() == 'old'
    assert not (app / 'added_by_failed_update.py').exists()
    # Paths an older worker did not back up are left untouched.
    assert (tray / 'ha4linux-tray').read_text() == 'tray'
    assert icon.read_text() == 'icon'


def test_venv_helper_fixes_script_paths_after_rename(tmp_path):
    helper = load_asset('ha4linux-venv.py')
    venv, built_at = tmp_path / '.venv', tmp_path / '.venv.new-1'
    (venv / 'bin').mkdir(parents=True)
    (venv / 'bin/pip').write_text(f'#!{built_at}/bin/python3\nprint("pip")\n')
    (venv / 'bin/other').write_text('#!/usr/bin/env python3\n')
    (venv / 'bin/python').symlink_to('/usr/bin/python3')

    helper._fix_script_paths(venv, built_at)

    assert (venv / 'bin/pip').read_text() == f'#!{venv}/bin/python3\nprint("pip")\n'
    assert (venv / 'bin/other').read_text() == '#!/usr/bin/env python3\n'
