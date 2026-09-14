"""Comprehensive Unit Test Suite for Stage 4 Simulator & Action Planner.

Uses purely synthesized fixture data (NO request_ids from sample_requests.csv or requests.csv).
"""
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.planning.planner import ActionPlanner
from code.simulation.recurrence import detect_and_extrapolate_recurrence
from code.simulation.simulator import CashSimulator


def test_1_recurrence_detection():
    print("=================================================================")
    print("TEST 1: Generic Recurrence Detection from 2 Settled Events")
    print("=================================================================")
    # 2 settled utility debits in history (30-day gap: 2025-01-10 and 2025-02-09)
    synth_events = [
        {
            "event_id": "synth_evt_01",
            "user_id": "synth_user_01",
            "category": "utilities",
            "direction": "debit",
            "status": "settled",
            "amount_home_currency": "1850.00",
            "settlement_date": "2025-01-10",
            "cash_effective_date": "2025-01-10",
            "cash_flow_multiplier": Decimal("1.0"),
        },
        {
            "event_id": "synth_evt_02",
            "user_id": "synth_user_01",
            "category": "utilities",
            "direction": "debit",
            "status": "settled",
            "amount_home_currency": "2100.00",  # Higher debit -> conservative amount
            "settlement_date": "2025-02-09",
            "cash_effective_date": "2025-02-09",
            "cash_flow_multiplier": Decimal("1.0"),
        },
    ]

    extrapolated = detect_and_extrapolate_recurrence(
        user_events=synth_events,
        user_id="synth_user_01",
        request_date=date(2025, 2, 15),
        horizon_days=90,
    )

    print(f"Extrapolated Count: {len(extrapolated)}")
    for e in extrapolated:
        print(f"  Recurring Event: date={e['cash_effective_date']}, amount={e['amount_home_currency']}, desc={e['description']}")

    assert len(extrapolated) >= 2, f"Expected at least 2 extrapolated events, got {len(extrapolated)}"
    # Verify conservative amount (max for debit: 2100.00)
    for e in extrapolated:
        assert Decimal(e["amount_home_currency"]) == Decimal("2100.00")
        assert e["direction"] == "debit"
    print(">>> TEST 1 PASSED.\n")


def test_2_partial_payment_schedule():
    print("=================================================================")
    print("TEST 2: Partial-Payment Schedule (Exactly 2 Payments)")
    print("=================================================================")
    # Opening balance = 15000, Floor = 5000 -> Headroom = 10000
    # Request = 16000 (Cannot pay full 16000 immediately, but can pay safe 10000 now, 6000 later after salary)
    user_prof = {
        "user_id": "synth_user_02",
        "home_currency": "INR",
        "current_available_balance": "15000",
        "minimum_balance_to_keep": "5000",
        "payment_methods_user_will_consider": "partial_payment|full_payment",
    }
    request = {
        "request_id": "synth_req_partial",
        "user_id": "synth_user_02",
        "request_date": "2025-03-01",
        "desired_completion_date": "2025-04-15",
        "requested_amount": "16000",
        "allows_partial_payment": "true",
    }
    events = [
        # Upcoming salary on 2025-03-25 of 30000
        {
            "event_id": "synth_sal_01",
            "user_id": "synth_user_02",
            "category": "salary",
            "direction": "credit",
            "status": "scheduled",
            "amount_home_currency": "30000",
            "cash_effective_date": "2025-03-25",
            "cash_flow_multiplier": Decimal("1.0"),
        }
    ]

    planner = ActionPlanner(exchange_rates={})
    decision = planner.evaluate_request(request, user_prof, events, payment_options=[])

    print(f"Recommended Method: {decision.recommended_payment_method}")
    print(f"Amount Safe To Pay: {decision.amount_safe_to_pay}")
    print(f"Payment Plan:       {decision.payment_plan}")
    print(f"Affordability:      {decision.affordability_status}")

    assert decision.recommended_payment_method == "partial_payment"
    assert decision.amount_safe_to_pay == Decimal("10000.00")
    assert decision.payment_plan == "2025-03-01:10000|2025-03-26:6000"
    print(">>> TEST 2 PASSED.\n")


