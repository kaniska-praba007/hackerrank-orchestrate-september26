from __future__ import annotations


def effective_date(event: dict[str, str]) -> tuple[str, str]:
    """Return the required non-null cash date and the explicit source label."""
    if event["settlement_date"]:
        return event["settlement_date"], "settlement"
    return event["event_date"], "event_fallback"
