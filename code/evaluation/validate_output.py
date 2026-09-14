"""Structural submission validator; exits non-zero on contract violations."""
from __future__ import annotations

import csv
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIELDS = ["request_id", "amount_safe_to_pay", "affordability_status", "recommended_payment_method", "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed", "decision_explanation"]
STATUSES = {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"}
METHODS = {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}


def read(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "output.csv"
    expected = read(ROOT / "dataset" / "requests.csv")
    rows = read(output)
    errors: list[str] = []
    if not rows or list(rows[0]) != FIELDS:
        errors.append("header must contain the exact required fields in order")
    if [r["request_id"] for r in rows] != [r["request_id"] for r in expected]:
        errors.append("rows must appear once and in requests.csv order")
    by_request = {r["request_id"]: r for r in expected}
    profiles = {r["user_id"]: r for r in read(ROOT / "dataset" / "financial_profiles.csv")}
    options = read(ROOT / "dataset" / "request_payment_options.csv")
    option_ids = {(r["request_id"], r["payment_option_id"]): r for r in options}
    for row in rows:
        request = by_request.get(row["request_id"])
        if not request:
            continue
        try:
            safe, asked = Decimal(row["amount_safe_to_pay"]), Decimal(request["requested_amount"])
            if not Decimal("0") <= safe <= asked:
                errors.append(f"{row['request_id']}: amount_safe_to_pay out of bounds")
        except Exception:
            errors.append(f"{row['request_id']}: invalid amount_safe_to_pay")
        if row["affordability_status"] not in STATUSES or row["recommended_payment_method"] not in METHODS:
            errors.append(f"{row['request_id']}: invalid status or method")
        if row["affordability_status"] == "affordable_now" and row["earliest_date_for_full_payment"] != request["request_date"]:
            errors.append(f"{row['request_id']}: affordable_now requires request-date earliest full payment")
        if row["recommended_payment_method"] == "not_recommended" and row["payment_plan"] != "none":
            errors.append(f"{row['request_id']}: not_recommended requires payment_plan=none")
        changes = [] if row["spending_changes_needed"] == "none" else row["spending_changes_needed"].split("|")
        if len(changes) > 3 or any(not (x.startswith("stop:") or x.startswith("reduce_to:")) for x in changes):
            errors.append(f"{row['request_id']}: invalid spending changes")
        if row["recommended_payment_method"] == "partial_payment":
            parts = row["payment_plan"].split("|")
            if len(parts) != 2 or not (Decimal("0") < safe < asked):
                errors.append(f"{row['request_id']}: partial plan must have two payments and partial safe amount")
            elif Decimal(parts[0].split(":", 1)[1]) != safe:
                errors.append(f"{row['request_id']}: first partial payment must equal amount_safe_to_pay")
    if errors:
        print("INVALID OUTPUT", file=sys.stderr)
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"PASS: {len(rows)} rows meet structural output invariants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
