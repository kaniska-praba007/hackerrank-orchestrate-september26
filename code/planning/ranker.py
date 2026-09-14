"""Deterministic 6-Tier Plan Ranker for Stage 4 Action Planner."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from code.planning.candidate_generator import CandidatePlan
from code.simulation.simulator import CashSimulator, SimulationResult


@dataclass
class EvaluatedPlan:
    plan: CandidatePlan
    spending_changes: dict[str, dict[str, Any]]
    spending_changes_string: str
    simulation_result: SimulationResult
    affordability_status: str
    is_safe: bool


def evaluate_and_rank_plans(
    simulator: CashSimulator,
    candidate_plans: list[CandidatePlan],
    spending_adjustment_sets: list[dict[str, dict[str, Any]]],
    request_date: date,
    desired_completion_date: date,
    format_changes_fn: Any,
) -> tuple[EvaluatedPlan | None, list[EvaluatedPlan]]:
    """Simulate candidate plans across spending adjustments and rank safe plans using strict 6-tier hierarchy.
    
    6-Tier Ranking Criteria:
    1. Completion by deadline (completion_date <= desired_completion_date)
    2. No spending changes needed (spending_changes_needed == "none")
    3. Least total amount paid
    4. Earliest first payment date
    5. Fewest payments count
    6. Lowest payment_option_id
    """
    evaluated_safe_plans: list[EvaluatedPlan] = []

    for plan in candidate_plans:
        if not plan.is_eligible:
            continue

        for adj_set in spending_adjustment_sets:
            sim_res = simulator.simulate(
                request_date=request_date,
                candidate_payments=plan.payments,
                adjustments=adj_set,
            )

            if not sim_res.is_safe:
                continue

            changes_str = format_changes_fn(adj_set)
            has_changes = changes_str != "none"

            # Derive standard 4-value affordability status (problem_statement.md line 44)
            if plan.payment_method == "full_payment" and not has_changes:
                status = "affordable_now"
            elif plan.payment_method in {"partial_payment", "installments"} or has_changes:
                status = "affordable_with_plan"
            elif plan.payment_method == "wait":
                status = "affordable_later"
            else:
                status = "not_affordable"

            evaluated_safe_plans.append(EvaluatedPlan(
                plan=plan,
                spending_changes=adj_set,
                spending_changes_string=changes_str,
                simulation_result=sim_res,
                affordability_status=status,
                is_safe=True,
            ))

    # Filter to plans that complete on or before desired completion date
    valid_deadline_plans = [
        ep for ep in evaluated_safe_plans
        if ep.plan.completion_date <= desired_completion_date
    ]

    if not valid_deadline_plans:
        return None, []

    # Sort using strict 6-tier ranking tuple
    def ranking_key(ep: EvaluatedPlan):
        p = ep.plan
        no_spending_changes = 0 if ep.spending_changes_string == "none" else 1
        total_paid = p.total_amount_paid
        first_date = p.payments[0][0] if p.payments else request_date
        num_payments = len(p.payments)
        opt_id = p.payment_option_id or "zzzzzz"

        return (
            no_spending_changes,   # Tier 2: No spending changes first
            total_paid,            # Tier 3: Least total amount paid
            first_date,            # Tier 4: Earliest first payment date
            num_payments,          # Tier 5: Fewest payments count
            opt_id,                # Tier 6: Lowest payment_option_id
        )

    valid_deadline_plans.sort(key=ranking_key)
    return valid_deadline_plans[0], valid_deadline_plans
