from __future__ import annotations

from collections import Counter
from typing import Iterable


def build_report(rows: Iterable[dict[str, str]], input_row_count: int, rate_misses: list[dict[str, str]]) -> dict:
    rows = list(rows)
    pending = [row["event_id"] for row in rows if row["amount_source"] == "pending_image_extraction"]
    fallback = [row["event_id"] for row in rows if row["cash_effective_date_source"] == "event_fallback"]
    source_counts = Counter(row["amount_source"] for row in rows)
    return {
        "input_row_count": input_row_count,
        "output_row_count": len(rows),
        "amount_source_counts": {
            "csv": source_counts["csv"],
            "pending_image_extraction": source_counts["pending_image_extraction"],
            "image_extracted": source_counts["image_extracted"],
        },
        "pending_image_extraction_event_ids": pending,
        "cash_effective_date_source_counts": {
            "settlement": sum(row["cash_effective_date_source"] == "settlement" for row in rows),
            "event_fallback": len(fallback),
        },
        "event_fallback_date_event_ids": fallback,
        "related_image_id_count": sum(bool(row["related_image_id"]) for row in rows),
        "related_message_event_count": sum(row["related_message_ids"] != "[]" for row in rows),
        "identity_home_currency_amount_count": sum(
            bool(row["amount_original"]) and row["amount_currency"] == row["home_currency"] for row in rows
        ),
        "converted_home_currency_amount_count": sum(
            bool(row["amount_original"]) and row["amount_currency"] != row["home_currency"] and bool(row["amount_home_currency"])
            for row in rows
        ),
        "missing_exchange_rate_match_count": len(rate_misses),
        "missing_exchange_rate_matches": rate_misses,
        "null_counts": {field: sum(row[field] == "" for row in rows) for field in rows[0]} if rows else {},
    }
