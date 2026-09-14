from __future__ import annotations

from decimal import Decimal
from typing import Iterable


def decimal_text(value: Decimal) -> str:
    return format(value, "f")


def rate_index(rates: Iterable[dict[str, str]]) -> dict[tuple[str, str, str], Decimal]:
    return {
        (row["rate_date"], row["from_currency"], row["to_currency"]): Decimal(row["rate"])
        for row in rates
    }


def normalize_amount(
    event: dict[str, str], home_currency: str, cash_effective_date: str,
    related_image_id: str, rates: dict[tuple[str, str, str], Decimal],
) -> tuple[str, str, str, dict[str, str] | None]:
    """Return original amount, source state, home amount, and an exact-date miss."""
    raw_amount = event["amount"]
    if not raw_amount:
        if not related_image_id:
            raise ValueError(f"{event['event_id']}: null amount has no linked image")
        return "", "pending_image_extraction", "", None

    amount = Decimal(raw_amount)
    if event["currency"] == home_currency:
        return decimal_text(amount), "csv", decimal_text(amount), None

    pair = (cash_effective_date, event["currency"], home_currency)
    rate = rates.get(pair)
    if rate is None:
        return decimal_text(amount), "csv", "", {
            "event_id": event["event_id"],
            "from_currency": event["currency"],
            "to_currency": home_currency,
            "cash_effective_date": cash_effective_date,
        }
    return decimal_text(amount), "csv", decimal_text(amount * rate), None
