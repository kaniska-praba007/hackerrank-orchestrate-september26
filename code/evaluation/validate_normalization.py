"""Independent structural validation for normalized_events.csv."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))
from normalization.events import FIELDS  # noqa: E402


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    normalized_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "normalized_events.csv"
    source = read(ROOT / "dataset" / "financial_events.csv")
    images = read(ROOT / "dataset" / "images.csv")
    messages = read(ROOT / "dataset" / "messages.csv")
    rows = read(normalized_path)
    errors: list[str] = []
    if not rows or list(rows[0]) != FIELDS:
        errors.append("normalized CSV header differs from the approved schema")
    if len(rows) != len(source):
        errors.append(f"row-count parity failed: source={len(source)}, normalized={len(rows)}")
    if len({row["event_id"] for row in rows}) != len(rows):
        errors.append("normalized event_id values are not unique")
    image_by_event = {row["related_event_id"]: row["image_id"] for row in images}
    message_ids = {row["message_id"] for row in messages}
    allowed_sources = {"csv", "pending_image_extraction", "image_extracted"}
    for row in rows:
        event_id = row["event_id"]
        if not row["cash_effective_date"] or row["cash_effective_date_source"] not in {"settlement", "event_fallback"}:
            errors.append(f"{event_id}: invalid effective-date fields")
        if row["amount_source"] not in allowed_sources:
            errors.append(f"{event_id}: invalid amount_source")
        if row["amount_home_currency"] and not row["amount_original"]:
            errors.append(f"{event_id}: amount_home_currency exists without amount_original")
        expected_image = image_by_event.get(event_id, "")
        if row["related_image_id"] != expected_image:
            errors.append(f"{event_id}: related_image_id referential mismatch")
        try:
            related_messages = json.loads(row["related_message_ids"])
        except json.JSONDecodeError:
            errors.append(f"{event_id}: related_message_ids is not JSON")
            related_messages = []
        if not isinstance(related_messages, list) or any(message_id not in message_ids for message_id in related_messages):
            errors.append(f"{event_id}: related_message_ids referential mismatch")
        if row["amount_source"] == "pending_image_extraction" and (row["amount_original"] or not row["related_image_id"]):
            errors.append(f"{event_id}: invalid pending image state")
    if errors:
        print("VALIDATION FAILED", file=sys.stderr)
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"VALIDATION PASSED: {len(rows)} normalized rows; all checked invariants hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
