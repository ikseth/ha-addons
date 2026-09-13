"""Logica de estado de la integracion, sin dependencias de Home Assistant.

Interpreta las propiedades que publica el addon de Kodi (contrato `cec.*`,
protocolo 1) y decide que estado mostrar. Esta separada del resto para poder
testearla sin Home Assistant. Las reglas vienen de medidas reales (ver
docs/DESIGN.md):

- Mientras el televisor cambia de estado no contesta por CEC y el addon publica
  `unknown` (tras un encendido, mas de 30 s). Un `unknown` asi no es una perdida:
  se mantiene el ultimo estado conocido durante un margen.
- Una lectura antigua no vale: al arrancar, el equipo puede publicar con la hora
  sin sincronizar, y si el addon deja de publicar la ultima lectura se congela.
- Tras una orden se muestra el estado pedido hasta que el addon lo confirme o
  venza un plazo, para que el interruptor no parpadee.
- `unknown` sostenido (p. ej. televisor desenchufado de la corriente) es estado
  desconocido, nunca `off`.
"""

from __future__ import annotations

from dataclasses import dataclass

SUPPORTED_PROTOCOL = "1"

POWER_ON = "on"
POWER_STANDBY = "standby"
POWER_UNKNOWN = "unknown"
DEFINITIVE = (POWER_ON, POWER_STANDBY)

PROP_PROTOCOL = "cec.protocol"
PROP_TV_POWER = "cec.tv_power"
PROP_TV_POWER_TS = "cec.tv_power_ts"
PROP_ERROR = "cec.error"
PROP_DEVICE = "cec.device"
PROP_POLL_INTERVAL = "cec.poll_interval"
PROPERTIES = (PROP_PROTOCOL, PROP_TV_POWER, PROP_TV_POWER_TS, PROP_ERROR,
              PROP_DEVICE, PROP_POLL_INTERVAL)

DEFAULT_POLL_INTERVAL = 30

UNAVAILABLE_NOT_PUBLISHED = "not_published"
UNAVAILABLE_INCOMPATIBLE = "incompatible_protocol"
UNAVAILABLE_STALE = "stale"


def label(prop: str) -> str:
    return "Window(Home).Property(%s)" % prop


def labels() -> list[str]:
    return [label(p) for p in PROPERTIES]


def _as_int(raw: object, default: int) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Snapshot:
    """Una lectura de las propiedades publicadas por el addon."""

    protocol: str
    power: str
    timestamp: int
    error: str
    device: str
    poll_interval: int

    @classmethod
    def from_labels(cls, result: dict[str, str]) -> "Snapshot":
        get = lambda prop: str(result.get(label(prop)) or "").strip()  # noqa: E731
        power = get(PROP_TV_POWER) or POWER_UNKNOWN
        if power not in DEFINITIVE:
            power = POWER_UNKNOWN
        return cls(
            protocol=get(PROP_PROTOCOL),
            power=power,
            timestamp=_as_int(get(PROP_TV_POWER_TS), 0),
            error=get(PROP_ERROR),
            device=get(PROP_DEVICE),
            poll_interval=_as_int(get(PROP_POLL_INTERVAL), DEFAULT_POLL_INTERVAL)
            or DEFAULT_POLL_INTERVAL,
        )


def version_tuple(raw: str) -> tuple[int, int, int]:
    token = str(raw or "").strip().lower().removeprefix("v").split("-", 1)[0]
    values = [int(part) if part.isdigit() else 0 for part in token.split(".")[:3]]
    return tuple((values + [0, 0, 0])[:3])  # type: ignore[return-value]


class PowerTracker:
    """Convierte lecturas sucesivas en el estado que muestra el interruptor.

    `now` es la hora de pared (epoch, s) de Home Assistant, comparable con la
    marca que publica el addon.
    """

    def __init__(self, hold_unknown: float, stale_factor: float,
                 min_stale: float, optimistic: float) -> None:
        self.hold_unknown = hold_unknown
        self.stale_factor = stale_factor
        self.min_stale = min_stale
        self.optimistic = optimistic

        self.snapshot: Snapshot | None = None
        self.unavailable_reason: str | None = UNAVAILABLE_NOT_PUBLISHED
        self._last_known: str | None = None
        self._last_known_at: float | None = None
        self._pending: str | None = None
        self._pending_since: float | None = None
        self._pending_until: float | None = None

    # --- entradas -------------------------------------------------------

    def command(self, target: str, now: float) -> None:
        """Registra una orden enviada: `target` es POWER_ON o POWER_STANDBY."""
        self._pending = target
        self._pending_since = now
        self._pending_until = now + self.optimistic

    def update(self, snapshot: Snapshot, now: float) -> None:
        self.snapshot = snapshot
        self.unavailable_reason = self._unavailable_reason(snapshot, now)
        if self.unavailable_reason is not None:
            return
        fresh_definitive = snapshot.power in DEFINITIVE
        if fresh_definitive:
            self._last_known = snapshot.power
            self._last_known_at = now
        if self._pending is not None:
            expired = now >= (self._pending_until or 0)
            # Solo confirma una lectura hecha despues de enviar la orden.
            confirmed = (fresh_definitive and snapshot.power == self._pending
                         and snapshot.timestamp >= int(self._pending_since or 0))
            if confirmed or expired:
                self._pending = self._pending_since = self._pending_until = None

    # --- salidas --------------------------------------------------------

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None

    @property
    def pending(self) -> str | None:
        return self._pending

    def power(self, now: float) -> str:
        """Estado a mostrar: on, standby o unknown."""
        if not self.available:
            return POWER_UNKNOWN
        if self._pending is not None and now < (self._pending_until or 0):
            return self._pending
        if self.snapshot is not None and self.snapshot.power in DEFINITIVE:
            return self.snapshot.power
        if (self._last_known is not None and self._last_known_at is not None
                and now - self._last_known_at <= self.hold_unknown):
            return self._last_known
        return POWER_UNKNOWN

    def is_on(self, now: float) -> bool | None:
        power = self.power(now)
        if power == POWER_UNKNOWN:
            return None
        return power == POWER_ON

    def reading_age(self, now: float) -> int | None:
        if self.snapshot is None or self.snapshot.timestamp <= 0:
            return None
        return int(now - self.snapshot.timestamp)

    # --- interno ----------------------------------------------------------

    def _unavailable_reason(self, snapshot: Snapshot, now: float) -> str | None:
        if not snapshot.protocol:
            return UNAVAILABLE_NOT_PUBLISHED
        if snapshot.protocol != SUPPORTED_PROTOCOL:
            return UNAVAILABLE_INCOMPATIBLE
        limit = max(self.stale_factor * snapshot.poll_interval, self.min_stale)
        if snapshot.timestamp <= 0 or now - snapshot.timestamp > limit:
            return UNAVAILABLE_STALE
        return None