def test_3_installment_schedule_verbatim():
    print("=================================================================")
    print("TEST 3: Installment Schedule Pulled Verbatim from Payment Options")
    print("=================================================================")
    user_prof = {
        "user_id": "synth_user_03",
        "home_currency": "INR",
        "current_available_balance": "8000",
        "minimum_balance_to_keep": "5000",
        "payment_methods_user_will_consider": "installments",
        "max_installment_months": "6",
    }
    request = {
        "request_id": "synth_req_inst",
        "user_id": "synth_user_03",
        "request_date": "2025-05-01",
        "desired_completion_date": "2025-10-15",
        "requested_amount": "12000",
        "allows_partial_payment": "false",
    }
    options = [
        {
            "payment_option_id": "synth_opt_01",
            "request_id": "synth_req_inst",
            "payment_method": "installments",
            "payment_amount": "2100",
            "number_of_payments": "6",
            "first_payment_date": "2025-05-05",
            "payment_frequency_days": "30",
            "financing_fee": "600",
            "total_payable_amount": "12600",
        }
    ]
    # Monthly salary of 5000 on the 1st of each month
    events = [
        {
            "event_id": f"sal_{m}",
            "user_id": "synth_user_03",
            "category": "salary",
            "direction": "credit",
            "status": "scheduled",
            "amount_home_currency": "5000",
            "cash_effective_date": f"2025-0{m}-01",
            "cash_flow_multiplier": Decimal("1.0"),
        }
        for m in range(6, 10)
    ]

    planner = ActionPlanner(exchange_rates={})
    decision = planner.evaluate_request(request, user_prof, events, payment_options=options)

    print(f"Recommended Method: {decision.recommended_payment_method}")
    print(f"Payment Plan:       {decision.payment_plan}")
    print(f"Decision Trace Opt: {decision.decision_trace.get('winning_method')}")

    assert decision.recommended_payment_method == "installments"
    assert "2025-05-05:2100" in decision.payment_plan
    assert len(decision.payment_plan.split("|")) == 6
    print(">>> TEST 3 PASSED.\n")


def test_4_wait_case():
    print("=================================================================")
    print("TEST 4: Wait Case (Future Full Payment Safe after Incoming Credit)")
    print("=================================================================")
    user_prof = {
        "user_id": "synth_user_04",
        "home_currency": "INR",
        "current_available_balance": "6000",
        "minimum_balance_to_keep": "5000",  # Only 1000 headroom today
        "payment_methods_user_will_consider": "full_payment",
    }
    request = {
        "request_id": "synth_req_wait",
        "user_id": "synth_user_04",
        "request_date": "2025-06-01",
        "desired_completion_date": "2025-07-15",
        "requested_amount": "15000",  # Cannot afford on 2025-06-01
        "allows_partial_payment": "false",
    }
    events = [
        # Large confirmed bonus/salary arriving on 2025-06-20
        {
            "event_id": "sal_june",
            "user_id": "synth_user_04",
            "category": "salary",
            "direction": "credit",
            "status": "settled",
            "amount_home_currency": "25000",
            "cash_effective_date": "2025-06-20",
            "cash_flow_multiplier": Decimal("1.0"),
        }
    ]

    planner = ActionPlanner(exchange_rates={})
    decision = planner.evaluate_request(request, user_prof, events, payment_options=[])

    print(f"Recommended Method:     {decision.recommended_payment_method}")
    print(f"Amount Safe To Pay:     {decision.amount_safe_to_pay}")
    print(f"Earliest Full Pay Date: {decision.earliest_date_for_full_payment}")
    print(f"Affordability Status:   {decision.affordability_status}")

    assert decision.recommended_payment_method == "wait"
    assert decision.amount_safe_to_pay == Decimal("1000.00")
    assert decision.earliest_date_for_full_payment == "2025-06-21"
    print(">>> TEST 4 PASSED.\n")


def test_5_stop_only_spending_change():
    print("=================================================================")
    print("TEST 5: Stop-Only Spending Change (Pausing Flexible Subscription)")
    print("=================================================================")
    # Opening 10000, Floor 5000 -> Headroom 5000
    # Request = 5000 on 2025-07-01. But an upcoming streaming debit of 1500 on 2025-07-10 would breach floor (balance would drop to 3500 < 5000).
    # User is willing to stop "streaming". Stopping it makes the full payment safe!
    user_prof = {
        "user_id": "synth_user_05",
        "home_currency": "INR",
        "current_available_balance": "10000",
        "minimum_balance_to_keep": "5000",
        "expense_categories_to_protect": "rent|groceries",
        "expense_categories_user_is_willing_to_stop": "streaming",
        "payment_methods_user_will_consider": "full_payment",
    }
    request = {
        "request_id": "synth_req_stop",
        "user_id": "synth_user_05",
        "request_date": "2025-07-01",
        "desired_completion_date": "2025-07-01",
        "requested_amount": "5000",
        "allows_partial_payment": "false",
    }
    events = [
        {
            "event_id": "stream_sub_01",
            "user_id": "synth_user_05",
            "category": "streaming",
            "direction": "debit",
            "status": "scheduled",
            "amount_home_currency": "1500",
            "cash_effective_date": "2025-07-10",
            "cash_flow_multiplier": Decimal("1.0"),
        }
    ]

    planner = ActionPlanner(exchange_rates={})
    decision = planner.evaluate_request(request, user_prof, events, payment_options=[])

    print(f"Recommended Method:      {decision.recommended_payment_method}")
    print(f"Affordability Status:    {decision.affordability_status}")
    print(f"Spending Changes Needed: {decision.spending_changes_needed}")

    assert decision.recommended_payment_method == "full_payment"
    assert decision.affordability_status == "affordable_with_plan"
    assert "stop:stream_sub_01" in decision.spending_changes_needed
    print(">>> TEST 5 PASSED.\n")


