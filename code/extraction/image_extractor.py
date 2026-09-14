"""VLM Image Extractor for financial document images.

Extraction Rule for Invoices / Receipts / Bills:
Prefer the mathematically exact, tax-inclusive total (verified by summing subtotal +
itemized taxes) over any rounded or cash-denomination figure — regardless of which label
("Total", "Grand Total", "Amount Due", etc.) is attached to which number on a given document.
Do not pattern-match on label text alone.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field

from code.extraction.claims import Claim
from code.extraction.llm_client import LLMClient


class ImageExtractionSchema(BaseModel):
    event_id: str = Field(description="The financial event ID associated with this image (e.g. event_1442).")
    image_id: str = Field(description="The exact image ID being analyzed (e.g. image_01, image_02, etc.). Do not substitute the event ID or filename.")
    extracted_amount: str = Field(
        description="The exact numerical financial amount relevant to the event (e.g. net salary, invoice balance due, receipt total). Only numbers and decimal point, no commas or currency symbols. Preserve exact paise/decimal precision (e.g. 8528.10)."
    )
    currency: Literal["INR", "USD", "IDR", "ZAR", "EUR"] = Field(
        description="The currency of the extracted amount."
    )
    document_type: str = Field(
        description="Type of financial document (e.g. salary_slip, rent_receipt, grocery_bill, utility_bill, tax_invoice, clinic_bill)."
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score from 0.0 to 1.0 that this amount represents the correct settlement amount.",
    )
    rationale: str = Field(
        description="Brief justification for why this specific figure was chosen over other figures in the document."
    )


class ImageExtractor:
    def __init__(self, client: LLMClient | None = None):
        self.client = client or LLMClient()

    def extract_image_claim(
        self,
        image_path: Path,
        image_id: str,
        event_id: str,
        user_id: str,
        event_context: dict[str, str],
    ) -> tuple[Claim, bool]:
        """Extract a structured Claim from a PNG image file."""
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found at {image_path}")

        image_bytes = image_path.read_bytes()

        prompt = f"""You are an expert financial auditor examining document evidence for a financial event.
Document & Event Reference Details:
- Image ID: {image_id}
- Event ID: {event_id}
- User ID: {user_id}
- Event Description: {event_context.get('description', '')}
- Category: {event_context.get('category', '')}
- Direction: {event_context.get('direction', '')}
- Event Date: {event_context.get('event_date', '')}
- Settlement Date: {event_context.get('settlement_date', '')}

Task:
Extract the authoritative monetary amount that represents this specific transaction:
- Field 'image_id' in output must match '{image_id}'.
- Field 'event_id' in output must match '{event_id}'.
- For salary slips: Extract net take-home salary, not gross earnings or deductions.
- General Tax/Invoice Total Rule: Prefer the mathematically exact, tax-inclusive total (verified by summing subtotal + itemized taxes/CGST/SGST/VAT) over any rounded or cash-denomination figure — regardless of which label ('Total', 'Grand Total', 'Amount Due', etc.) is attached to which number on a given document. Do not pattern-match on label text alone. Preserve exact paise/decimal amounts (e.g., if item subtotal + taxes sums to 8528.10 and a rounded cash line says 8528, report 8528.10).
- For invoices / bills / rent: Extract the total payable / balance due for this specific transaction.
- For taxi / receipts: Extract total fare / grand total including taxes and surcharges.
- Return the exact numerical value as a clean string without commas or currency symbols.
- Identify the currency (INR, USD, IDR, ZAR, EUR).
"""

        parsed, is_hit = self.client.generate_structured(
            prompt=prompt,
            response_schema=ImageExtractionSchema,
            image_bytes=image_bytes,
            image_mime="image/png",
        )

        amount_clean = parsed.extracted_amount.replace(",", "").strip()
        amount_decimal = Decimal(amount_clean) if amount_clean else None

        eff_date = None
        if event_context.get("settlement_date"):
            eff_date = date.fromisoformat(event_context["settlement_date"][:10])
        elif event_context.get("event_date"):
            eff_date = date.fromisoformat(event_context["event_date"][:10])

        claim = Claim(
            source_type="image",
            source_id=image_id,
            user_id=user_id,
            target_event_id=event_id,
            claim_type="missing_amount",
            amount=amount_decimal,
            currency=parsed.currency,
            effective_date=eff_date,
            is_confirmed=True,
            confidence=Decimal(str(round(parsed.confidence, 2))),
            raw_text=f"[{parsed.document_type}] {parsed.rationale}",
        )

        return claim, is_hit
