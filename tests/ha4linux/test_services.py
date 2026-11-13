"""Tests del sensor de unidades, independientes de Home Assistant."""
import sys
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ha4linux"))
from app.sensors.services import ServicesSensor, parse_systemd_timestamp  # noqa: E402


def _collect(outputs):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return CompletedProcess(args, 0, outputs[args[-1]], "")

    with patch("app.sensors.services.shutil.which", return_value="/usr/bin/systemctl"), patch(
        "app.sensors.services.subprocess.run", side_effect=run
    ):
        data = ServicesSensor(list(outputs)).collect()
    assert all(call[1]["env"]["LC_ALL"] == "C" and call[1]["env"]["TZ"] == "UTC" for call in calls)
    assert all("--value" not in call[0] for call in calls)
    return {item["name"]: item for item in data["services"]}


def test_services_results_and_missing_properties():
    items = _collect({
        "ok.service": "ExecMainStatus=0\nSubState=dead\nExecMainExitTimestamp=Fri 2026-11-13 07:22:00 UTC\nResult=success\nLoadState=loaded\nActiveState=inactive\nExecMainStartTimestamp=Fri 2026-11-13 07:21:48 UTC\n",
        "fail.service": "LoadState=loaded\nActiveState=failed\nResult=exit-code\nExecMainStartTimestamp=Fri 2026-11-13 07:21:48 UTC\nExecMainStatus=1\n",
        "never.service": "LoadState=loaded\nActiveState=inactive\nExecMainStartTimestamp=\nExecMainStatus=0\n",
        "missing.service": "LoadState=not-found\nActiveState=inactive\n",
    })
    assert "missing.service" not in items
    assert items["ok.service"]["last_run_end"] == "2026-11-13T07:22:00+00:00"
    assert items["ok.service"]["last_exit_status"] == 0
    assert items["fail.service"]["is_failed"] is True
    assert items["fail.service"]["result"] == "exit-code"
    assert items["fail.service"]["last_exit_status"] == 1
    assert items["never.service"]["last_exit_status"] is None
    assert items["never.service"]["last_run_start"] is None
    assert items["ok.service"]["last_trigger"] is None


def test_timers_and_other_types():
    items = _collect({
        "backup.timer": "LastTriggerUSec=Fri 2026-11-13 07:21:48 UTC\nLoadState=loaded\nActiveState=active\nNextElapseUSecRealtime=Fri 2026-11-13 23:56:04 UTC\nResult=success\n",
        "new.timer": "LoadState=loaded\nLastTriggerUSec=n/a\n",
        "test.socket": "LoadState=loaded\nResult=success\n",
    })
    assert items["backup.timer"]["last_trigger"] == "2026-11-13T07:21:48+00:00"
    assert items["backup.timer"]["next_trigger"] == "2026-11-13T23:56:04+00:00"
    assert items["backup.timer"]["last_exit_status"] is None
    assert items["new.timer"]["last_trigger"] is None
    assert items["test.socket"]["unit_type"] == "socket"
    assert items["test.socket"]["result"] == "success"


def test_invalid_dates_return_none():
    assert parse_systemd_timestamp("bad") is None
    assert parse_systemd_timestamp("Fri 2026-11-13 07:21:48 CET") is None
    assert parse_systemd_timestamp("0") is None
    assert parse_systemd_timestamp("n/a") is None
