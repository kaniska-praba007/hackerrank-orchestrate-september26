"""Stage 3 Full Deterministic Verifier Orchestrator."""
from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from code.extraction.claims import Claim
from code.verification.conflict_resolver import (
    resolve_competing_claims,
    resolve_event_conflict,
)
from code.verification.image_resolver import ImageClaimResolver
from code.verification.lifecycle_deduplicator import EventLifecycleDeduplicator

ROOT_DIR = Path(__file__).resolve().parents[2]


class Stage3Verifier:
    def __init__(
        self,
        normalized_events: list[dict[str, str]],
        exchange_rates: dict[tuple[str, str, str], Decimal],
        image_claims: list[Claim],
        message_claims: list[Claim],
    ):
        self.normalized_events = normalized_events
        self.rates = exchange_rates
        self.image_claims = image_claims
        self.message_claims = message_claims
        self.events_by_id = {e["event_id"]: dict(e) for e in normalized_events}

    def verify_and_build_ledger(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Orchestrate Stage 3 deterministic verification across all events and claims.
        
        Steps:
        1. Resolve image claims for missing amount events via ImageClaimResolver.
        2. Group all message/evidence claims by target_event_id and user_id.
        3. For events with multiple competing claims, call resolve_competing_claims first.
        4. Apply winning claim to baseline event via resolve_event_conflict.
        5. Run EventLifecycleDeduplicator to determine liquid cash flow eligibility.
        """
        # Step 1: Image claims resolution
        # Image claims are uniquely mapped by related_image_id / target_event_id
        image_claims_by_event = {c.target_event_id: c for c in self.image_claims if c.target_event_id}

        # Step 2: Group message claims by target_event_id and user_id
        message_claims_by_event: dict[str, list[Claim]] = defaultdict(list)
        user_salary_claims: dict[str, list[Claim]] = defaultdict(list)

        for c in self.message_claims:
            if c.target_event_id:
                message_claims_by_event[c.target_event_id].append(c)
            elif c.claim_type == "salary_update":
                user_salary_claims[c.user_id].append(c)

        verified_events: list[dict[str, Any]] = []
        arbitration_audit_log: list[dict[str, Any]] = []

        deduplicator = EventLifecycleDeduplicator(self.events_by_id)

        for event in self.normalized_events:
            evt_id = event["event_id"]
            current_event = dict(event)

            # Step 1: Missing amount resolution from image claim
            if current_event.get("amount_source") == "pending_image_extraction":
                img_claim = image_claims_by_event.get(evt_id)
                if img_claim and img_claim.is_confident() and img_claim.amount is not None:
                    current_event, _, _ = resolve_event_conflict(current_event, img_claim)
                else:
                    current_event["amount_source"] = "unresolved_claim"

            # Step 2 & 3: Competing claims pre-arbitration
            # Check if multiple claims target this event
            competing = message_claims_by_event.get(evt_id, [])
            if competing:
                # Orchestration: resolve_competing_claims called BEFORE resolve_event_conflict
                winning_claim, audit_trail = resolve_competing_claims(competing)
                if winning_claim:
                    current_event, is_amended, rationale = resolve_event_conflict(current_event, winning_claim)
                    if is_amended:
                        arbitration_audit_log.append({
                            "event_id": evt_id,
                            "winning_claim_id": winning_claim.source_id,
                            "audit_trail": audit_trail,
                            "rationale": rationale,
                        })

            # Step 5: Lifecycle evaluation
            lifecycle_meta = deduplicator.evaluate_lifecycle(current_event)
            current_event["cash_flow_multiplier"] = lifecycle_meta["cash_flow_multiplier"]
            current_event["lifecycle_pattern"] = lifecycle_meta["lifecycle_pattern"]
            current_event["audit_rationale"] = lifecycle_meta["audit_rationale"]

            verified_events.append(current_event)

        summary = {
            "total_verified_events": len(verified_events),
            "arbitrated_conflicts_count": len(arbitration_audit_log),
            "audit_log": arbitration_audit_log,
            "resolved_salary_streams": {
                u: resolve_competing_claims(claims)[0].to_dict()
                for u, claims in user_salary_claims.items()
                if claims
            },
        }

        return verified_events, summary
