"""Exact-field regression gate for the public solved examples."""
from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "dataset"
MAIN = ROOT / "code" / "main.py"
FIELDS = ["request_id", "amount_safe_to_pay", "affordability_status", "recommended_payment_method", "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed", "decision_explanation"]
NUMERIC = {"amount_safe_to_pay"}


def normalized(field: str, value: str) -> str:
    if field in NUMERIC and value:
        return format(Decimal(value).normalize(), "f")
    return value.strip()


def main() -> int:
    with tempfile.TemporaryDirectory() as folder:
        output = Path(folder) / "samples_output.csv"
        command = [sys.executable, str(MAIN), "--requests-file", "sample_requests.csv", "--output", str(output)]
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        if result.returncode:
            print(result.stderr or result.stdout, file=sys.stderr)
            return result.returncode
        expected = list(csv.DictReader((DATASET / "sample_requests.csv").open(encoding="utf-8-sig", newline="")))
        actual = list(csv.DictReader(output.open(encoding="utf-8-sig", newline="")))
    if len(actual) != len(expected):
        print(f"row count mismatch: expected {len(expected)}, got {len(actual)}", file=sys.stderr)
        return 1
    for wanted, got in zip(expected, actual):
        for field in FIELDS:
            if normalized(field, wanted[field]) != normalized(field, got[field]):
                print(f"{wanted['request_id']}: {field} mismatch", file=sys.stderr)
                print(f"  expected: {wanted[field]!r}", file=sys.stderr)
                print(f"  actual:   {got[field]!r}", file=sys.stderr)
                return 1
    print(f"PASS: {len(expected)} sample requests match every required field")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
