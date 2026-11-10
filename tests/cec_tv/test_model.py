"""Tests de la logica de estado de cec_tv. No requieren Home Assistant."""
import importlib.util
import os
import sys

import pytest

_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "custom_components", "cec_tv", "model.py")
_spec = importlib.util.spec_from_file_location("cec_tv_model", _PATH)
model = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = model  # dataclasses necesita el modulo registrado
_spec.loader.exec_module(model)

NOW = 1_800_000_000


def labels(power="on", ts=NOW, protocol="1", error="", interval="30"):
    return {model.label(model.PROP_PROTOCOL): protocol,
            model.label(model.PROP_TV_POWER): power,
            model.label(model.PROP_TV_POWER_TS): str(ts),
            model.label(model.PROP_ERROR): error,
            model.label(model.PROP_DEVICE): "/dev/cec0",
            model.label(model.PROP_POLL_INTERVAL): interval}


def snap(**kw):
    return model.Snapshot.from_labels(labels(**kw))


def tracker():
    return model.PowerTracker(hold_unknown=90, stale_factor=3, min_stale=90, optimistic=60)


def test_labels_cubren_todo_el_contrato():
    assert len(model.labels()) == len(model.PROPERTIES)
    assert model.label("cec.tv_power") == "Window(Home).Property(cec.tv_power)"


def test_snapshot_parsea_y_normaliza():
    s = model.Snapshot.from_labels(labels(power="raro", ts="x", interval=""))
    assert (s.power, s.timestamp, s.poll_interval) == ("unknown", 0, 30)


@pytest.mark.parametrize("power, expected", [("on", True), ("standby", False)])
def test_estado_definitivo(power, expected):
    t = tracker()
    t.update(snap(power=power), NOW)
    assert t.available and t.is_on(NOW) is expected


def test_addon_sin_publicar_no_disponible():
    t = tracker()
    t.update(model.Snapshot.from_labels({}), NOW)
    assert not t.available and t.unavailable_reason == "not_published"
    assert t.is_on(NOW) is None


def test_protocolo_incompatible():
    t = tracker()
    t.update(snap(protocol="2"), NOW)
    assert t.unavailable_reason == "incompatible_protocol"


def test_lectura_con_hora_sin_sincronizar_es_antigua():
    """Medido: la primera lectura tras arrancar lleva marca de 1980."""
    t = tracker()
    t.update(snap(ts=315536436), NOW)
    assert t.unavailable_reason == "stale"


def test_limite_de_antiguedad_depende_del_intervalo():
    t = tracker()
    t.update(snap(ts=NOW - 89), NOW)
    assert t.available
    t.update(snap(ts=NOW - 91), NOW)
    assert not t.available
    t.update(snap(ts=NOW - 200, interval="100"), NOW)   # 3 x 100 = 300 s
    assert t.available


def test_unknown_en_transicion_mantiene_el_ultimo_estado():
    t = tracker()
    t.update(snap(power="on", ts=NOW), NOW)
    t.update(snap(power="unknown", ts=NOW + 30), NOW + 30)
    assert t.is_on(NOW + 30) is True
    t.update(snap(power="unknown", ts=NOW + 89), NOW + 89)
    assert t.is_on(NOW + 89) is True


def test_unknown_sostenido_es_desconocido_nunca_apagado():
    """Un televisor desenchufado no contesta: no se puede decir que este apagado."""
    t = tracker()
    t.update(snap(power="standby", ts=NOW), NOW)
    t.update(snap(power="unknown", ts=NOW + 120), NOW + 120)
    assert t.available and t.is_on(NOW + 120) is None


def test_orden_de_encendido_no_parpadea_mientras_la_tele_arranca():
    """Medido: tras activate, standby antiguo y luego unknown mas de 30 s."""
    t = tracker()
    t.update(snap(power="standby", ts=NOW), NOW)
    t.command("on", NOW + 1)
    for dt, power in ((2, "standby"), (5, "unknown"), (15, "unknown"), (20, "unknown")):
        t.update(snap(power=power, ts=NOW + dt), NOW + dt)
        assert t.is_on(NOW + dt) is True, dt
    t.update(snap(power="on", ts=NOW + 23), NOW + 23)
    assert t.is_on(NOW + 23) is True and t.pending is None


def test_confirmacion_solo_con_lectura_posterior_a_la_orden():
    t = tracker()
    t.update(snap(power="on", ts=NOW), NOW)
    t.command("standby", NOW + 5)
    t.update(snap(power="standby", ts=NOW + 4), NOW + 6)   # lectura anterior a la orden
    assert t.pending == "standby"
    t.update(snap(power="standby", ts=NOW + 7), NOW + 8)
    assert t.pending is None and t.is_on(NOW + 8) is False


def test_orden_que_no_se_cumple_vence_y_muestra_la_realidad():
    t = tracker()
    t.update(snap(power="standby", ts=NOW), NOW)
    t.command("on", NOW)
    t.update(snap(power="standby", ts=NOW + 61), NOW + 61)
    assert t.pending is None and t.is_on(NOW + 61) is False


def test_version_tuple():
    assert model.version_tuple("0.2.1") == (0, 2, 1)
    assert model.version_tuple("v1.0") == (1, 0, 0)
    assert model.version_tuple("") == (0, 0, 0)
