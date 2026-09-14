"""Run full Stage 3 deterministic verification across all 25,342 normalized events."""
from __future__ import annotations

import csv
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.extraction.claims import Claim
from code.verification.verifier_orchestrator import Stage3Verifier


def load_csv(path: Path) -> list[dict[str, str]]:
    with open(path, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_exchange_rates(path: Path) -> dict[tuple[str, str, str], Decimal]:
    rates: dict[tuple[str, str, str], Decimal] = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rates[(row["from_currency"], row["to_currency"], row["rate_date"])] = Decimal(row["rate"])
    return rates


def main() -> int:
    print("=================================================================")
    print("STAGE 3: FULL DETERMINISTIC VERIFIER & LEDGER BUILDER")
    print("=================================================================")
    
    normalized_path = ROOT / "normalized_events.csv"
    rates_path = ROOT / "dataset" / "exchange_rates.csv"
    img_claims_path = ROOT / "cache" / "extraction" / "extracted_image_claims.json"
    msg_claims_path = ROOT / "cache" / "extraction" / "extracted_message_claims.json"

    if not normalized_path.exists():
        print(f"Error: {normalized_path} not found.", file=sys.stderr)
        return 1

    normalized_events = load_csv(normalized_path)
    rates = load_exchange_rates(rates_path) if rates_path.exists() else {}
    
    image_claims: list[Claim] = []
    if img_claims_path.exists():
        raw_imgs = json.loads(img_claims_path.read_text(encoding="utf-8"))
        image_claims = [Claim.from_dict(d) for d in raw_imgs]
    
    message_claims: list[Claim] = []
    if msg_claims_path.exists():
        raw_msgs = json.loads(msg_claims_path.read_text(encoding="utf-8"))
        message_claims = [Claim.from_dict(d) for d in raw_msgs]

    print(f"Input Normalization Rows: {len(normalized_events)}")
    print(f"Input Image Claims:       {len(image_claims)}")
    print(f"Input Message Claims:     {len(message_claims)}")

    verifier = Stage3Verifier(
        normalized_events=normalized_events,
        exchange_rates=rates,
        image_claims=image_claims,
        message_claims=message_claims,
    )

    verified_events, summary = verifier.verify_and_build_ledger()

    # Fail-closed checks: ensure no unresolved claims silently fabricated
    unresolved_count = sum(1 for e in verified_events if e.get("amount_source") == "unresolved_claim")
    image_resolved_count = sum(1 for e in verified_events if e.get("amount_source") == "image_extracted")

    print(f"\nVerification Results:")
    print(f"  Total Verified Events:       {len(verified_events)}")
    print(f"  Image-Resolved Events:       {image_resolved_count} / {len(image_claims)}")
    print(f"  Unresolved Claims (Failed):  {unresolved_count}")
    print(f"  Arbitrated Conflicts:        {summary['arbitrated_conflicts_count']}")
    print(f"  Resolved User Salary Streams:{len(summary['resolved_salary_streams'])}")

    out_dir = ROOT / "cache" / "verification"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "verified_events.json").write_text(json.dumps(verified_events, indent=2, default=str), encoding="utf-8")
    (out_dir / "verification_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    assert len(verified_events) == 25342, f"Expected 25342 verified events, got {len(verified_events)}"
    assert image_resolved_count == 16, f"Expected 16 image events resolved, got {image_resolved_count}"
    assert unresolved_count == 0, f"Expected 0 unresolved claims, got {unresolved_count}"

    print("\nSTAGE 3 FULL-DATASET RUN COMPLETE: 25,342 events verified successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
