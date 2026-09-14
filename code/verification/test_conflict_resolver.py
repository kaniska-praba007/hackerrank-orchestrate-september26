"""Comprehensive Unit Test Suite for Stage 3 Deterministic Conflict Resolver."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import date
from decimal import Decimal
from code.extraction.claims import Claim
from code.verification.conflict_resolver import (
    is_same_originating_source,
    resolve_claim_pair,
    resolve_competing_claims,
    resolve_event_conflict,
)


def test_fix1_counterparty_matching():
    print("=================================================================")
    print("TEST 1: is_same_originating_source (Counterparty Identity Match)")
    print("=================================================================")
    c1 = Claim(
        source_type="message", source_id="msg_01", user_id="user_02", target_event_id=None,
        claim_type="salary_update", amount=Decimal("42750000"), currency="IDR",
        effective_date=date(2025, 8, 15), is_confirmed=True, confidence=Decimal("0.95"),
        raw_text="Payroll update from Cobalt Systems", counterparty="Cobalt Systems", sent_at="2025-07-29T09:30:00Z"
    )
    c2_same_cp = Claim(
        source_type="message", source_id="msg_02", user_id="user_02", target_event_id=None,
        claim_type="salary_update", amount=Decimal("45000000"), currency="IDR",
        effective_date=date(2025, 9, 15), is_confirmed=True, confidence=Decimal("0.95"),
        raw_text="Revised payroll from Cobalt Systems", counterparty="cobalt systems", sent_at="2025-08-10T09:30:00Z"
    )
    c3_different_cp = Claim(
        source_type="message", source_id="msg_03", user_id="user_02", target_event_id=None,
        claim_type="salary_update", amount=Decimal("38000000"), currency="IDR",
        effective_date=date(2025, 9, 15), is_confirmed=True, confidence=Decimal("0.95"),
        raw_text="Offer from Greenfield Foods", counterparty="Greenfield Foods", sent_at="2025-08-10T09:30:00Z"
    )

    result_same = is_same_originating_source(c1, c2_same_cp)
    result_diff = is_same_originating_source(c1, c3_different_cp)

    print(f"Input A: user={c1.user_id}, source={c1.source_type}, counterparty='{c1.counterparty}'")
    print(f"Input B (Same counterparty): user={c2_same_cp.user_id}, source={c2_same_cp.source_type}, counterparty='{c2_same_cp.counterparty}'")
    print(f"  -> Expected: True | Actual: {result_same}")
    assert result_same is True

    print(f"Input C (Different counterparty): user={c3_different_cp.user_id}, source={c3_different_cp.source_type}, counterparty='{c3_different_cp.counterparty}'")
    print(f"  -> Expected: False | Actual: {result_diff}")
    assert result_diff is False
    print(">>> TEST 1 PASSED.\n")


def test_fix2_sent_at_chronological_ordering():
    print("=================================================================")
    print("TEST 2: Tier 2 Newer Record from Same Source (sent_at timestamp)")
    print("=================================================================")
    c_older = Claim(
        source_type="message", source_id="msg_99", user_id="user_07", target_event_id="event_salary",
        claim_type="salary_update", amount=Decimal("180000"), currency="INR",
        effective_date=date(2024, 9, 15), is_confirmed=True, confidence=Decimal("0.95"),
        raw_text="Initial date", counterparty="BrightPath Media", sent_at="2024-08-15T09:00:00Z"
    )
    c_newer = Claim(
        source_type="message", source_id="msg_01", user_id="user_07", target_event_id="event_salary",
        claim_type="salary_update", amount=Decimal("180000"), currency="INR",
        effective_date=date(2024, 9, 23), is_confirmed=True, confidence=Decimal("0.95"),
        raw_text="Revised date to 23 Sep", counterparty="BrightPath Media", sent_at="2024-08-29T09:30:00Z"
    )

    winner, rationale = resolve_claim_pair(c_older, c_newer)
    print(f"Input Older: id={c_older.source_id}, sent_at={c_older.sent_at}, eff_date={c_older.effective_date}")
    print(f"Input Newer: id={c_newer.source_id}, sent_at={c_newer.sent_at}, eff_date={c_newer.effective_date}")
    print(f"  -> Expected Winner: msg_01 | Actual: {winner.source_id}")
    print(f"  -> Expected Eff Date: 2024-09-23 | Actual: {winner.effective_date}")
    print(f"  -> Rationale: {rationale}")
    assert winner.source_id == "msg_01"
    assert winner.effective_date == date(2024, 9, 23)
    assert "Newer record from same source" in rationale
    print(">>> TEST 2 PASSED.\n")


def test_fix3_tier3_reachability():
    print("=================================================================")
    print("TEST 3: Tier 3 Confirmed vs Unconfirmed Reachability")
    print("=================================================================")
    c_confirmed = Claim(
        source_type="message", source_id="msg_conf", user_id="user_11", target_event_id=None,
        claim_type="salary_update", amount=Decimal("38760000"), currency="IDR",
        effective_date=date(2025, 5, 1), is_confirmed=True, confidence=Decimal("0.95"),
        raw_text="Confirmed base salary", counterparty="Greenfield Foods", sent_at="2025-04-22T09:30:00Z"
    )
    c_unconfirmed = Claim(
        source_type="message", source_id="msg_unconf", user_id="user_11", target_event_id=None,
        claim_type="salary_update", amount=Decimal("45000000"), currency="IDR",
        effective_date=date(2025, 5, 1), is_confirmed=False, confidence=Decimal("0.80"),
        raw_text="Proposed raise pending budget", counterparty="Greenfield Foods", sent_at="2025-04-25T09:30:00Z"
    )

    winner, rationale = resolve_claim_pair(c_confirmed, c_unconfirmed)
    print(f"Input Confirmed: id={c_confirmed.source_id}, amount={c_confirmed.amount}, is_confirmed={c_confirmed.is_confirmed}")
    print(f"Input Unconfirmed: id={c_unconfirmed.source_id}, amount={c_unconfirmed.amount}, is_confirmed={c_unconfirmed.is_confirmed}")
    print(f"  -> Expected Winner: msg_conf | Actual: {winner.source_id}")
    print(f"  -> Expected Amount: 38760000 | Actual: {winner.amount}")
    print(f"  -> Rationale: {rationale}")
    assert winner.source_id == "msg_conf"
    assert "Tier 3: Confirmed record" in rationale
    print(">>> TEST 3 PASSED.\n")


def test_fix4_hard_guard_on_informational_claims():
    print("=================================================================")
    print("TEST 4: Hard Early-Return Guard for Informational / Unconfirmed Types")
    print("=================================================================")
    baseline = {
        "event_id": "event_1785",
        "status": "scheduled",
        "amount_original": "5000",
        "amount_currency": "INR",
        "amount_home_currency": "5000",
    }
    info_claim = Claim(
        source_type="message", source_id="msg_14", user_id="user_20", target_event_id="event_1785",
        claim_type="general_informational", amount=Decimal("99999"), currency="INR",
        effective_date=date(2026, 2, 6), is_confirmed=True, confidence=Decimal("0.99"),
        raw_text="Refund initiated but not received yet", counterparty="CartLane", sent_at="2026-02-06T09:30:00Z"
    )
    bonus_claim = Claim(
        source_type="message", source_id="msg_03", user_id="user_04", target_event_id=None,
        claim_type="unconfirmed_bonus", amount=Decimal("50000000"), currency="IDR",
        effective_date=date(2024, 6, 1), is_confirmed=False, confidence=Decimal("0.95"),
        raw_text="Quarterly bonus pending evaluation", counterparty="Greenfield Foods", sent_at="2024-06-01T09:30:00Z"
    )

    up1, amended1, r1 = resolve_event_conflict(baseline, info_claim)
    print(f"Input Info Claim: id={info_claim.source_id}, type={info_claim.claim_type}, amount={info_claim.amount}")
    print(f"  -> Expected: amended=False, amount='5000' | Actual: amended={amended1}, amount='{up1['amount_original']}'")
    print(f"  -> Rationale: {r1}")
    assert amended1 is False
    assert up1["amount_original"] == "5000"

    up2, amended2, r2 = resolve_event_conflict(baseline, bonus_claim)
    print(f"Input Bonus Claim: id={bonus_claim.source_id}, type={bonus_claim.claim_type}, amount={bonus_claim.amount}")
    print(f"  -> Expected: amended=False, amount='5000' | Actual: amended={amended2}, amount='{up2['amount_original']}'")
    print(f"  -> Rationale: {r2}")
    assert amended2 is False
    assert up2["amount_original"] == "5000"
    print(">>> TEST 4 PASSED.\n")


def test_fix5_tier4_directional_fallback():
    print("=================================================================")
    print("TEST 5: Tier 4 Financially Safer Directional Fallback")
    print("=================================================================")
    # Case A: Debit / Expense conflict (e.g. conflicting utility or rent estimates) -> Conservative Higher Expense
    exp_low = Claim(
        source_type="message", source_id="msg_exp_low", user_id="user_05", target_event_id="evt_util",
        claim_type="amount_adjustment", amount=Decimal("1500"), currency="INR",
        effective_date=date(2025, 4, 1), is_confirmed=True, confidence=Decimal("0.80"),
        raw_text="Estimated utility bill 1500", counterparty="PowerCorp", sent_at="2025-03-01T10:00:00Z",
        direction="debit"
    )
    exp_high = Claim(
        source_type="message", source_id="msg_exp_high", user_id="user_05", target_event_id="evt_util",
        claim_type="amount_adjustment", amount=Decimal("2200"), currency="INR",
        effective_date=date(2025, 4, 1), is_confirmed=True, confidence=Decimal("0.80"),
        raw_text="Estimated utility bill 2200", counterparty="PowerCorp", sent_at="2025-03-01T10:00:00Z",
        direction="debit"
    )
    winner_exp, r_exp = resolve_claim_pair(exp_low, exp_high)
    print(f"Debit Conflict: low={exp_low.amount} INR vs high={exp_high.amount} INR")
    print(f"  -> Expected Winner: msg_exp_high (2200 INR) | Actual: {winner_exp.source_id} ({winner_exp.amount} INR)")
    print(f"  -> Rationale: {r_exp}")
    assert winner_exp.source_id == "msg_exp_high"
    assert winner_exp.amount == Decimal("2200")
    assert "higher debit estimate" in r_exp

    # Case B: Credit / Income conflict -> Conservative Lower Income
    inc_low = Claim(
        source_type="message", source_id="msg_inc_low", user_id="user_09", target_event_id=None,
        claim_type="salary_update", amount=Decimal("30000000"), currency="IDR",
        effective_date=date(2025, 6, 1), is_confirmed=True, confidence=Decimal("0.80"),
        raw_text="Base salary 30M", counterparty="Acme", sent_at="2025-05-01T10:00:00Z",
        direction="credit"
    )
    inc_high = Claim(
        source_type="message", source_id="msg_inc_high", user_id="user_09", target_event_id=None,
        claim_type="salary_update", amount=Decimal("35000000"), currency="IDR",
        effective_date=date(2025, 6, 1), is_confirmed=True, confidence=Decimal("0.80"),
        raw_text="Base salary 35M", counterparty="Acme", sent_at="2025-05-01T10:00:00Z",
        direction="credit"
    )
    winner_inc, r_inc = resolve_claim_pair(inc_low, inc_high)
    print(f"Credit Conflict: low={inc_low.amount} IDR vs high={inc_high.amount} IDR")
    print(f"  -> Expected Winner: msg_inc_low (30000000 IDR) | Actual: {winner_inc.source_id} ({winner_inc.amount} IDR)")
    print(f"  -> Rationale: {r_inc}")
    assert winner_inc.source_id == "msg_inc_low"
    assert winner_inc.amount == Decimal("30000000")
    assert "lower credit estimate" in r_inc
    print(">>> TEST 5 PASSED.\n")


def test_fix6_competing_claims_reduction():
    print("=================================================================")
    print("TEST 6: resolve_competing_claims Pre-Arbitration Orchestration")
    print("=================================================================")
    c1 = Claim(
        source_type="message", source_id="msg_a", user_id="user_02", target_event_id=None,
        claim_type="salary_update", amount=Decimal("35000000"), currency="IDR",
        effective_date=date(2025, 7, 15), is_confirmed=True, confidence=Decimal("0.95"),
        raw_text="Salary 35M", counterparty="Cobalt Systems", sent_at="2025-06-01T09:00:00Z"
    )
    c2 = Claim(
        source_type="message", source_id="msg_b", user_id="user_02", target_event_id=None,
        claim_type="general_informational", amount=Decimal("99999999"), currency="IDR",
        effective_date=date(2025, 7, 20), is_confirmed=True, confidence=Decimal("0.95"),
        raw_text="Info note", counterparty="Cobalt Systems", sent_at="2025-07-20T09:00:00Z"
    )
    c3 = Claim(
        source_type="message", source_id="msg_c", user_id="user_02", target_event_id=None,
        claim_type="salary_update", amount=Decimal("42750000"), currency="IDR",
        effective_date=date(2025, 8, 15), is_confirmed=True, confidence=Decimal("0.95"),
        raw_text="Salary increased to 42.75M", counterparty="Cobalt Systems", sent_at="2025-07-29T09:30:00Z"
    )

    winner, audit_trail = resolve_competing_claims([c1, c2, c3])
    print(f"Competing list: {[c.source_id for c in [c1, c2, c3]]}")
    for step in audit_trail:
        print(f"  Audit step: {step}")
    print(f"  -> Expected Winner: msg_c (42750000 IDR) | Actual: {winner.source_id} ({winner.amount} {winner.currency})")
    assert winner.source_id == "msg_c"
    assert winner.amount == Decimal("42750000")
    print(">>> TEST 6 PASSED.\n")


if __name__ == "__main__":
    test_fix1_counterparty_matching()
    test_fix2_sent_at_chronological_ordering()
    test_fix3_tier3_reachability()
    test_fix4_hard_guard_on_informational_claims()
    test_fix5_tier4_directional_fallback()
    test_fix6_competing_claims_reduction()
    print("ALL 6 ARBITRATION TESTS EXECUTED AND VERIFIED.")
