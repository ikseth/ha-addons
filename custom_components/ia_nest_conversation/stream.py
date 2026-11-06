"""Home Assistant-independent mapping from edge deltas to Assist deltas."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterable
import logging

from .edge_client import EdgeClientError

_LOGGER = logging.getLogger(__name__)


def failure_speech(language: str) -> str:
    """Return the explicitly supported failure notice for this turn's language."""
    if language.lower().startswith("es"):
        return "No he podido contestar ahora. Intentalo de nuevo."
    return "I couldn't answer right now. Please try again."


async def map_edge_turn(
    deltas: AsyncIterable[str], language: str
) -> AsyncGenerator[dict[str, str]]:
    """Turn edge text deltas and edge failures into Assist-compatible deltas."""
    emitted = False
    # Assist starts streaming TTS only after this role delta.
    yield {"role": "assistant"}
    try:
        async for delta in deltas:
            if delta:
                emitted = True
                yield {"content": delta}
    except EdgeClientError as err:
        _LOGGER.error("IA_NEST edge failure type=%s code=%s", err.kind, err.code or "-")
        prefix = " " if emitted else ""
        yield {"content": f"{prefix}{failure_speech(language)}"}
