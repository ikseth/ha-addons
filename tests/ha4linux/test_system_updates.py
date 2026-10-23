"""Tests de la logica de actualizaciones del sistema de ha4linux. No requieren Home Assistant."""
import importlib.util
import os
import sys

_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "custom_components", "ha4linux", "system_updates.py"
)
_spec = importlib.util.spec_from_file_location("ha4linux_system_updates", _PATH)
su = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = su
_spec.loader.exec_module(su)


def payload(count=3, state="idle", enabled=True, supported=True, packages=None, total=None, truncated=False):
    if packages is None:
        packages = [{"name": f"pkg{i}", "candidate_version": f"1.{i}", "raw": f"pkg{i} 1.{i}"} for i in range(count)]
    return {
        "updates_enabled": enabled,
        "updates_supported": supported,
        "updates_state": state,
        "updates_pending_count": count,
        "updates_packages": packages,
        "updates_packages_total": count if total is None else total,
        "updates_packages_truncated": truncated,
        "updates_last_checked_at": "2026-10-23T10:00:00+00:00",
        "distribution": "Debian",
        "package_manager": "apt",
    }


def coordinator_data(module_payload):
    return {"sensors": {"system_info": {"available": True, "data": module_payload}}}


def test_system_info_payload_tolera_datos_incompletos():
    assert su.system_info_payload(None) == {}
    assert su.system_info_payload({"sensors": []}) == {}
    assert su.system_info_payload({"sensors": {"system_info": {"data": "x"}}}) == {}
    assert su.system_info_payload(coordinator_data({"a": 1})) == {"a": 1}


def test_solo_hay_muestra_valida_en_idle_activado_y_soportado():
    assert su.pending_count(payload()) == 3
    assert su.pending_count(payload(state="checking")) is None
    assert su.pending_count(payload(enabled=False)) is None
    assert su.pending_count(payload(supported=False)) is None
    assert su.pending_count({}) is None


def test_should_notify_solo_con_paquetes_pendientes():
    assert su.should_notify(payload(count=2))
    assert not su.should_notify(payload(count=0))
    assert not su.should_notify(payload(count=2, state="error"))


def test_firma_cambia_con_la_lista_de_paquetes():
    base = su.notification_signature(payload())
    assert base == su.notification_signature(payload())
    assert base != su.notification_signature(payload(count=4))


def test_mensaje_igual_que_antes():
    message = su.notification_message("host-a", payload(count=2, total=5, truncated=True))
    assert message.splitlines()[:4] == [
        "Host: `host-a`",
        "Distribution: `Debian`",
        "Package manager: `apt`",
        "Pending updates: `2`",
    ]
    assert "- `pkg1` -> `1.1`" in message
    assert message.endswith("- ... and `3` more packages")


def test_atributos_limitan_la_lista_de_paquetes():
    attrs = su.availability_attributes(payload(count=30), limit=20)
    assert attrs["pending_count"] == 30
    assert len(attrs["packages"]) == 20
    assert attrs["packages_truncated"] is True

    attrs = su.availability_attributes(payload(count=2))
    assert attrs["packages"] == ["pkg0", "pkg1"]
    assert attrs["packages_truncated"] is False


def test_atributos_marcan_truncado_si_el_agente_recorto_la_lista():
    attrs = su.availability_attributes(payload(count=50, packages=[{"name": "a"}], total=50, truncated=True))
    assert attrs["packages"] == ["a"]
    assert attrs["packages_truncated"] is True


def test_resumen_agrega_y_omite_equipos_sin_muestra():
    summary = su.summarize(
        [
            ("b", payload(count=2)),
            ("a", payload(count=5)),
            ("c", payload(count=0)),
            ("d", payload(count=7, state="checking")),
        ]
    )
    assert summary == {
        "hosts_reporting": 3,
        "hosts_with_updates": 2,
        "pending_total": 7,
        "hosts": {"a": 5, "b": 2},
    }
    assert su.summarize([])["hosts_reporting"] == 0
