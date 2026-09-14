"""Message NLP extractor for financial notifications, employer updates, and provider messages."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Literal, Optional
from pydantic import BaseModel, Field

from code.extraction.claims import Claim
from code.extraction.llm_client import LLMClient


class SingleMessageExtraction(BaseModel):
    message_id: str = Field(description="The message_id being analyzed.")
    user_id: str = Field(description="The user_id.")
    related_event_id: Optional[str] = Field(default=None, description="The related event ID if present in the message record or text.")
    claim_type: Literal[
        "salary_update",
        "event_cancellation",
        "amount_adjustment",
        "date_reschedule",
        "unconfirmed_income",
        "unconfirmed_bonus",
        "general_informational",
    ] = Field(
        description="The classification of the financial claim made in the message."
    )
    extracted_amount: Optional[str] = Field(
        default=None,
        description="The new or adjusted numerical amount if mentioned (clean digits and decimal only, no symbols or commas).",
    )
    currency: Optional[Literal["INR", "USD", "IDR", "ZAR", "EUR"]] = Field(
        default=None,
        description="The currency of the extracted amount.",
    )
    effective_date: Optional[str] = Field(
        default=None,
        description="The date from which this change is effective (YYYY-MM-DD format).",
    )
    is_confirmed: bool = Field(
        description="True if this is an approved/confirmed change or fact; False if it is pending approval, unconfirmed bonus, speculative, or unearned.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score in the classification and extraction.",
    )
    summary: str = Field(description="Concise summary of the financial fact communicated.")


class BatchMessageExtractionSchema(BaseModel):
    extractions: List[SingleMessageExtraction]


class MessageParser:
    def __init__(self, client: LLMClient | None = None):
        self.client = client or LLMClient()

    def parse_messages_batch(
        self,
        messages: list[dict[str, str]],
    ) -> tuple[list[Claim], bool]:
        """Parse a batch of messages into typed Claim objects."""
        if not messages:
            return [], True

        formatted_messages = []
        for m in messages:
            formatted_messages.append(
                f"- message_id: {m.get('message_id')}\n"
                f"  user_id: {m.get('user_id')}\n"
                f"  related_event_id: {m.get('related_event_id') or 'none'}\n"
                f"  sent_at: {m.get('sent_at')}\n"
                f"  source_type: {m.get('source_type')}\n"
                f"  text: {m.get('message_text')}"
            )
        messages_block = "\n\n".join(formatted_messages)

        prompt = f"""You are an expert financial auditor extracting structured factual claims from user/employer/provider messages.
The messages may be in English, Indonesian, or other languages.

Messages to analyze:
{messages_block}

Instructions:
1. For each message, classify its financial claim type:
   - salary_update: employer updating regular/base salary amount or payroll date
   - event_cancellation: a pending or scheduled debit is cancelled, waived, or refunded
   - amount_adjustment: an expense/bill has been adjusted to a new amount
   - date_reschedule: payment or income date has moved to a new confirmed date
   - unconfirmed_income / unconfirmed_bonus: bonus/payout still pending performance evaluation, commission unearned, or payout pending
   - general_informational: general notifications not altering financial balance/events
2. Extract the exact numerical amount, currency, and effective date (YYYY-MM-DD) if stated.
3. Determine if the financial fact is CONFIRMED (approved/settled) or UNCONFIRMED (pending review, speculative).
"""

        parsed, is_hit = self.client.generate_structured(
            prompt=prompt,
            response_schema=BatchMessageExtractionSchema,
        )

        claims: list[Claim] = []
        for ext in parsed.extractions:
            amt = None
            if ext.extracted_amount:
                amt_str = ext.extracted_amount.replace(",", "").strip()
                if amt_str:
                    try:
                        amt = Decimal(amt_str)
                    except Exception:
                        amt = None

            eff_date = None
            if ext.effective_date:
                try:
                    eff_date = date.fromisoformat(ext.effective_date[:10])
                except Exception:
                    eff_date = None
            raw_msg = next((m for m in messages if m.get("message_id") == ext.message_id), {})
            raw_sent_at = raw_msg.get("sent_at", "")
            if not eff_date and raw_sent_at:
                eff_date = date.fromisoformat(raw_sent_at[:10])

            claims.append(
                Claim(
                    source_type="message",
                    source_id=ext.message_id,
                    user_id=ext.user_id,
                    target_event_id=ext.related_event_id if ext.related_event_id and ext.related_event_id.lower() != "none" else None,
                    claim_type=ext.claim_type,
                    amount=amt,
                    currency=ext.currency,
                    effective_date=eff_date,
                    is_confirmed=ext.is_confirmed,
                    confidence=Decimal(str(round(ext.confidence, 2))),
                    raw_text=ext.summary,
                    counterparty=raw_msg.get("source_type"),
                    sent_at=raw_sent_at or None,
                )
            )

        return claims, is_hit
