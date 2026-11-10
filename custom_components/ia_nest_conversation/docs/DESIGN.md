# IA_NEST Conversation

This integration adds a Home Assistant conversation agent for text that Assist
does not resolve locally.  It sends the single current user turn to IA_NEST's
OpenAI-compatible edge and relays the response as it streams.  The Home
Assistant conversation id is sent in a configurable request header so the edge
can preserve its own session.

It does not send a system prompt, conversation history, tools, Home Assistant
LLM context, or any house-control request.  TLS certificate verification is
mandatory: the configuration stores the pasted PEM trust root with the config
entry and there is no insecure mode.

## Manual installation

Copy `custom_components/ia_nest_conversation` into the same path in the Home
Assistant configuration directory, restart Home Assistant, then add **IA_NEST
Conversation** under Devices & services. Enter the HTTPS base URL, edge API key,
PEM trust root, menu entry, session-header name, and response deadline. Setup
checks `GET /v1/models` and requires the selected menu entry to be visible.

## Compatibility

Minimum Home Assistant version: **2026.6.2**. It was checked against 2026.6.2
and 2026.11.0; both expose the same `ConversationEntity` streaming contract and
`ChatLog.async_add_delta_content_stream` API used here.
