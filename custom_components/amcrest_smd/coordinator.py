"""Mantiene la conexion push con la camara y el estado de los eventos SMD."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .api import AmcrestSmdApiError, AmcrestSmdAuthError, AmcrestSmdClient
from .const import (
    ACTION_START,
    ACTION_STOP,
    RECONNECT_BACKOFF_FACTOR,
    RECONNECT_BACKOFF_MAX,
    RECONNECT_BACKOFF_START,
    TRACKED_EVENTS,
)

_LOGGER = logging.getLogger(__name__)


class AmcrestSmdCoordinator:
    """Coordina la escucha del stream de eventos y publica el estado.

    A diferencia de un DataUpdateCoordinator, aqui no hay sondeo: la camara
    empuja los eventos por una conexion persistente. La unica peticion adicional
    es una consulta puntual al conectar, para no quedar a ciegas hasta el
    siguiente evento.

    Contrato deliberado (ver docs/DESIGN.md):
      - No hay watchdog. Si se pierde el evento `Stop`, el sensor permanece en
        `on` hasta el siguiente `Stop`. Se compensa en la capa de automatismos.
      - Si la conexion cae, el estado pasa a desconocido y las entidades quedan
        `unavailable`. Nunca se inventa un `off`, porque un `off` falso apagaria
        luces con alguien presente.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: AmcrestSmdClient,
        heartbeat: int,
        device_info: dict[str, Any],
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.client = client
        self.heartbeat = heartbeat
        self.device_info = device_info

        self.connected = False
        self.states: dict[str, bool | None] = {code: None for code in TRACKED_EVENTS}

        self._listeners: list[Callable[[], None]] = []
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        # Marca si el ultimo intento llego a conectar, para reiniciar el backoff
        # solo tras una conexion buena y no tras un fallo encadenado.
        self._connected_last_attempt = False

    @callback
    def add_listener(self, update_callback: Callable[[], None]) -> Callable[[], None]:
        """Suscribe una entidad a los cambios de estado."""
        self._listeners.append(update_callback)

        @callback
        def remove_listener() -> None:
            if update_callback in self._listeners:
                self._listeners.remove(update_callback)

        return remove_listener

    @callback
    def _notify(self) -> None:
        for update_callback in list(self._listeners):
            update_callback()

    async def async_start(self) -> None:
        """Arranca la escucha en segundo plano, sin bloquear el arranque de HA."""
        self._stopping = False
        self._task = self.entry.async_create_background_task(
            self.hass, self._async_run(), name=f"amcrest_smd_{self.entry.entry_id}"
        )

    async def async_stop(self) -> None:
        """Detiene la escucha de forma ordenada."""
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _async_run(self) -> None:
        """Bucle de conexion con backoff exponencial.

        Si la camara esta caida no se la martillea: el tiempo de espera entre
        reintentos crece 1s, 2s, 4s... hasta el tope configurado.
        """
        backoff = RECONNECT_BACKOFF_START

        while not self._stopping:
            self._connected_last_attempt = False
            auth_failed = False

            try:
                await self._async_connect_and_listen()
            except asyncio.CancelledError:
                raise
            except AmcrestSmdAuthError as err:
                # Credenciales malas: reintentar rapido no arregla nada.
                _LOGGER.error("Autenticacion rechazada por la camara: %s", err)
                auth_failed = True
            except AmcrestSmdApiError as err:
                # Solo se informa de la primera caida tras una conexion buena.
                # Los reintentos posteriores van a debug para no inundar el log
                # mientras la camara siga estando inaccesible.
                if self._connected_last_attempt:
                    _LOGGER.info("Conexion con la camara perdida: %s", err)
                else:
                    _LOGGER.debug("Sigue sin poder conectarse: %s", err)
            except Exception:  # noqa: BLE001 - el bucle no debe morir nunca
                _LOGGER.exception("Error inesperado en el stream de eventos")

            self._set_disconnected()

            if self._stopping:
                break

            if auth_failed:
                backoff = RECONNECT_BACKOFF_MAX
            elif self._connected_last_attempt:
                # La conexion era buena y se cayo: reintentamos enseguida.
                backoff = RECONNECT_BACKOFF_START

            _LOGGER.debug("Reconectando con la camara en %.0f s", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * RECONNECT_BACKOFF_FACTOR, RECONNECT_BACKOFF_MAX)

    async def _async_connect_and_listen(self) -> None:
        """Sincroniza el estado inicial y escucha hasta que el stream caiga."""
        # Una unica consulta por conexion, no un sondeo periodico.
        for code in TRACKED_EVENTS:
            self.states[code] = await self.client.async_event_active(code)

        self.connected = True
        self._connected_last_attempt = True
        self._notify()
        _LOGGER.debug(
            "Conectado al stream de eventos; estado inicial: %s", self.states
        )

        async for code, action in self.client.async_stream_events(self.heartbeat):
            if code not in self.states:
                continue

            if action == ACTION_START:
                new_state: bool | None = True
            elif action == ACTION_STOP:
                new_state = False
            else:
                # `Pulse` y demas acciones no delimitan un intervalo.
                continue

            if self.states[code] != new_state:
                self.states[code] = new_state
                self._notify()

    @callback
    def _set_disconnected(self) -> None:
        """Marca la conexion como caida sin inventar estados.

        Los sensores pasan a `unavailable`, no a `off`: un `off` falso con
        alguien en el garaje seria un fallo silencioso y peligroso.
        """
        if not self.connected and all(v is None for v in self.states.values()):
            return

        self.connected = False
        for code in self.states:
            self.states[code] = None
        self._notify()
