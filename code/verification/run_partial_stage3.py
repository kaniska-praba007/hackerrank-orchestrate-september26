"""Runner for Partial Stage 3 Verification (Image Claims + Lifecycle Deduplication)."""
from __future__ import annotations

import csv
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from code.normalization.amounts import rate_index
from code.verification.image_resolver import ImageClaimResolver
from code.verification.lifecycle_deduplicator import EventLifecycleDeduplicator


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def run_partial_stage3():
    events_raw = load_csv(ROOT_DIR / "normalized_events.csv")
    rates_raw = load_csv(ROOT_DIR / "dataset" / "exchange_rates.csv")
    rates = rate_index(rates_raw)
    claims_path = ROOT_DIR / "cache" / "extraction" / "extracted_image_claims.json"

    events_by_id = {e["event_id"]: e for e in events_raw}

    # 1. Run Image Claim Resolver
    resolver = ImageClaimResolver(claims_path)
    image_resolved_rows = []
    image_audit_reports = []

    for event in events_raw:
        if event["amount_source"] == "pending_image_extraction" or event["related_image_id"]:
            resolved_event, audit = resolver.resolve_image_event(event, rates)
            events_by_id[event["event_id"]] = resolved_event
            image_resolved_rows.append(resolved_event)
            image_audit_reports.append(audit)

    # 2. Run Event Lifecycle Deduplicator
    deduplicator = EventLifecycleDeduplicator(events_by_id)
    linked_audit_reports = []

    for event in events_raw:
        if event["linked_event_id"]:
            lifecycle_audit = deduplicator.evaluate_lifecycle(events_by_id[event["event_id"]])
            parent_event = events_by_id.get(event["linked_event_id"], {})
            linked_audit_reports.append({
                "child": events_by_id[event["event_id"]],
                "parent": parent_event,
                "lifecycle": lifecycle_audit,
            })

    return image_resolved_rows, image_audit_reports, linked_audit_reports


def main():
    image_rows, image_audits, linked_audits = run_partial_stage3()

    print(f"=== 1. VERIFIED IMAGE CLAIMS RESOLVER ({len(image_rows)} events) ===")
    for r in image_rows:
        print(f"- {r['event_id']} ({r['related_image_id']}): original={r['amount_currency']} {r['amount_original']} | home={r['home_currency']} {r['amount_home_currency']} | src={r['amount_source']}")

    print(f"\n=== 2. EVENT LIFECYCLE DEDUPLICATOR ({len(linked_audits)} linked events) ===")
    for item in linked_audits:
        c = item["child"]
        p = item["parent"]
        l = item["lifecycle"]
        print(f"- Child {c['event_id']} ({c['event_type']}, {c['status']}, {c['direction']}, {c['amount_currency']} {c['amount_original']}) -> Parent {p.get('event_id')} ({p.get('event_type')}, {p.get('status')}) | multiplier={l['cash_flow_multiplier']} | pattern={l['lifecycle_pattern']}")


if __name__ == "__main__":
    main()
