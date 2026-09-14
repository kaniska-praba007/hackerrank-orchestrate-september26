"""Claim data models and serialization for Stage 2 evidence extraction."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

IMAGE_CONFIDENCE_THRESHOLD = Decimal("0.80")
MESSAGE_CONFIDENCE_THRESHOLD = Decimal("0.75")


@dataclass(frozen=True)
class Claim:
    source_type: Literal["image", "message"]
    source_id: str  # e.g. "image_01", "message_01"
    user_id: str
    target_event_id: str | None
    claim_type: str  # e.g. "missing_amount", "salary_update", "cancellation", "amount_adjustment", "date_change", "general_informational", "unconfirmed_income"
    amount: Decimal | None
    currency: str | None
    effective_date: date | None
    is_confirmed: bool
    confidence: Decimal
    raw_text: str
    counterparty: str | None = None  # Sender, employer, provider, or merchant identity
    sent_at: str | None = None  # Exact timestamp of evidence origination (e.g. 2025-07-29T09:30:00Z)
    direction: Literal["debit", "credit"] | None = None  # Transaction direction: 'debit' (expense) or 'credit' (income)

    def is_confident(self) -> bool:
        threshold = IMAGE_CONFIDENCE_THRESHOLD if self.source_type == "image" else MESSAGE_CONFIDENCE_THRESHOLD
        return self.confidence >= threshold

    @property
    def sent_at_datetime(self) -> datetime | None:
        if not self.sent_at:
            return None
        try:
            return datetime.fromisoformat(self.sent_at.replace("Z", "+00:00"))
        except Exception:
            return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "user_id": self.user_id,
            "target_event_id": self.target_event_id,
            "claim_type": self.claim_type,
            "amount": str(self.amount) if self.amount is not None else None,
            "currency": self.currency,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "is_confirmed": self.is_confirmed,
            "confidence": str(self.confidence),
            "raw_text": self.raw_text,
            "counterparty": self.counterparty,
            "sent_at": self.sent_at,
            "direction": self.direction,
            "is_confident": self.is_confident(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Claim:
        eff_date = None
        if data.get("effective_date"):
            eff_date = date.fromisoformat(data["effective_date"][:10])
        amt = None
        if data.get("amount") is not None:
            amt = Decimal(str(data["amount"]).replace(",", ""))
        return cls(
            source_type=data["source_type"],
            source_id=data["source_id"],
            user_id=data["user_id"],
            target_event_id=data.get("target_event_id"),
            claim_type=data["claim_type"],
            amount=amt,
            currency=data.get("currency"),
            effective_date=eff_date,
            is_confirmed=bool(data.get("is_confirmed", True)),
            confidence=Decimal(str(data.get("confidence", "1.0"))),
            raw_text=data.get("raw_text", ""),
            counterparty=data.get("counterparty"),
            sent_at=data.get("sent_at"),
            direction=data.get("direction"),
        )
