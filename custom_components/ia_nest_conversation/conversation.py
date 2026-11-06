"""Conversation entity backed by one stateless user turn at IA_NEST's edge."""

from __future__ import annotations

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_API_KEY,
    CONF_CA_PEM,
    CONF_MENU_ENTRY,
    CONF_SESSION_HEADER,
    CONF_TIMEOUT,
    CONF_URL,
    DOMAIN,
)
from .edge_client import EdgeClient
from .stream import map_edge_turn


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the only conversation entity for this configuration entry."""
    async_add_entities([IaNestConversationEntity(entry)])


class IaNestConversationEntity(conversation.ConversationEntity):
    """A conversation agent that deliberately sends no HA context or history."""

    _attr_has_entity_name = True
    _attr_name = "Conversation"
    _attr_supports_streaming = True

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = entry.entry_id

    @property
    def supported_languages(self) -> list[str] | str:
        """Support every language; the edge owns language generation."""
        return MATCH_ALL

    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        """Pass exactly this spoken turn to the edge and relay its deltas."""
        client = EdgeClient(
            async_get_clientsession(self.hass),
            self._entry.data[CONF_URL],
            self._entry.data[CONF_API_KEY],
            self._entry.data[CONF_CA_PEM],
            self._entry.data[CONF_MENU_ENTRY],
            self._entry.data[CONF_SESSION_HEADER],
            self._entry.data[CONF_TIMEOUT],
        )
        stream = chat_log.async_add_delta_content_stream(
            self.entity_id,
            self._stream_turn(client, user_input),
        )
        async for _content in stream:
            pass
        return conversation.async_get_result_from_chat_log(user_input, chat_log)

    async def _stream_turn(
        self, client: EdgeClient, user_input: conversation.ConversationInput
    ) -> AsyncGenerator[dict[str, str]]:
        """Map edge chunks and failures into HA's text-only delta stream."""
        async for delta in map_edge_turn(
            client.async_stream_chat(user_input.text, user_input.conversation_id),
            user_input.language,
        ):
            yield delta
