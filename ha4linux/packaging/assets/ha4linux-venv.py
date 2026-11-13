#!/usr/bin/env python3
"""Install requirements without replacing a usable virtual environment."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _run(*args: str) -> None:
    subprocess.run(args, check=True)


def _can_run(*args: str) -> bool:
    try:
        return subprocess.run(args, capture_output=True, check=False).returncode == 0
    except OSError:
        return False


def _fix_script_paths(venv: Path, built_at: Path) -> None:
    """Point console scripts at the final path; they were generated in the temporary one."""
    old_prefix = f'#!{built_at}/bin/'.encode()
    new_prefix = f'#!{venv}/bin/'.encode()
    for script in (venv / 'bin').iterdir():
        if script.is_symlink() or not script.is_file():
            continue
        with script.open('rb') as handle:
            first = handle.readline()
        if first.startswith(old_prefix):
            data = script.read_bytes()
            script.write_bytes(new_prefix + data[len(old_prefix):])


def setup_venv(install_dir: Path) -> None:
    requirements = install_dir / 'requirements.txt'
    if not requirements.is_file():
        raise RuntimeError(f'requirements file not found: {requirements}')
    current = install_dir / '.venv'
    python = current / 'bin/python'
    healthy = (
        python.is_file()
        and _can_run(str(python), '-c', 'import sys')
        and _can_run(str(python), '-m', 'pip', '--version')
    )
    if healthy:
        _run(str(python), '-m', 'pip', 'install', '-r', str(requirements))
        return

    if sys.version_info < (3, 9):  # noqa: UP036 -- supports Python 3.9 hosts
        raise RuntimeError('Python 3.9 or newer is required to create the virtual environment')
    suffix = f'{int(time.time())}-{os.getpid()}'
    replacement = install_dir / f'.venv.new-{suffix}'
    previous = install_dir / f'.venv.old-{suffix}'
    print(f'[ha4linux-venv] Replacing missing or unusable {current}', flush=True)
    try:
        try:
            _run(sys.executable, '-m', 'venv', str(replacement))
        except subprocess.CalledProcessError as exc:
            raise RuntimeError('Cannot create virtual environment; install the system python3-venv package') from exc
        new_python = replacement / 'bin/python'
        _run(str(new_python), '-m', 'pip', 'install', '-r', str(requirements))
        _run(str(new_python), '-m', 'pip', '--version')
        had_current = current.exists() or current.is_symlink()
        if had_current:
            current.rename(previous)
        try:
            replacement.rename(current)
        except OSError:
            if had_current:
                previous.rename(current)
            raise
        _fix_script_paths(current, replacement)
        if had_current:
            if previous.is_dir() and not previous.is_symlink():
                shutil.rmtree(previous)
            else:
                previous.unlink()
    finally:
        if replacement.exists():
            shutil.rmtree(replacement)


if __name__ == '__main__':
    try:
        setup_venv(Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/opt/ha4linux'))
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f'[ha4linux-venv] {exc}') from exc
