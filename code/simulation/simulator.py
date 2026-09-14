"""Deterministic 90-Day Cash Projection Simulator for Stage 4."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from code.simulation.ledger import convert_currency, get_event_cash_impact, parse_date


@dataclass
class SimulationResult:
    is_safe: bool
    min_balance: Decimal
    min_balance_date: date
    opening_balance: Decimal
    closing_balance: Decimal
    breached_dates: list[date]
    daily_balances: dict[date, Decimal]
    ledger_entries: list[dict[str, Any]]


class CashSimulator:
    def __init__(
        self,
        home_currency: str,
        opening_balance: Decimal,
        minimum_balance_floor: Decimal,
        verified_events: list[dict[str, Any]],
        exchange_rates: dict[tuple[str, str, str], Decimal],
    ):
        self.home_currency = home_currency
        self.opening_balance = opening_balance
        self.floor = minimum_balance_floor
        self.events = verified_events
        self.rates = exchange_rates

    def simulate(
        self,
        request_date: date,
        candidate_payments: list[tuple[date, Decimal]],
        adjustments: dict[str, dict[str, Any]] | None = None,
        horizon_days: int = 90,
    ) -> SimulationResult:
        """Run 90-day daily cash projection and check safety floor after EVERY event and payment.
        
        Deterministic ordering for same-day items:
        1. Confirmed incoming credits
        2. Scheduled/recurring debits
        3. Candidate payments
        """
        end_date = request_date + timedelta(days=horizon_days)

        # Index events occurring within [request_date, end_date] by date
        events_by_date: dict[date, list[dict[str, Any]]] = {}
        for evt in self.events:
            evt_date = parse_date(evt.get("cash_effective_date") or evt.get("settlement_date") or evt.get("scheduled_date"))
            if evt_date and request_date <= evt_date <= end_date:
                events_by_date.setdefault(evt_date, []).append(evt)

        # Index candidate payments by date
        payments_by_date: dict[date, list[Decimal]] = {}
        for p_date, p_amt in candidate_payments:
            if p_amt > Decimal("0"):
                payments_by_date.setdefault(p_date, []).append(p_amt)

        current_balance = self.opening_balance
        min_balance = current_balance
        min_balance_date = request_date
        breached_dates: list[date] = []
        daily_balances: dict[date, Decimal] = {request_date: current_balance}
        ledger_entries: list[dict[str, Any]] = []

        # Check opening balance
        if current_balance < self.floor:
            breached_dates.append(request_date)

        all_dates = sorted(set(events_by_date.keys()) | set(payments_by_date.keys()))
        for curr_date in all_dates:
            day_events = events_by_date.get(curr_date, [])
            credits = [e for e in day_events if str(e.get("direction", "")).lower() == "credit"]
            debits = [e for e in day_events if str(e.get("direction", "")).lower() != "credit"]

            # Conservative intraday settlement sequence (agent_spec.md §3):
            # Under intraday settlement ambiguity, available funds must not presume
            # unposted incoming credits before same-day debits/payments are fulfilled.
            # 1. Scheduled / recurring debits
            # 2. Candidate payments for this day
            # 3. Incoming credits / salary
            for deb in debits:
                impact = get_event_cash_impact(deb, self.home_currency, self.rates, adjustments)
                current_balance += impact
                ledger_entries.append({
                    "date": curr_date,
                    "type": "event",
                    "id": deb.get("event_id"),
                    "impact": impact,
                    "balance_after": current_balance,
                })
                if current_balance < min_balance:
                    min_balance = current_balance
                    min_balance_date = curr_date
                if current_balance < self.floor and curr_date not in breached_dates:
                    breached_dates.append(curr_date)

            for p_amt in payments_by_date.get(curr_date, []):
                current_balance -= p_amt
                ledger_entries.append({
                    "date": curr_date,
                    "type": "candidate_payment",
                    "amount": p_amt,
                    "balance_after": current_balance,
                })
                if current_balance < min_balance:
                    min_balance = current_balance
                    min_balance_date = curr_date
                if current_balance < self.floor and curr_date not in breached_dates:
                    breached_dates.append(curr_date)

            for cred in credits:
                impact = get_event_cash_impact(cred, self.home_currency, self.rates, adjustments)
                current_balance += impact
                ledger_entries.append({
                    "date": curr_date,
                    "type": "event",
                    "id": cred.get("event_id"),
                    "impact": impact,
                    "balance_after": current_balance,
                })
                if current_balance < min_balance:
                    min_balance = current_balance
                    min_balance_date = curr_date
                if current_balance < self.floor and curr_date not in breached_dates:
                    breached_dates.append(curr_date)

            daily_balances[curr_date] = current_balance

        is_safe = len(breached_dates) == 0 and min_balance >= self.floor

        return SimulationResult(
            is_safe=is_safe,
            min_balance=min_balance,
            min_balance_date=min_balance_date,
            opening_balance=self.opening_balance,
            closing_balance=current_balance,
            breached_dates=breached_dates,
            daily_balances=daily_balances,
            ledger_entries=ledger_entries,
        )

    def calculate_max_immediate_safe_amount(
        self,
        request_date: date,
        requested_amount: Decimal,
        adjustments: dict[str, dict[str, Any]] | None = None,
    ) -> Decimal:
        """Find the greatest immediate payment on request_date in [0, requested_amount] that preserves floor."""
        base_res = self.simulate(request_date, [], adjustments=adjustments)
        if not base_res.is_safe:
            return Decimal("0.00")

        headroom = base_res.min_balance - self.floor
        if headroom <= Decimal("0"):
            return Decimal("0.00")

        safe_amt = min(requested_amount, headroom).quantize(Decimal("0.01"))
        return safe_amt

    def find_earliest_date_for_full_payment(
        self,
        request_date: date,
        requested_amount: Decimal,
        horizon_days: int = 90,
    ) -> date | None:
        """Find earliest date in [request_date, request_date + 90] where full payment is safe WITHOUT spending changes."""
        end_date = request_date + timedelta(days=horizon_days)
        curr = request_date
        while curr <= end_date:
            res = self.simulate(
                request_date=request_date,
                candidate_payments=[(curr, requested_amount)],
                adjustments=None,
                horizon_days=horizon_days,
            )
            if res.is_safe:
                return curr
            curr += timedelta(days=1)
        return None
