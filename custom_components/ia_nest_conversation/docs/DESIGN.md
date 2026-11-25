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

## Who is speaking (since 0.2.0)

IA_NEST needs to know who is talking and from which device before it answers
(IA_NEST meta ADR 0017, steps H12P5 D5-D6 and H12P8). Home Assistant observes
both facts; the integration passes them on as HTTP headers, never in the body,
and draws no conclusion from them.

- **Person.** Home Assistant knows the logged-in user of each turn
  (`ConversationInput.context.user_id`), but the edge validates people by the
  e-mail address in the IA_NEST directory. The options hold a table from Home
  Assistant user id (stable when a user is renamed) to that e-mail address. If
  the turn's user has a row, the e-mail goes in the person header (default
  `X-IANest-Person`). No user, or no row: no person header, and the edge treats
  the turn as the account itself with the least permissions. A shared user (for
  example, a tablet used by the whole family) is just one more row pointing to
  its own directory account.
- **Device.** `ConversationInput.device_id` (the device registry id, stable when
  a device is renamed), when present, goes in the device header (default
  `X-IANest-Device`). Satellites send it; the app and the browser do not. The
  satellite id is never sent.
- **Language** is not sent: it belongs to the Assist pipeline, not to the
  speaker. It is still used for the integration's own failure notice.
- The table is installation configuration, written by provisioning through the
  options flow. It never goes into a public repository; examples use made-up
  values.
- None of these facts grants anything. Permissions come from the IA_NEST
  directory. An e-mail address that is not in the directory makes the edge
  answer 403, and the integration speaks its usual failure notice.
- Logs say whether a person or a device was sent, never which.

### Options configuration

Open the integration's **Configure** action and enter a JSON object in **Home
Assistant user ID to e-mail map**. Its keys are Home Assistant user IDs and its
values are the corresponding IA_NEST directory e-mail addresses. Both must be
non-empty text and every e-mail must contain `@`. Leave the object empty when
no user should be identified. The person and device header names default to
`X-IANest-Person` and `X-IANest-Device`; change them only when the edge has
been configured with different names.
