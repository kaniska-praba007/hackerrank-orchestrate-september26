"""Ledger and Currency Conversion Utilities for Stage 4 Simulation."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any


def parse_date(d: str | date | datetime | None) -> date | None:
    if d is None:
        return None
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    if isinstance(d, datetime):
        return d.date()
    d_str = str(d).strip()
    if not d_str:
        return None
    try:
        return date.fromisoformat(d_str[:10])
    except Exception:
        return None


def convert_currency(
    amount: Decimal,
    from_curr: str,
    to_curr: str,
    target_date: date,
    rates: dict[tuple[str, str, str], Decimal],
) -> Decimal:
    """Convert amount from from_curr to to_curr using exchange rates on or before target_date."""
    if from_curr == to_curr or amount == Decimal("0"):
        return amount

    # Direct match
    date_str = target_date.isoformat()
    if (from_curr, to_curr, date_str) in rates:
        return (amount * rates[(from_curr, to_curr, date_str)]).quantize(Decimal("0.01"))

    # Fallback to nearest prior date
    matching_rates = [
        (r_date, rate)
        for (f, t, r_date), rate in rates.items()
        if f == from_curr and t == to_curr and r_date <= date_str
    ]
    if matching_rates:
        matching_rates.sort(key=lambda x: x[0], reverse=True)
        return (amount * matching_rates[0][1]).quantize(Decimal("0.01"))

    # Fallback to earliest available if all dates are in future
    all_rates = [
        (r_date, rate)
        for (f, t, r_date), rate in rates.items()
        if f == from_curr and t == to_curr
    ]
    if all_rates:
        all_rates.sort(key=lambda x: x[0])
        return (amount * all_rates[0][1]).quantize(Decimal("0.01"))

    return amount


def get_event_cash_impact(
    event: dict[str, Any],
    home_currency: str,
    rates: dict[tuple[str, str, str], Decimal],
    adjustments: dict[str, dict[str, Any]] | None = None,
) -> Decimal:
    """Calculate the signed liquid cash flow impact of a verified event.
    
    Credits return positive Decimal; debits return negative Decimal.
    Non-cash, cancelled, or multiplier=0 events return Decimal("0").
    """
    evt_id = event.get("event_id", "")
    multiplier = Decimal(str(event.get("cash_flow_multiplier", "1.0")))
    if multiplier == Decimal("0"):
        return Decimal("0")

    status = event.get("status", "")
    if status in {"cancelled", "failed"}:
        return Decimal("0")

    # Check for active spending adjustments
    match_id = evt_id if (adjustments and evt_id in adjustments) else event.get("source_event_id", "")
    if adjustments and match_id in adjustments:
        adj = adjustments[match_id]
        if adj.get("action") == "stop":
            return Decimal("0")
        if adj.get("action") == "reduce_to":
            new_amt = Decimal(str(adj.get("new_amount", "0")))
            return -new_amt

    # Standard amount resolution
    amt_home = event.get("amount_home_currency")
    if amt_home is not None and str(amt_home).strip() != "":
        amt = Decimal(str(amt_home).replace(",", ""))
    else:
        orig = event.get("amount_original")
        curr = event.get("amount_currency", home_currency)
        if orig is None or str(orig).strip() == "":
            return Decimal("0")
        amt_raw = Decimal(str(orig).replace(",", ""))
        evt_date = parse_date(event.get("cash_effective_date") or event.get("settlement_date") or event.get("authorization_date")) or date.today()
        amt = convert_currency(amt_raw, curr, home_currency, evt_date, rates)

    direction = str(event.get("direction", "debit")).lower()
    if direction == "credit":
        return amt * multiplier
    return -amt * multiplier
