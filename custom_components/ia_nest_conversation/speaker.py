"""Turn speaker-header selection independent from Home Assistant."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from .const import (
    CONF_DEVICE_HEADER,
    CONF_PERSON_HEADER,
    CONF_PERSON_MAP,
    DEFAULT_DEVICE_HEADER,
    DEFAULT_PERSON_HEADER,
)

_LOGGER = logging.getLogger(__name__)


def build_turn_headers(
    options: Mapping[str, Any], user_id: str | None, device_id: str | None
) -> dict[str, str]:
    """Build optional person and device headers without exposing their values."""
    person_map = options.get(CONF_PERSON_MAP, {})
    person_header = options.get(CONF_PERSON_HEADER, DEFAULT_PERSON_HEADER)
    device_header = options.get(CONF_DEVICE_HEADER, DEFAULT_DEVICE_HEADER)
    headers: dict[str, str] = {}

    if (
        isinstance(person_map, Mapping)
        and isinstance(person_header, str)
        and user_id
        and isinstance(email := person_map.get(user_id), str)
        and email
    ):
        headers[person_header] = email
    if isinstance(device_header, str) and device_header and device_id:
        headers[device_header] = device_id

    _LOGGER.debug(
        "IA_NEST turn speaker headers person_sent=%s device_sent=%s",
        isinstance(person_header, str) and person_header in headers,
        isinstance(device_header, str) and device_header in headers,
    )
    return headers
