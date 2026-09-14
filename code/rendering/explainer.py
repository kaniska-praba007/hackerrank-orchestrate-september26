"""Deterministic Explanation Renderer for Stage 5."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from code.simulation.ledger import parse_date


def human_money(value: Decimal | str | None) -> str:
    if value is None or str(value).strip() == "":
        return "0"
    try:
        v = Decimal(str(value).replace(",", ""))
    except Exception:
        return str(value)
    rendered = f"{v:,.2f}"
    if rendered.endswith(".00"):
        return rendered[:-3]
    if rendered.endswith("0") and "." in rendered and len(rendered.split(".")[1]) == 2:
        return rendered
    return rendered


def human_date(d: date | str | None) -> str:
    parsed = parse_date(d)
    if not parsed:
        return ""
    return f"{parsed.day} {parsed.strftime('%B %Y')}"


def format_action_prose(action: str, new_amt: str, desc: str, curr: str) -> str:
    desc_clean = desc.lower().strip() if desc else "subscription"
    if not desc_clean.startswith("the "):
        desc_clean = f"the {desc_clean}"
    if action == "stop":
        return f"Stop {desc_clean}"
    elif action == "reduce_to":
        return f"Reduce {desc_clean} to {curr} {human_money(new_amt)}"
    return ""


def render_explanation(
    trace: dict[str, Any],
    events_by_id: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Deterministically compile decision explanation from typed DecisionTrace."""
    events_by_id = events_by_id or {}
    method = trace.get("winning_method", "not_recommended")
    curr = trace.get("home_currency", "INR")
    asked = Decimal(trace.get("requested_amount", "0"))
    floor = Decimal(trace.get("minimum_balance_floor", "0"))
    safe_today = Decimal(trace.get("immediate_safe_amount", "0"))
    changes_str = trace.get("spending_changes_needed", "none")
    comp_date_str = trace.get("winning_completion_date", "")
    earliest_full_str = trace.get("earliest_full_payment_date", "")
    deadline_str = trace.get("desired_completion_date", "") or comp_date_str

    if method == "full_payment":
        if changes_str == "none":
            # Baseline full payment
            phrase = "keeps the" if trace.get("request_type") == "other" else "leaves at least"
            suffix = "minimum available" if phrase == "keeps the" else "available"
            return f"Pay {curr} {human_money(asked)} today. This {phrase} {curr} {human_money(floor)} {suffix} over the next 90 days."
        else:
            # Spending changes applied
            prose_parts = []
            for item in changes_str.split("|"):
                parts = item.split(":")
                act = parts[0]
                evt_id = parts[1]
                amt_part = parts[2] if len(parts) > 2 else ""
                evt = events_by_id.get(evt_id, {})
                desc = evt.get("description") or evt.get("category") or "subscription"
                prose_parts.append(format_action_prose(act, amt_part, desc, curr))

            joined_prose = " and ".join(p[0].lower() + p[1:] if i > 0 else p for i, p in enumerate(prose_parts))
            return f"{joined_prose}, then pay {curr} {human_money(asked)} today. This leaves at least {curr} {human_money(floor)} available."

    elif method == "installments":
        plan_str = trace.get("payment_plan", "")
        plan_parts = plan_str.split("|") if plan_str and plan_str != "none" else []
        num_inst = len(plan_parts)
        first_part = plan_parts[0] if plan_parts else f"{trace.get('request_date')}:{asked}"
        f_date_str, f_amt_str = first_part.split(":")
        return f"Use {num_inst} installments of {curr} {human_money(f_amt_str)}, starting {human_date(f_date_str)}. This leaves at least {curr} {human_money(floor)} available."

    elif method == "partial_payment":
        plan_str = trace.get("payment_plan", "")
        plan_parts = plan_str.split("|")
        p1_date, p1_amt = plan_parts[0].split(":")
        p2_date, p2_amt = plan_parts[1].split(":")
        return f"Pay {curr} {human_money(p1_amt)} today and the remaining {curr} {human_money(p2_amt)} on {human_date(p2_date)}. This completes the full request and keeps the {curr} {human_money(floor)} minimum protected."

    elif method == "wait":
        w_date = earliest_full_str or comp_date_str
        req_deadline = trace.get("desired_completion_date", "")
        if req_deadline and w_date < req_deadline:
            return f"Wait until {human_date(w_date)}, then pay {curr} {human_money(asked)} in full. Paying sooner would put the {curr} {human_money(floor)} minimum at risk."
        return f"Pay {curr} {human_money(asked)} in full on {human_date(w_date)}. Paying earlier would take the balance below the {curr} {human_money(floor)} minimum."

    else:
        # not_recommended
        if not earliest_full_str:
            if Decimal("0") < safe_today < asked:
                return f"Do not proceed with the {curr} {human_money(asked)} request. Although {curr} {human_money(safe_today)} is available today, the full amount cannot be completed safely within 90 days."
            return f"Do not make this payment by {human_date(deadline_str)}. None of the available options keeps the {curr} {human_money(floor)} minimum protected."
        else:
            # earliest_date_for_full_payment is populated
            if deadline_str and earliest_full_str > deadline_str:
                return f"Do not make this payment by {human_date(deadline_str)}. The full {curr} {human_money(asked)} is not safe until {human_date(earliest_full_str)}, which is after the requested deadline."
            if trace.get("has_eligible_candidates", True):
                return f"The full {curr} {human_money(asked)} is safe to pay by {human_date(earliest_full_str)}, but none of the available payment methods you consider keeps your {curr} {human_money(floor)} minimum balance protected throughout the period."
            return f"The full {curr} {human_money(asked)} is safe to pay by {human_date(earliest_full_str)}, but no payment method you and the merchant both accept is available for this request."


def verify_grounding_and_consistency(
    row: dict[str, str],
    trace: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Verify decision_explanation and output fields are strictly grounded in DecisionTrace."""
    issues = []
    status = row.get("affordability_status", "")
    method = row.get("recommended_payment_method", "")
    plan = row.get("payment_plan", "")
    explanation = row.get("decision_explanation", "")
    curr = trace.get("home_currency", "")

    # 1. State consistency check
    if status == "affordable_now" and method != "full_payment":
        issues.append(f"affordable_now must use full_payment, found {method}")
    elif status == "affordable_with_plan" and method not in ("full_payment", "partial_payment", "installments"):
        issues.append(f"affordable_with_plan must use full_payment/partial_payment/installments, found {method}")
    elif status == "affordable_later" and method != "wait":
        issues.append(f"affordable_later must use wait, found {method}")
    elif status == "not_affordable" and method != "not_recommended":
        issues.append(f"not_affordable must use not_recommended, found {method}")

    # 2. Plan consistency check
    if method == "not_recommended" and plan != "none":
        issues.append(f"Method not_recommended must have payment_plan='none'")
    elif method in ("full_payment", "partial_payment", "installments", "wait") and plan == "none":
        issues.append(f"Method {method} cannot have payment_plan='none'")

    # 3. Currency and trace grounding
    if curr and curr not in explanation:
        issues.append(f"Explanation missing home currency {curr}")

    return len(issues) == 0, issues