def test_6_reduce_to_only_spending_change():
    print("=================================================================")
    print("TEST 6: Reduce_To-Only Spending Change (Downgrading Dining Expense)")
    print("=================================================================")
    # Opening 10000, Floor 5000 -> Headroom 5000
    # Request = 5000 on 2025-08-01. Dining debit of 800 on 2025-08-05 would breach floor to 4200.
    # User is willing to reduce "dining" (50% reduction = 400).
    user_prof = {
        "user_id": "synth_user_06",
        "home_currency": "INR",
        "current_available_balance": "10000",
        "minimum_balance_to_keep": "5000",
        "expense_categories_to_protect": "rent|groceries",
        "expense_categories_user_is_willing_to_reduce": "dining",
        "payment_methods_user_will_consider": "full_payment",
    }
    request = {
        "request_id": "synth_req_reduce",
        "user_id": "synth_user_06",
        "request_date": "2025-08-01",
        "desired_completion_date": "2025-08-01",
        "requested_amount": "4500",
        "allows_partial_payment": "false",
    }
    events = [
        {
            "event_id": "dining_evt_01",
            "user_id": "synth_user_06",
            "category": "dining",
            "direction": "debit",
            "status": "scheduled",
            "amount_home_currency": "800",
            "cash_effective_date": "2025-08-05",
            "cash_flow_multiplier": Decimal("1.0"),
        }
    ]

    planner = ActionPlanner(exchange_rates={})
    decision = planner.evaluate_request(request, user_prof, events, payment_options=[])

    print(f"Recommended Method:      {decision.recommended_payment_method}")
    print(f"Affordability Status:    {decision.affordability_status}")
    print(f"Spending Changes Needed: {decision.spending_changes_needed}")

    assert decision.recommended_payment_method == "full_payment"
    assert decision.affordability_status == "affordable_with_plan"
    assert "reduce_to:dining_evt_01:400" in decision.spending_changes_needed
    print(">>> TEST 6 PASSED.\n")


def test_7_not_recommended_fallback():
    print("=================================================================")
    print("TEST 7: No Safe Plan (not_recommended Fallback)")
    print("=================================================================")
    # Opening 5200, Floor 5000 -> Headroom 200
    # Request = 50000, no income, fixed rent debits. Impossible to afford.
    user_prof = {
        "user_id": "synth_user_07",
        "home_currency": "INR",
        "current_available_balance": "5200",
        "minimum_balance_to_keep": "5000",
        "expense_categories_to_protect": "rent",
        "payment_methods_user_will_consider": "full_payment|installments",
    }
    request = {
        "request_id": "synth_req_impossible",
        "user_id": "synth_user_07",
        "request_date": "2025-09-01",
        "desired_completion_date": "2025-09-15",
        "requested_amount": "50000",
        "allows_partial_payment": "false",
    }
    events = [
        {
            "event_id": "rent_heavy",
            "user_id": "synth_user_07",
            "category": "rent",
            "direction": "debit",
            "status": "scheduled",
            "amount_home_currency": "200",
            "cash_effective_date": "2025-09-05",
            "cash_flow_multiplier": Decimal("1.0"),
        }
    ]

    planner = ActionPlanner(exchange_rates={})
    decision = planner.evaluate_request(request, user_prof, events, payment_options=[])

    print(f"Recommended Method:     {decision.recommended_payment_method}")
    print(f"Amount Safe To Pay:     {decision.amount_safe_to_pay}")
    print(f"Affordability Status:   {decision.affordability_status}")
    print(f"Payment Plan:           {decision.payment_plan}")

    assert decision.recommended_payment_method == "not_recommended"
    assert decision.affordability_status == "not_affordable"
    assert decision.amount_safe_to_pay == Decimal("0.00")
    assert decision.payment_plan == "none"
    print(">>> TEST 7 PASSED.\n")


if __name__ == "__main__":
    test_1_recurrence_detection()
    test_2_partial_payment_schedule()
    test_3_installment_schedule_verbatim()
    test_4_wait_case()
    test_5_stop_only_spending_change()
    test_6_reduce_to_only_spending_change()
    test_7_not_recommended_fallback()
    print("ALL 7 STAGE 4 SIMULATOR & PLANNER TESTS EXECUTED AND PASSED.")
