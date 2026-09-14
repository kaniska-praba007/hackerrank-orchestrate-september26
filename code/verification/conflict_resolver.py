"""Deterministic Conflict Resolver & Evidence Arbitrator for Stage 3."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from code.extraction.claims import (
    Claim,
    IMAGE_CONFIDENCE_THRESHOLD,
    MESSAGE_CONFIDENCE_THRESHOLD,
)

# Fix 2 & 4: Informational and Unconfirmed Income Types that can NEVER alter baseline commitments
INFORMATIONAL_OR_UNCONFIRMED_TYPES = {
    "general_informational",
    "unconfirmed_income",
    "unconfirmed_bonus",
}


def is_same_originating_source(a: Claim, b: Claim) -> bool:
    """Check if two claims originate from the exact same counterparty/issuer.
    
    Fix 1: Checks user_id, source_type, and non-empty matching counterparty identity.
    """
    if a.user_id != b.user_id:
        return False
    if a.source_type != b.source_type:
        return False
    if not a.counterparty or not b.counterparty:
        return False
    return a.counterparty.strip().lower() == b.counterparty.strip().lower()


def get_claim_direction(claim: Claim) -> str:
    """Determine the transaction direction for a claim ('credit' or 'debit').
    
    Prioritizes explicit claim.direction field; falls back to schema claim_type:
    - 'salary_update' -> 'credit' (income)
    - all other claim types (missing_amount, amount_adjustment, etc.) -> 'debit' (expense)
    """
    if claim.direction in ("credit", "debit"):
        return claim.direction
    if claim.claim_type == "salary_update":
        return "credit"
    return "debit"


def resolve_claim_pair(
    claim_a: Claim,
    claim_b: Claim,
) -> tuple[Claim, str]:
    """Arbitrate between two conflicting claims for the same financial subject.
    
    Hierarchy of Arbitration (problem_statement.md line 200):
    1. Explicit cancellation, settlement, or amendment
    2. Newer record from the same source (by actual sent_at timestamp)
    3. A settled event over an estimate or forecast (real field-based check)
    4. Financially safer interpretation when conflict cannot be resolved
    """
    # Guard applies ONLY to informational/unconfirmed income types (NOT "not is_confirmed")
    a_is_info = claim_a.claim_type in INFORMATIONAL_OR_UNCONFIRMED_TYPES
    b_is_info = claim_b.claim_type in INFORMATIONAL_OR_UNCONFIRMED_TYPES

    if a_is_info and not b_is_info:
        return claim_b, f"Claim {claim_b.source_id} wins: Claim {claim_a.source_id} is '{claim_a.claim_type}'."
    if b_is_info and not a_is_info:
        return claim_a, f"Claim {claim_a.source_id} wins: Claim {claim_b.source_id} is '{claim_b.claim_type}'."
    if a_is_info and b_is_info:
        return claim_a, f"Both claims are informational ({claim_a.claim_type}, {claim_b.claim_type}); neither alters commitments."

    # Tier 1: Explicit cancellation or amendment wins
    a_is_canc = claim_a.claim_type == "event_cancellation"
    b_is_canc = claim_b.claim_type == "event_cancellation"
    if a_is_canc and not b_is_canc:
        return claim_a, f"Tier 1: Explicit cancellation in {claim_a.source_id} supersedes {claim_b.source_id}."
    if b_is_canc and not a_is_canc:
        return claim_b, f"Tier 1: Explicit cancellation in {claim_b.source_id} supersedes {claim_a.source_id}."

    # Tier 2: Newer record from the same originating source (Actual sent_at timestamp)
    if is_same_originating_source(claim_a, claim_b) and (claim_a.is_confirmed == claim_b.is_confirmed):
        ts_a = claim_a.sent_at_datetime
        ts_b = claim_b.sent_at_datetime
        if ts_a and ts_b and ts_a != ts_b:
            if ts_a > ts_b:
                return claim_a, f"Tier 2: Newer record from same source {claim_a.counterparty} ({ts_a.isoformat()} > {ts_b.isoformat()})."
            else:
                return claim_b, f"Tier 2: Newer record from same source ({ts_b.isoformat()} > {ts_a.isoformat()})."

    # Tier 3: Confirmed / Settled status check (Confirmed supersedes unconfirmed estimate/forecast)
    if claim_a.is_confirmed and not claim_b.is_confirmed:
        return claim_a, f"Tier 3: Confirmed record {claim_a.source_id} supersedes unconfirmed estimate {claim_b.source_id}."
    if claim_b.is_confirmed and not claim_a.is_confirmed:
        return claim_b, f"Tier 3: Confirmed record {claim_b.source_id} supersedes unconfirmed estimate {claim_a.source_id}."

    # Tier 4: Financially safer interpretation (Per-claim direction evaluation)
    amt_a = claim_a.amount or Decimal("0")
    amt_b = claim_b.amount or Decimal("0")

    dir_a = get_claim_direction(claim_a)
    dir_b = get_claim_direction(claim_b)

    if dir_a != dir_b:
        # Direction mismatch anomaly: log and fall back to conservative higher expense
        import logging
        logging.warning(
            f"Direction mismatch anomaly between competing claims: {claim_a.source_id} ({dir_a}) vs {claim_b.source_id} ({dir_b})."
        )
        if amt_a >= amt_b:
            return claim_a, f"Tier 4: Direction mismatch anomaly ({dir_a} vs {dir_b}); defaulted to higher debit estimate ({claim_a.currency} {amt_a} >= {claim_b.currency} {amt_b})."
        return claim_b, f"Tier 4: Direction mismatch anomaly ({dir_a} vs {dir_b}); defaulted to higher debit estimate ({claim_b.currency} {amt_b} >= {claim_a.currency} {amt_a})."

    if dir_a == "credit":
        # For income / credit: conservative lower amount is safer
        if amt_a <= amt_b:
            return claim_a, f"Tier 4: Financially safer lower credit estimate ({claim_a.currency} {amt_a} <= {claim_b.currency} {amt_b})."
        return claim_b, f"Tier 4: Financially safer lower credit estimate ({claim_b.currency} {amt_b} <= {claim_a.currency} {amt_a})."
    else:
        # For expense / debit: conservative higher amount is safer
        if amt_a >= amt_b:
            return claim_a, f"Tier 4: Financially safer higher debit estimate ({claim_a.currency} {amt_a} >= {claim_b.currency} {amt_b})."
        return claim_b, f"Tier 4: Financially safer higher debit estimate ({claim_b.currency} {amt_b} >= {claim_a.currency} {amt_a})."


def resolve_competing_claims(claims: list[Claim]) -> tuple[Claim | None, list[str]]:
    """Arbitrate among multiple competing claims for the same target event or subject.
    
    Iteratively applies resolve_claim_pair across the list.
    Returns (winning_claim, audit_trail).
    """
    if not claims:
        return None, ["No claims to arbitrate."]
    if len(claims) == 1:
        return claims[0], [f"Single claim {claims[0].source_id} accepted."]

    audit_trail: list[str] = []
    winner = claims[0]
    for challenger in claims[1:]:
        prior_winner = winner
        winner, rationale = resolve_claim_pair(prior_winner, challenger)
        audit_trail.append(f"Pair ({prior_winner.source_id} vs {challenger.source_id}) -> {winner.source_id} won: {rationale}")

    return winner, audit_trail


def resolve_event_conflict(
    baseline_event: dict[str, Any],
    claim: Claim,
) -> tuple[dict[str, Any], bool, str]:
    """Arbitrate between a normalized baseline event and an extracted evidence Claim.
    
    Returns (updated_event, is_amended, rationale).
    """
    updated = dict(baseline_event)

    # Fix 4: Hard early-return guard for informational / unconfirmed income types
    if claim.claim_type in INFORMATIONAL_OR_UNCONFIRMED_TYPES:
        return updated, False, f"Claim {claim.source_id} is '{claim.claim_type}'; baseline event preserved unchanged."

    # Fix 1: Approved confidence threshold check (0.80 for images, 0.75 for messages)
    if not claim.is_confident():
        return updated, False, f"Claim {claim.source_id} confidence ({claim.confidence}) is below threshold; baseline preserved."

    # Tier 1: Explicit Cancellation
    if claim.claim_type == "event_cancellation":
        updated["status"] = "cancelled"
        updated["amount_original"] = "0"
        updated["amount_home_currency"] = "0"
        return updated, True, f"Tier 1: Event {baseline_event.get('event_id')} cancelled per explicit notice {claim.source_id}."

    # Tier 1: Missing Amount Image Resolution
    if claim.claim_type == "missing_amount" and claim.amount is not None:
        updated["amount_original"] = format(claim.amount, "f")
        if claim.currency:
            updated["amount_currency"] = claim.currency
        updated["amount_source"] = "image_extracted"
        return updated, True, f"Tier 1: Missing amount populated from document {claim.source_id} ({claim.currency} {claim.amount})."

    # Tier 2 & 3: Amount Adjustment on Existing Event
    if claim.claim_type == "amount_adjustment" and claim.amount is not None:
        event_status = baseline_event.get("status", "")
        # Tier 3: If baseline event is already settled and claim is unconfirmed, baseline wins
        if event_status == "settled" and not claim.is_confirmed:
            return updated, False, f"Tier 3: Settled event {baseline_event.get('event_id')} takes precedence over unconfirmed {claim.source_id}."

        updated["amount_original"] = format(claim.amount, "f")
        if claim.currency:
            updated["amount_currency"] = claim.currency
        return updated, True, f"Event amount amended to {claim.currency} {claim.amount} per verified notice {claim.source_id}."

    # Handle Date Reschedule
    if claim.claim_type == "date_reschedule" and claim.effective_date:
        updated["settlement_date"] = claim.effective_date.isoformat()
        updated["cash_effective_date"] = claim.effective_date.isoformat()
        return updated, True, f"Event date rescheduled to {claim.effective_date.isoformat()} per notice {claim.source_id}."

    return updated, False, "Baseline event preserved."
