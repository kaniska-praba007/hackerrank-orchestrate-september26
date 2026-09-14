"""Candidate Plan Generator for Stage 4 Action Planner."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from code.simulation.ledger import parse_date


@dataclass
class CandidatePlan:
    payment_method: str  # full_payment, partial_payment, installments, wait, not_recommended
    payments: list[tuple[date, Decimal]]  # [(date, amount), ...]
    total_amount_paid: Decimal
    completion_date: date
    payment_option_id: str | None = None
    plan_string: str = "none"  # Canonical payment_plan format
    is_eligible: bool = True
    ineligibility_reason: str = ""


def fmt_amt(val: Decimal | str | None) -> str:
    if val is None:
        return "0"
    v = Decimal(str(val).replace(",", ""))
    v = v.quantize(Decimal("0.01")) if v.as_tuple().exponent < -2 else v
    f_str = format(v, "f")
    return f_str.rstrip("0").rstrip(".") if "." in f_str else f_str


def generate_candidate_plans(
    request: dict[str, Any],
    user_profile: dict[str, Any],
    payment_options: list[dict[str, Any]],
    immediate_safe_amount: Decimal,
    earliest_full_date: date | None = None,
) -> list[CandidatePlan]:
    """Generate all structurally valid candidate payment plans for a user request."""
    req_id = request.get("request_id", "")
    req_date = parse_date(request.get("request_date")) or date.today()
    comp_date = parse_date(request.get("desired_completion_date")) or (req_date + timedelta(days=60))
    requested_amount = Decimal(str(request.get("requested_amount", "0")).replace(",", ""))

    user_methods = set(
        m.strip().lower()
        for m in str(user_profile.get("payment_methods_user_will_consider", "")).split("|")
        if m.strip()
    )
    if not user_methods:
        user_methods = {"full_payment", "partial_payment", "installments", "wait"}

    req_allows_partial = str(request.get("allows_partial_payment", "false")).lower() in {"true", "1", "yes"}

    max_inst_months_str = str(user_profile.get("max_installment_months", "")).strip()
    max_inst_months = int(max_inst_months_str) if max_inst_months_str.isdigit() else 999

    candidates: list[CandidatePlan] = []

    # 1. Candidate: full_payment
    can_full = "full_payment" in user_methods
    candidates.append(CandidatePlan(
        payment_method="full_payment",
        payments=[(req_date, requested_amount)],
        total_amount_paid=requested_amount,
        completion_date=req_date,
        plan_string=f"{req_date.isoformat()}:{fmt_amt(requested_amount)}",
        is_eligible=can_full,
        ineligibility_reason="" if can_full else "User does not consider full payment",
    ))

    # 2. Candidate: partial_payment (exactly 2 payments)
    can_partial = req_allows_partial and ("partial_payment" in user_methods)
    if can_partial and Decimal("0") < immediate_safe_amount < requested_amount:
        rem_amount = requested_amount - immediate_safe_amount
        p2_date = earliest_full_date if (earliest_full_date and earliest_full_date <= comp_date) else comp_date
        plan_str = f"{req_date.isoformat()}:{fmt_amt(immediate_safe_amount)}|{p2_date.isoformat()}:{fmt_amt(rem_amount)}"
        candidates.append(CandidatePlan(
            payment_method="partial_payment",
            payments=[(req_date, immediate_safe_amount), (p2_date, rem_amount)],
            total_amount_paid=requested_amount,
            completion_date=p2_date,
            plan_string=plan_str,
            is_eligible=True,
        ))

    # 3. Candidates: installments from request_payment_options
    can_inst = "installments" in user_methods
    req_options = [opt for opt in payment_options if opt.get("request_id") == req_id]
    for opt in req_options:
        opt_id = opt.get("payment_option_id", "")
        opt_method = opt.get("payment_method", "").lower()
        if opt_method != "installments":
            continue

        num_payments = int(opt.get("number_of_payments", "1"))
        first_date = parse_date(opt.get("first_payment_date")) or req_date
        freq_days = int(opt.get("payment_frequency_days", "30") or "30")
        inst_amt = Decimal(str(opt.get("payment_amount", "0")).replace(",", ""))
        total_payable = Decimal(str(opt.get("total_payable_amount", "0")).replace(",", ""))
        if total_payable == Decimal("0"):
            total_payable = inst_amt * num_payments

        # Check max installment duration in months (approx 30 days per month)
        total_duration_days = (num_payments - 1) * freq_days
        total_duration_months = (total_duration_days + 29) // 30
        is_duration_ok = total_duration_months <= max_inst_months

        inst_payments: list[tuple[date, Decimal]] = []
        plan_parts: list[str] = []
        curr_p_date = first_date
        for _ in range(num_payments):
            inst_payments.append((curr_p_date, inst_amt))
            plan_parts.append(f"{curr_p_date.isoformat()}:{fmt_amt(inst_amt)}")
            curr_p_date += timedelta(days=freq_days)

        final_comp_date = inst_payments[-1][0] if inst_payments else req_date
        plan_str = "|".join(plan_parts)

        is_eligible = can_inst and is_duration_ok
        reason = ""
        if not can_inst:
            reason = "User does not consider installments"
        elif not is_duration_ok:
            reason = f"Installment duration ({total_duration_months}m) exceeds user limit ({max_inst_months}m)"

        candidates.append(CandidatePlan(
            payment_method="installments",
            payments=inst_payments,
            total_amount_paid=total_payable,
            completion_date=final_comp_date,
            payment_option_id=opt_id,
            plan_string=plan_str,
            is_eligible=is_eligible,
            ineligibility_reason=reason,
        ))

    # 4. Candidates: wait (future full payment on earliest safe date)
    can_wait = "full_payment" in user_methods
    wait_target_dates: list[date] = []
    if earliest_full_date and earliest_full_date > req_date:
        wait_target_dates.append(earliest_full_date)

    for w_date in sorted(wait_target_dates):
        candidates.append(CandidatePlan(
            payment_method="wait",
            payments=[(w_date, requested_amount)],
            total_amount_paid=requested_amount,
            completion_date=w_date,
            plan_string=f"{w_date.isoformat()}:{fmt_amt(requested_amount)}",
            is_eligible=can_wait,
            ineligibility_reason="" if can_wait else "User does not accept full payment",
        ))

    return candidates
