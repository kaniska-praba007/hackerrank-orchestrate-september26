"""Spending-Change Optimizer for Stage 4 Action Planner."""
from __future__ import annotations

import itertools
from decimal import Decimal
from typing import Any


def generate_candidate_adjustments(
    user_events: list[dict[str, Any]],
    user_profile: dict[str, Any],
    request_date: date | None = None,
) -> list[dict[str, dict[str, Any]]]:
    """Generate valid spending adjustment combinations (max 3 actions).
    
    Invariants:
    1. Only adjust future/upcoming events in the 90-day simulation window.
    2. Only adjust categories user is willing to reduce or stop.
    3. Never adjust categories user wants to protect.
    4. Never both stop AND reduce the same event_id.
    5. Max 3 concurrent adjustments.
    """
    from code.simulation.ledger import parse_date
    protect_cats = set(
        cat.strip().lower()
        for cat in str(user_profile.get("expense_categories_to_protect", "")).split("|")
        if cat.strip()
    )
    reduce_cats = set(
        cat.strip().lower()
        for cat in str(user_profile.get("expense_categories_user_is_willing_to_reduce", "")).split("|")
        if cat.strip()
    )
    stop_cats = set(
        cat.strip().lower()
        for cat in str(user_profile.get("expense_categories_user_is_willing_to_stop", "")).split("|")
        if cat.strip()
    )

    # Candidate individual actions
    candidate_actions: list[tuple[str, str, Decimal, Decimal]] = []  # (event_id, action, new_amount, original_amount)

    for evt in user_events:
        evt_id = evt.get("event_id", "")
        cat = str(evt.get("category", "")).lower().strip()
        direction = str(evt.get("direction", "")).lower().strip()
        flexibility = str(evt.get("flexibility", "")).lower().strip()
        
        # Only debits / expenses
        if direction == "credit" or not cat or cat in protect_cats:
            continue
        if flexibility == "fixed":
            continue

        # Only future / upcoming events in the simulation window
        if request_date:
            evt_date = parse_date(evt.get("cash_effective_date") or evt.get("settlement_date") or evt.get("scheduled_date"))
            if evt_date and evt_date < request_date:
                continue

        amt_raw = Decimal(str(evt.get("amount_home_currency") or evt.get("amount_original") or "0").replace(",", ""))
        if amt_raw <= Decimal("0"):
            continue

        # Check for stop eligibility
        if cat in stop_cats or flexibility in {"stoppable", "reducible_or_stoppable"}:
            candidate_actions.append((evt_id, "stop", Decimal("0.00"), amt_raw))

        # Check for reduce eligibility
        if cat in reduce_cats or flexibility in {"reducible", "reducible_or_stoppable"}:
            min_allowed = evt.get("minimum_allowed_amount")
            if min_allowed is not None and str(min_allowed).strip() != "":
                reduced_amt = Decimal(str(min_allowed).replace(",", ""))
            else:
                reduced_amt = (amt_raw * Decimal("0.50")).quantize(Decimal("0.01"))
            if reduced_amt < amt_raw:
                candidate_actions.append((evt_id, "reduce_to", reduced_amt, amt_raw))

    # Sort candidates by original amount descending and keep top 4 most impactful events
    candidate_actions.sort(key=lambda x: x[3], reverse=True)
    
    # Group actions by event_id to ensure mutual exclusivity
    actions_by_event: dict[str, list[tuple[str, Decimal]]] = {}
    for evt_id, action, new_amt, _ in candidate_actions:
        if len(actions_by_event) < 4 or evt_id in actions_by_event:
            actions_by_event.setdefault(evt_id, []).append((action, new_amt))

    distinct_events = list(actions_by_event.keys())
    adjustment_sets: list[dict[str, dict[str, Any]]] = [{}]  # Start with 0 adjustments (baseline)

    # 1 action combinations
    for evt_id in distinct_events:
        for action, new_amt in actions_by_event[evt_id]:
            adjustment_sets.append({
                evt_id: {"action": action, "new_amount": new_amt}
            })

    # 2 actions combinations
    if len(distinct_events) >= 2:
        for evt1, evt2 in itertools.combinations(distinct_events, 2):
            for a1, amt1 in actions_by_event[evt1]:
                for a2, amt2 in actions_by_event[evt2]:
                    adjustment_sets.append({
                        evt1: {"action": a1, "new_amount": amt1},
                        evt2: {"action": a2, "new_amount": amt2},
                    })

    # 3 actions combinations
    if len(distinct_events) >= 3:
        for evt1, evt2, evt3 in itertools.combinations(distinct_events, 3):
            for a1, amt1 in actions_by_event[evt1]:
                for a2, amt2 in actions_by_event[evt2]:
                    for a3, amt3 in actions_by_event[evt3]:
                        adjustment_sets.append({
                            evt1: {"action": a1, "new_amount": amt1},
                            evt2: {"action": a2, "new_amount": amt2},
                            evt3: {"action": a3, "new_amount": amt3},
                        })

    return adjustment_sets


def format_spending_changes(adjustments: dict[str, dict[str, Any]] | None) -> str:
    """Format spending adjustments into required canonical string."""
    if not adjustments:
        return "none"

    formatted_parts: list[str] = []
    # Deterministic sort by event_id
    for evt_id in sorted(adjustments.keys()):
        adj = adjustments[evt_id]
        act = adj.get("action")
        if act == "stop":
            formatted_parts.append(f"stop:{evt_id}")
        elif act == "reduce_to":
            new_amt = format(Decimal(str(adj.get("new_amount", "0"))).normalize(), "f")
            formatted_parts.append(f"reduce_to:{evt_id}:{new_amt}")

    return "|".join(formatted_parts) if formatted_parts else "none"
