"""Stage 4 Action Planner and Decision Orchestrator."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from code.planning.candidate_generator import CandidatePlan, generate_candidate_plans
from code.planning.ranker import EvaluatedPlan, evaluate_and_rank_plans
from code.planning.spending_optimizer import (
    format_spending_changes,
    generate_candidate_adjustments,
)
from code.simulation.ledger import convert_currency, parse_date
from code.simulation.recurrence import detect_and_extrapolate_recurrence
from code.simulation.simulator import CashSimulator, SimulationResult


@dataclass
class PlanDecision:
    request_id: str
    user_id: str
    amount_safe_to_pay: Decimal
    affordability_status: str
    recommended_payment_method: str
    payment_plan: str
    earliest_date_for_full_payment: str
    spending_changes_needed: str
    decision_trace: dict[str, Any]


class ActionPlanner:
    def __init__(
        self,
        exchange_rates: dict[tuple[str, str, str], Decimal],
    ):
        self.rates = exchange_rates

    def evaluate_request(
        self,
        request: dict[str, Any],
        user_profile: dict[str, Any],
        user_events: list[dict[str, Any]],
        payment_options: list[dict[str, Any]],
        salary_stream: dict[str, Any] | None = None,
    ) -> PlanDecision:
        req_id = request.get("request_id", "")
        user_id = request.get("user_id", "")
        req_date = parse_date(request.get("request_date")) or date.today()
        comp_date = parse_date(request.get("desired_completion_date")) or (req_date + timedelta(days=60))
        requested_amount = Decimal(str(request.get("requested_amount", "0")).replace(",", ""))

        home_currency = str(user_profile.get("home_currency", "INR"))
        opening_balance = Decimal(str(user_profile.get("current_available_balance", "0")).replace(",", ""))
        min_floor = Decimal(str(user_profile.get("minimum_balance_to_keep", "0")).replace(",", ""))

        # Fail-closed guard: Unresolved claims material to 90-day forecast fail closed immediately
        for evt in user_events:
            if evt.get("amount_source") == "unresolved_claim" or evt.get("status") == "unresolved":
                evt_date = parse_date(evt.get("cash_effective_date") or evt.get("settlement_date") or evt.get("scheduled_date"))
                if evt_date is None or (req_date <= evt_date <= req_date + timedelta(days=90)):
                    trace = {
                        "request_id": req_id,
                        "user_id": user_id,
                        "requested_amount": str(requested_amount),
                        "home_currency": home_currency,
                        "opening_balance": str(opening_balance),
                        "minimum_balance_floor": str(min_floor),
                        "immediate_safe_amount": "0.00",
                        "earliest_full_payment_date": "",
                        "winning_method": "not_recommended",
                        "affordability_status": "not_affordable",
                        "payment_plan": "none",
                        "winning_total_paid": "0.00",
                        "winning_completion_date": "",
                        "spending_changes_needed": "none",
                        "min_projected_balance": str(opening_balance),
                        "min_balance_date": req_date.isoformat(),
                        "unresolved_claim_event_id": evt.get("event_id"),
                    }
                    return PlanDecision(
                        request_id=req_id,
                        user_id=user_id,
                        amount_safe_to_pay=Decimal("0.00"),
                        affordability_status="not_affordable",
                        recommended_payment_method="not_recommended",
                        payment_plan="none",
                        earliest_date_for_full_payment="",
                        spending_changes_needed="none",
                        decision_trace=trace,
                    )

        # 1. Extrapolate generic recurrence
        recurring_events = detect_and_extrapolate_recurrence(
            user_events=user_events,
            user_id=user_id,
            request_date=req_date,
            horizon_days=90,
            salary_stream=salary_stream,
        )
        all_simulation_events = list(user_events) + recurring_events

        # 2. Build simulator
        simulator = CashSimulator(
            home_currency=home_currency,
            opening_balance=opening_balance,
            minimum_balance_floor=min_floor,
            verified_events=all_simulation_events,
            exchange_rates=self.rates,
        )

        # 3. Calculate baseline capacities
        immediate_safe_amount = simulator.calculate_max_immediate_safe_amount(
            request_date=req_date,
            requested_amount=requested_amount,
            adjustments=None,
        )

        earliest_full_date = simulator.find_earliest_date_for_full_payment(
            request_date=req_date,
            requested_amount=requested_amount,
            horizon_days=90,
        )
        earliest_full_str = earliest_full_date.isoformat() if earliest_full_date else ""

        # 4. Generate candidate spending adjustments & candidate payment plans
        adj_sets = generate_candidate_adjustments(
            all_simulation_events, user_profile, request_date=req_date
        )
        candidate_plans = generate_candidate_plans(
            request=request,
            user_profile=user_profile,
            payment_options=payment_options,
            immediate_safe_amount=immediate_safe_amount,
            earliest_full_date=earliest_full_date,
        )

        # 5. Simulate and rank plans using 6-tier hierarchy
        winning_evaluated, all_evaluated = evaluate_and_rank_plans(
            simulator=simulator,
            candidate_plans=candidate_plans,
            spending_adjustment_sets=adj_sets,
            request_date=req_date,
            desired_completion_date=comp_date,
            format_changes_fn=format_spending_changes,
        )

        # 6. Assemble output decision
        if winning_evaluated is not None:
            w_plan = winning_evaluated.plan
            status = winning_evaluated.affordability_status
            method = w_plan.payment_method
            plan_str = w_plan.plan_string
            changes_str = winning_evaluated.spending_changes_string

            trace = {
                "request_id": req_id,
                "user_id": user_id,
                "requested_amount": str(requested_amount),
                "home_currency": home_currency,
                "opening_balance": str(opening_balance),
                "minimum_balance_floor": str(min_floor),
                "immediate_safe_amount": str(immediate_safe_amount),
                "earliest_full_payment_date": earliest_full_str,
                "winning_method": method,
                "affordability_status": status,
                "payment_plan": plan_str,
                "winning_total_paid": str(w_plan.total_amount_paid),
                "winning_completion_date": w_plan.completion_date.isoformat(),
                "spending_changes_needed": changes_str,
                "min_projected_balance": str(winning_evaluated.simulation_result.min_balance),
                "min_balance_date": winning_evaluated.simulation_result.min_balance_date.isoformat(),
            }

            return PlanDecision(
                request_id=req_id,
                user_id=user_id,
                amount_safe_to_pay=immediate_safe_amount,
                affordability_status=status,
                recommended_payment_method=method,
                payment_plan=plan_str,
                earliest_date_for_full_payment=earliest_full_str,
                spending_changes_needed=changes_str,
                decision_trace=trace,
            )

        # Fallback: not_recommended
        has_eligible = any(cp.is_eligible for cp in candidate_plans)
        trace = {
            "request_id": req_id,
            "user_id": user_id,
            "requested_amount": str(requested_amount),
            "home_currency": home_currency,
            "opening_balance": str(opening_balance),
            "minimum_balance_floor": str(min_floor),
            "immediate_safe_amount": str(immediate_safe_amount),
            "earliest_full_payment_date": earliest_full_str,
            "winning_method": "not_recommended",
            "affordability_status": "not_affordable",
            "winning_total_paid": "0.00",
            "winning_completion_date": "",
            "spending_changes_needed": "none",
            "min_projected_balance": str(simulator.simulate(req_date, []).min_balance),
            "min_balance_date": req_date.isoformat(),
            "has_eligible_candidates": has_eligible,
        }

        return PlanDecision(
            request_id=req_id,
            user_id=user_id,
            amount_safe_to_pay=immediate_safe_amount,
            affordability_status="not_affordable",
            recommended_payment_method="not_recommended",
            payment_plan="none",
            earliest_date_for_full_payment=earliest_full_str,
            spending_changes_needed="none",
            decision_trace=trace,
        )
