from __future__ import annotations

from collections import defaultdict
from typing import Iterable


def profile_currency_index(profiles: Iterable[dict[str, str]]) -> dict[str, str]:
    return {row["user_id"]: row["home_currency"] for row in profiles}


def image_index(images: Iterable[dict[str, str]]) -> dict[str, str]:
    return {row["related_event_id"]: row["image_id"] for row in images}


def message_index(messages: Iterable[dict[str, str]]) -> dict[str, list[str]]:
    """Index IDs only. Caller intentionally never accesses message_text."""
    indexed: dict[str, list[str]] = defaultdict(list)
    for row in messages:
        event_id = row["related_event_id"]
        if event_id:
            indexed[event_id].append(row["message_id"])
    return dict(indexed)
