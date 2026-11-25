"""Option validation that does not depend on Home Assistant."""

from __future__ import annotations

from typing import Any


def validate_person_map(value: Any) -> dict[str, str]:
    """Return a valid Home Assistant user-id to edge e-mail mapping.

    Values are deliberately not normalized: Home Assistant user IDs are opaque
    identifiers and the edge owns interpretation of the e-mail address.
    """
    if not isinstance(value, dict):
        raise ValueError("The person map must be an object")

    for user_id, email in value.items():
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("Each person-map user ID must be non-empty text")
        if not isinstance(email, str) or not email.strip() or "@" not in email:
            raise ValueError("Each person-map e-mail must be non-empty text containing @")

    return value
