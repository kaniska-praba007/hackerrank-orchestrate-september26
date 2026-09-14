"""Image Claim Resolver for Stage 3 Deterministic Verifier."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from code.extraction.claims import IMAGE_CONFIDENCE_THRESHOLD


class ImageClaimResolver:
    def __init__(self, claims_path: Path):
        self.claims_path = claims_path
        self.claims_by_event: dict[str, dict[str, Any]] = {}
        self.claims_by_image: dict[str, dict[str, Any]] = {}
        self._load_claims()

    def _load_claims(self) -> None:
        if not self.claims_path.exists():
            raise FileNotFoundError(f"Extracted image claims not found at {self.claims_path}")
        data = json.loads(self.claims_path.read_text(encoding="utf-8"))
        for item in data:
            target_evt = item.get("target_event_id")
            src_img = item.get("source_id")
            if target_evt:
                self.claims_by_event[target_evt] = item
            if src_img:
                self.claims_by_image[src_img] = item

    def resolve_image_event(
        self,
        event: dict[str, str],
        rates: dict[tuple[str, str, str], Decimal],
    ) -> tuple[dict[str, str], dict[str, Any]]:
        """Resolve a single pending_image_extraction event using verified Claim evidence.
        
        Returns (updated_event_dict, audit_metadata).
        """
        event_id = event["event_id"]
        image_id = event.get("related_image_id")
        claim = self.claims_by_event.get(event_id) or self.claims_by_image.get(image_id)

        updated = dict(event)
        audit_meta = {
            "event_id": event_id,
            "image_id": image_id,
            "status": "unresolved",
            "confidence": "0.0",
            "resolved_amount": None,
            "resolved_currency": None,
            "amount_home_currency": None,
            "rationale": None,
        }

        if not claim:
            updated["amount_source"] = "unresolved_claim"
            return updated, audit_meta

        conf_str = str(claim.get("confidence", "0.0"))
        confidence = Decimal(conf_str)
        audit_meta["confidence"] = conf_str
        audit_meta["rationale"] = claim.get("raw_text", "")

        # Strict Confidence Threshold Check (0.80)
        if confidence < IMAGE_CONFIDENCE_THRESHOLD or not claim.get("amount"):
            updated["amount_source"] = "unresolved_claim"
            return updated, audit_meta

        amt_str = str(claim["amount"])
        amt_decimal = Decimal(amt_str)
        curr = claim.get("currency") or event.get("amount_currency")
        home_curr = event["home_currency"]
        cash_date = event["cash_effective_date"]

        # Calculate Home Currency Amount
        amount_home = ""
        if curr == home_curr:
            amount_home = format(amt_decimal, "f")
        else:
            pair = (cash_date, curr, home_curr)
            rate = rates.get(pair)
            if rate is not None:
                amount_home = format(amt_decimal * rate, "f")

        updated["amount_original"] = format(amt_decimal, "f")
        updated["amount_currency"] = curr
        updated["amount_source"] = "image_extracted"
        updated["amount_home_currency"] = amount_home

        audit_meta["status"] = "resolved"
        audit_meta["resolved_amount"] = format(amt_decimal, "f")
        audit_meta["resolved_currency"] = curr
        audit_meta["amount_home_currency"] = amount_home

        return updated, audit_meta
