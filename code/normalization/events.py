from __future__ import annotations

import json
from typing import Iterable

from .amounts import normalize_amount
from .dates import effective_date

FIELDS = [
    "event_id", "user_id", "event_type", "description", "category", "direction",
    "amount_original", "amount_source", "amount_currency", "event_date", "settlement_date",
    "cash_effective_date", "cash_effective_date_source", "status", "linked_event_id",
    "flexibility", "minimum_allowed_amount", "related_image_id", "related_message_ids",
    "home_currency", "amount_home_currency",
]


def normalize_events(
    source_events: Iterable[dict[str, str]], profile_currencies: dict[str, str],
    images: dict[str, str], messages: dict[str, list[str]], rates: dict,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    rows: list[dict[str, str]] = []
    rate_misses: list[dict[str, str]] = []
    for event in source_events:
        home_currency = profile_currencies.get(event["user_id"])
        if not home_currency:
            raise ValueError(f"{event['event_id']}: no profile/home currency for {event['user_id']}")
        related_image_id = images.get(event["event_id"], "")
        cash_date, cash_date_source = effective_date(event)
        amount_original, amount_source, amount_home, rate_miss = normalize_amount(
            event, home_currency, cash_date, related_image_id, rates,
        )
        if rate_miss:
            rate_misses.append(rate_miss)
        rows.append({
            "event_id": event["event_id"], "user_id": event["user_id"],
            "event_type": event["event_type"], "description": event["description"],
            "category": event["category"], "direction": event["direction"],
            "amount_original": amount_original, "amount_source": amount_source,
            "amount_currency": event["currency"], "event_date": event["event_date"],
            "settlement_date": event["settlement_date"], "cash_effective_date": cash_date,
            "cash_effective_date_source": cash_date_source, "status": event["status"],
            "linked_event_id": event["linked_event_id"], "flexibility": event["flexibility"],
            "minimum_allowed_amount": event["minimum_allowed_amount"],
            "related_image_id": related_image_id,
            "related_message_ids": json.dumps(messages.get(event["event_id"], []), separators=(",", ":")),
            "home_currency": home_currency, "amount_home_currency": amount_home,
        })
    return rows, rate_misses
