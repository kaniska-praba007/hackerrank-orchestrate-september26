"""Event Lifecycle Deduplicator for Stage 3 Deterministic Verifier."""
from __future__ import annotations

from decimal import Decimal
from typing import Any


class EventLifecycleDeduplicator:
    def __init__(self, events_by_id: dict[str, dict[str, str]]):
        self.events_by_id = events_by_id

    def evaluate_lifecycle(self, event: dict[str, str]) -> dict[str, Any]:
        """Evaluate the lifecycle state, liquid cash flow eligibility, and audit classification.
        
        Returns audit dict with:
        - cash_flow_multiplier: Decimal (1.0 = full cash flow impact, 0.0 = zero cash impact)
        - lifecycle_pattern: str describing the exact empirical pattern
        - audit_rationale: str explaining the financial reason
        """
        event_id = event["event_id"]
        linked_id = event.get("linked_event_id", "")
        direction = event.get("direction", "")
        status = event.get("status", "")
        event_type = event.get("event_type", "")

        # 1. Non-cash events (e.g. portfolio valuations) are NEVER liquid cash
        if direction == "non_cash" or event_type == "investment_valuation":
            return {
                "event_id": event_id,
                "linked_event_id": linked_id,
                "cash_flow_multiplier": Decimal("0.0"),
                "lifecycle_pattern": "non_cash_valuation",
                "audit_rationale": "Unrealized investment valuation has zero impact on liquid cash balance.",
            }

        # 2. Cancelled or Failed events produce ZERO cash impact
        if status in {"cancelled", "failed"}:
            return {
                "event_id": event_id,
                "linked_event_id": linked_id,
                "cash_flow_multiplier": Decimal("0.0"),
                "lifecycle_pattern": f"{status}_event",
                "audit_rationale": f"Event status is '{status}'; no cash movement occurred or will clear.",
            }

        # 3. Pending Incoming Credits (e.g. pending merchant refunds, unconfirmed prizes)
        if status == "pending" and direction == "credit":
            return {
                "event_id": event_id,
                "linked_event_id": linked_id,
                "cash_flow_multiplier": Decimal("0.0"),
                "lifecycle_pattern": "pending_credit_unearned",
                "audit_rationale": "Pending incoming credit is unearned/unsettled; conservative accounting excludes it from available cash.",
            }

        # 4. Check Linked Event Relationships (Parent-Child Lifecycle)
        if linked_id:
            parent = self.events_by_id.get(linked_id)
            if parent:
                p_type, p_status, p_dir = parent.get("event_type"), parent.get("status"), parent.get("direction")
                c_type, c_status, c_dir = event_type, status, direction

                # Pattern 1: Settled Expense -> Settled Refund / Reimbursement
                if p_dir == "debit" and p_status == "settled" and c_type == "refund" and c_status == "settled" and c_dir == "credit":
                    return {
                        "event_id": event_id,
                        "linked_event_id": linked_id,
                        "cash_flow_multiplier": Decimal("1.0"),
                        "lifecycle_pattern": "settled_refund_reimbursement",
                        "audit_rationale": "Settled refund/reimbursement is a valid chronological cash credit offsetting earlier debit.",
                    }

                # Pattern 3: Cancelled Pre-Auth -> Settled Purchase (Child perspective)
                if p_status == "cancelled" and c_status == "settled" and c_dir == "debit":
                    return {
                        "event_id": event_id,
                        "linked_event_id": linked_id,
                        "cash_flow_multiplier": Decimal("1.0"),
                        "lifecycle_pattern": "settled_purchase_replacing_auth",
                        "audit_rationale": "Settled card purchase is the authoritative cash debit replacing cancelled pre-authorization.",
                    }

                # Pattern 5: Failed Bill Payment -> Scheduled Retry (Child perspective)
                if p_status == "failed" and c_status == "scheduled" and c_dir == "debit":
                    return {
                        "event_id": event_id,
                        "linked_event_id": linked_id,
                        "cash_flow_multiplier": Decimal("1.0"),
                        "lifecycle_pattern": "scheduled_retry_after_failed_attempt",
                        "audit_rationale": "Scheduled retry debit is an active committed future cash outflow replacing failed attempt.",
                    }

                # Pattern 6: Settled Charge -> Duplicate Pending Charge (Child perspective)
                if p_status == "settled" and c_status == "pending" and c_dir == "debit":
                    return {
                        "event_id": event_id,
                        "linked_event_id": linked_id,
                        "cash_flow_multiplier": Decimal("1.0"),
                        "lifecycle_pattern": "duplicate_pending_charge_reserved",
                        "audit_rationale": "Pending duplicate debit is reserved as an active cash outflow by default under conservative policy.",
                    }

                # Pattern 7: Investment Purchase -> Investment Sale Proceeds
                if p_type == "investment_purchase" and c_type == "investment_sale" and c_status == "settled" and c_dir == "credit":
                    return {
                        "event_id": event_id,
                        "linked_event_id": linked_id,
                        "cash_flow_multiplier": Decimal("1.0"),
                        "lifecycle_pattern": "settled_investment_sale_proceeds",
                        "audit_rationale": "Settled investment sale proceeds represent valid realized chronological cash credit.",
                    }

        # 5. Standard Settled or Scheduled Cash Flow
        return {
            "event_id": event_id,
            "linked_event_id": linked_id,
            "cash_flow_multiplier": Decimal("1.0"),
            "lifecycle_pattern": f"standard_{status}_{direction}",
            "audit_rationale": f"Standard {status} {direction} counts fully toward financial ledger.",
        }
