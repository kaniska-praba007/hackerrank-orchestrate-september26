"""Deterministic fallback / baseline extractor when live LLM API is offline.
No hardcoded lookup tables are permitted. If an image cannot be parsed without
live VLM or local OCR, it is returned as UNRESOLVED (confidence=0.0).
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from code.extraction.claims import Claim


def extract_offline_image_claim(
    image_id: str,
    event_id: str,
    user_id: str,
    event_context: dict[str, str],
) -> Claim:
    """Offline image extractor without hardcoded lookup tables.
    
    If no local OCR engine or VLM is active, returns an UNRESOLVED claim
    with confidence 0.0, which triggers downstream fail-closed if material.
    """
    eff_date = None
    if event_context.get("settlement_date"):
        eff_date = date.fromisoformat(event_context["settlement_date"][:10])
    elif event_context.get("event_date"):
        eff_date = date.fromisoformat(event_context["event_date"][:10])

    return Claim(
        source_type="image",
        source_id=image_id,
        user_id=user_id,
        target_event_id=event_id,
        claim_type="missing_amount",
        amount=None,
        currency=event_context.get("currency"),
        effective_date=eff_date,
        is_confirmed=False,
        confidence=Decimal("0.0"),
        raw_text=f"Image {image_id} requires Gemini Pro Vision extraction (no credentials configured in environment).",
    )


def parse_offline_message_claim(msg: dict[str, str]) -> Claim:
    """Heuristic offline parser for message claims.
    
    Rules:
    1. Salary changes without explicit date default effective_date to message sent_at date.
    2. Informational messages (refund notes, unconfirmed bonuses) are classified as
       general_informational or unconfirmed_income and will NOT amend ledger state.
    """
    text = msg.get("message_text", "")
    user_id = msg.get("user_id", "")
    message_id = msg.get("message_id", "")
    sent_at_str = msg.get("sent_at", "")
    sent_at_date = date.fromisoformat(sent_at_str[:10]) if sent_at_str else None
    related_event_id = msg.get("related_event_id") or None
    if related_event_id and related_event_id.lower() == "none":
        related_event_id = None

    salary_match = re.search(
        r"(?:naik menjadi|gaji pokok yang dikonfirmasi adalah|monthly pay is|next salary is reduced to)\s+(INR|USD|IDR|ZAR|EUR)\s+([\d,.]+)",
        text,
        re.IGNORECASE,
    )
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", text)

    is_unconfirmed = bool(
        re.search(
            r"(masih menunggu|belum disetujui|still pending|can change until|isn’t withdrawable|belum disetujui|No off-season income)",
            text,
            re.IGNORECASE,
        )
    )
    is_cancellation = bool(re.search(r"(cancelled|dibatalkan|waived|refunded)", text, re.IGNORECASE))

    amt = None
    curr = None
    if salary_match:
        curr = salary_match.group(1).upper()
        raw_amt_str = salary_match.group(2).replace(",", "").rstrip(".")
        try:
            amt = Decimal(raw_amt_str)
        except Exception:
            amt = None

    # Explicit rule: If date is mentioned in text, use it; otherwise fallback to message sent_at date
    if date_match:
        eff_date = date.fromisoformat(date_match.group(1))
    else:
        eff_date = sent_at_date

    if is_unconfirmed:
        claim_type = "unconfirmed_income"
        is_confirmed = False
    elif is_cancellation:
        claim_type = "event_cancellation"
        is_confirmed = True
    elif salary_match:
        claim_type = "salary_update"
        is_confirmed = True
    else:
        claim_type = "general_informational"
        is_confirmed = True

    # Extract counterparty organization if identifiable
    counterparty = msg.get("source_type")
    cp_match = re.search(r"(?:di|from|at|here\.)\s+([A-Z][A-Za-z0-9\s]+?)(?:\s+telah|\s+has|\s+here|\s+payroll|\s+is|\.|\,)", text)
    if cp_match:
        counterparty = cp_match.group(1).strip()

    return Claim(
        source_type="message",
        source_id=message_id,
        user_id=user_id,
        target_event_id=related_event_id,
        claim_type=claim_type,
        amount=amt,
        currency=curr,
        effective_date=eff_date,
        is_confirmed=is_confirmed,
        confidence=Decimal("0.95") if amt else Decimal("0.85"),
        raw_text=text[:120],
        counterparty=counterparty,
        sent_at=sent_at_str or None,
    )
