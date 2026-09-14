"""Generic Multi-Category Recurrence Extrapolator for Stage 4 Simulation."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from code.simulation.ledger import parse_date

import calendar

NON_RECURRING_EVENT_TYPES = {
    "transfer",
    "refund",
    "bonus",
    "prize",
    "investment",
    "one_off",
    "cancelled",
}


def add_months(sourcedate: date, months: int) -> date:
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def detect_and_extrapolate_recurrence(
    user_events: list[dict[str, Any]],
    user_id: str,
    request_date: date,
    horizon_days: int = 90,
    salary_stream: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Detect recurring series across comparable events sharing (description, category, direction).
    
    Principles:
    1. For expenses/commitments: >= 2 prior settled/scheduled events with matching (description, category, direction).
    2. For salary/income: unified under category 'salary' (using Stage 3 confirmed salary stream when available).
    3. Regular cadence detection across any regular interval.
    4. Exclude non-recurring types (transfers, refunds, bonuses, prizes, investments).
    5. Conservative amount: max for debits, min for credits (or confirmed salary stream).
    """
    end_date = request_date + timedelta(days=horizon_days)

    grouped: dict[tuple[str, str, str], list[tuple[date, Decimal, dict[str, Any]]]] = defaultdict(list)
    for evt in user_events:
        evt_type = str(evt.get("event_type", "")).lower().strip()
        cat = str(evt.get("category", "")).lower().strip()
        direction = str(evt.get("direction", "")).lower().strip()
        status = str(evt.get("status", "")).lower().strip()

        if status not in {"settled", "scheduled"} or direction not in {"credit", "debit"}:
            continue

        if evt_type in NON_RECURRING_EVENT_TYPES or cat in NON_RECURRING_EVENT_TYPES:
            continue

        when = parse_date(evt.get("cash_effective_date") or evt.get("settlement_date") or evt.get("event_date"))
        if when:
            amt_str = str(evt.get("amount_home_currency") or evt.get("amount_original") or "0")
            try:
                amt = Decimal(amt_str.replace(",", ""))
            except Exception:
                continue

            if cat == "salary" or evt_type == "income":
                group_key = ("Salary", "salary", "credit")
            else:
                desc = str(evt.get("description", "")).strip()
                group_key = (desc, cat, direction)
            grouped[group_key].append((when, amt, evt))

    extrapolated_events: list[dict[str, Any]] = []
    has_salary_recurring = False

    for (desc, cat, direction), series in grouped.items():
        series.sort(key=lambda item: item[0])
        if len(series) < 2 and cat != "salary":
            continue

        if len(series) >= 2:
            intervals = [(series[i][0] - series[i - 1][0]).days for i in range(1, len(series))]
            mode_interval = max(set(intervals), key=intervals.count)
            matching_count = sum(1 for inv in intervals if abs(inv - mode_interval) <= 2)
            if cat != "salary" and (matching_count / len(intervals)) < 0.5:
                continue
        else:
            mode_interval = 30

        recent = [x[1] for x in series[-3:]]
        if direction == "debit":
            amount = max(recent)
        else:
            amount = min(recent)

        if cat == "salary":
            has_salary_recurring = True
            if salary_stream and salary_stream.get("is_confirmed") and salary_stream.get("amount") is not None:
                try:
                    amount = Decimal(str(salary_stream.get("amount", amount)).replace(",", ""))
                except Exception:
                    pass

        ref_event = series[-1][2]
        last_date = series[-1][0]
        eid = ref_event.get("event_id")

        if 20 <= mode_interval <= 40 or cat == "salary":
            # Monthly calendar recurrence (same day-of-month)
            m_idx = 1
            cursor = add_months(last_date, m_idx)
            while cursor <= end_date:
                if cursor >= request_date:
                    extrapolated_events.append({
                        "event_id": f"recurring:{eid}:{m_idx}",
                        "source_event_id": eid,
                        "user_id": user_id,
                        "category": cat,
                        "direction": direction,
                        "status": "scheduled",
                        "amount_home_currency": str(amount),
                        "amount_original": str(amount),
                        "amount_currency": ref_event.get("amount_currency", ref_event.get("home_currency", "INR")),
                        "settlement_date": cursor.isoformat(),
                        "cash_effective_date": cursor.isoformat(),
                        "cash_flow_multiplier": Decimal("1.0"),
                        "is_recurring_extrapolated": True,
                        "description": desc,
                        "flexibility": ref_event.get("flexibility", "fixed"),
                        "minimum_allowed_amount": ref_event.get("minimum_allowed_amount", ""),
                    })
                m_idx += 1
                cursor = add_months(last_date, m_idx)
        elif 3 <= mode_interval < 20:
            # Sub-monthly regular cadence
            step = 1
            cursor = last_date + timedelta(days=mode_interval * step)
            while cursor <= end_date:
                if cursor >= request_date:
                    extrapolated_events.append({
                        "event_id": f"recurring:{eid}:{step}",
                        "source_event_id": eid,
                        "user_id": user_id,
                        "category": cat,
                        "direction": direction,
                        "status": "scheduled",
                        "amount_home_currency": str(amount),
                        "amount_original": str(amount),
                        "amount_currency": ref_event.get("amount_currency", ref_event.get("home_currency", "INR")),
                        "settlement_date": cursor.isoformat(),
                        "cash_effective_date": cursor.isoformat(),
                        "cash_flow_multiplier": Decimal("1.0"),
                        "is_recurring_extrapolated": True,
                        "description": desc,
                        "flexibility": ref_event.get("flexibility", "fixed"),
                        "minimum_allowed_amount": ref_event.get("minimum_allowed_amount", ""),
                    })
                step += 1
                cursor = last_date + timedelta(days=mode_interval * step)

    # If salary stream is confirmed but wasn't extrapolated from historical events
    if not has_salary_recurring and salary_stream and salary_stream.get("is_confirmed") and salary_stream.get("amount") is not None:
        try:
            sal_amt = Decimal(str(salary_stream.get("amount", "0")).replace(",", ""))
        except Exception:
            sal_amt = Decimal("0")
        sal_curr = salary_stream.get("currency", "INR")
        eff_date = parse_date(salary_stream.get("effective_date")) or request_date
        m_idx = 1
        cursor = add_months(eff_date, m_idx)
        while cursor < request_date:
            m_idx += 1
            cursor = add_months(eff_date, m_idx)
        while cursor <= end_date:
            extrapolated_events.append({
                "event_id": f"recurring:salary_stream:{user_id}:{m_idx}",
                "source_event_id": f"salary_stream_{user_id}",
                "user_id": user_id,
                "category": "salary",
                "direction": "credit",
                "status": "scheduled",
                "amount_home_currency": str(sal_amt),
                "amount_original": str(sal_amt),
                "amount_currency": sal_curr,
                "settlement_date": cursor.isoformat(),
                "cash_effective_date": cursor.isoformat(),
                "cash_flow_multiplier": Decimal("1.0"),
                "is_recurring_extrapolated": True,
                "description": "Confirmed salary stream",
                "flexibility": "fixed",
                "minimum_allowed_amount": "",
            })
            m_idx += 1
            cursor = add_months(eff_date, m_idx)

    return extrapolated_events
