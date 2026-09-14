"""Normalization stage only: no image/message extraction or financial decisions."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from normalization.amounts import rate_index
from normalization.events import FIELDS, normalize_events
from normalization.joins import image_index, message_index, profile_currency_index
from normalization.report import build_report


def read_csv(path: Path, columns: tuple[str, ...] | None = None) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if columns is None:
            return list(reader)
        # Retain only requested structural fields; callers do not inspect text.
        return [{column: row[column] for column in columns} for row in reader]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=Path(__file__).resolve().parents[1] / "dataset")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "normalized_events.csv")
    parser.add_argument("--report", type=Path, default=Path(__file__).resolve().parents[1] / "normalization_report.json")
    args = parser.parse_args()
    try:
        events = read_csv(args.input_dir / "financial_events.csv")
        profiles = read_csv(args.input_dir / "financial_profiles.csv")
        images = read_csv(args.input_dir / "images.csv")
        messages = read_csv(args.input_dir / "messages.csv", ("message_id", "related_event_id"))
        rates = read_csv(args.input_dir / "exchange_rates.csv")
        rows, rate_misses = normalize_events(
            events, profile_currency_index(profiles), image_index(images), message_index(messages), rate_index(rates),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader(); writer.writerows(rows)
        args.report.write_text(json.dumps(build_report(rows, len(events), rate_misses), indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"normalization failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
