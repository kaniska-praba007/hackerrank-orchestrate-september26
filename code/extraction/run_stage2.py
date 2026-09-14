"""Stage 2 Runner: Evidence Extraction Pipeline (Images + Messages)."""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
DATASET_DIR = ROOT_DIR / "dataset"
CACHE_DIR = ROOT_DIR / "cache" / "extraction"
RAW_DIR = CACHE_DIR / "raw_responses"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR.mkdir(parents=True, exist_ok=True)

from code.extraction.claims import Claim
from code.extraction.fallback_extractor import (
    extract_offline_image_claim,
    parse_offline_message_claim,
)
from code.extraction.image_extractor import ImageExtractor
from code.extraction.llm_client import LLMClient, get_usage_tracker
from code.extraction.message_parser import MessageParser


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def run_stage_2(
    use_llm: bool = True,
    model_name: str = "gemini-3.6-flash",
    dataset_dir: Path | None = None,
    cache_dir: Path | None = None,
) -> tuple[list[tuple[Claim, str]], list[Claim], dict]:
    d_dir = dataset_dir or DATASET_DIR
    c_dir = cache_dir or CACHE_DIR
    c_dir.mkdir(parents=True, exist_ok=True)
    events = {r["event_id"]: r for r in load_csv(d_dir / "financial_events.csv")}
    images = load_csv(d_dir / "images.csv")
    messages = load_csv(d_dir / "messages.csv")

    client = LLMClient(model_name=model_name, cache_dir=c_dir) if use_llm else None
    if client and not client.api_key:
        client = None

    img_extractor = ImageExtractor(client) if client else None
    msg_parser = MessageParser(client) if client else None

    # 1. Process 16 Images
    image_claims_with_source: list[tuple[Claim, str]] = []
    image_cache_hits = 0
    image_start = time.time()

    for img_row in images:
        img_id = img_row["image_id"]
        evt_id = img_row["related_event_id"]
        usr_id = img_row["user_id"]
        evt_ctx = events.get(evt_id, {})
        img_path = DATASET_DIR / "media" / "images" / f"{img_id}.png"

        if img_extractor:
            try:
                claim, is_hit = img_extractor.extract_image_claim(
                    image_path=img_path,
                    image_id=img_id,
                    event_id=evt_id,
                    user_id=usr_id,
                    event_context=evt_ctx,
                )
                if is_hit:
                    image_cache_hits += 1
                image_claims_with_source.append((claim, "live_api" if not is_hit else "live_api_cached"))
            except Exception as e:
                print(f"Warning: LLM image extraction failed for {img_id}: {e}", file=sys.stderr)
                claim = extract_offline_image_claim(img_id, evt_id, usr_id, evt_ctx)
                image_claims_with_source.append((claim, "fallback"))
        else:
            claim = extract_offline_image_claim(img_id, evt_id, usr_id, evt_ctx)
            image_claims_with_source.append((claim, "fallback"))

    image_duration = time.time() - image_start

    # 2. Process Messages in Batches of 35 messages
    message_claims: list[Claim] = []
    msg_cache_hits = 0
    msg_start = time.time()

    chunk_size = 35
    message_chunks = [messages[i:i + chunk_size] for i in range(0, len(messages), chunk_size)]

    if msg_parser:
        for chunk in message_chunks:
            try:
                claims_batch, is_hit = msg_parser.parse_messages_batch(chunk)
                if is_hit:
                    msg_cache_hits += 1
                message_claims.extend(claims_batch)
            except Exception as e:
                print(f"Warning: LLM message parsing failed for chunk: {e}", file=sys.stderr)
                for m in chunk:
                    message_claims.append(parse_offline_message_claim(m))
    else:
        for m in messages:
            message_claims.append(parse_offline_message_claim(m))

    msg_duration = time.time() - msg_start

    # Save output artifacts
    img_json_path = CACHE_DIR / "extracted_image_claims.json"
    msg_json_path = CACHE_DIR / "extracted_message_claims.json"

    img_json_path.write_text(
        json.dumps([c.to_dict() for c, _ in image_claims_with_source], indent=2), encoding="utf-8"
    )
    msg_json_path.write_text(
        json.dumps([c.to_dict() for c in message_claims], indent=2), encoding="utf-8"
    )

    stats = {
        "image_count": len(image_claims_with_source),
        "image_cache_hits": image_cache_hits,
        "image_duration_seconds": round(image_duration, 3),
        "message_count": len(message_claims),
        "message_cache_hits": msg_cache_hits,
        "message_duration_seconds": round(msg_duration, 3),
        "llm_used": bool(client is not None),
        "model_name": model_name,
        "usage_stats": get_usage_tracker(model_name).to_dict() if client else {},
    }

    return image_claims_with_source, message_claims, stats


def main():
    print("=== Running Stage 2: Evidence Extraction (Run 1 - Cold / Live API) ===")
    img_claims1, msg_claims1, stats1 = run_stage_2(use_llm=True)
    print(f"Run 1 completed in {stats1['image_duration_seconds'] + stats1['message_duration_seconds']}s")
    print(f"LLM used: {stats1['llm_used']} (Model: {stats1.get('model_name')})")
    print(f"Extracted {len(img_claims1)} image claims, {len(msg_claims1)} message claims.")
    print(f"Run 1 Usage Stats: {json.dumps(stats1.get('usage_stats', {}), indent=2)}")

    print("\n=== Running Stage 2: Evidence Extraction (Run 2 - Warm / 100% Cache Verification) ===")
    img_claims2, msg_claims2, stats2 = run_stage_2(use_llm=True)
    print(f"Run 2 completed in {stats2['image_duration_seconds'] + stats2['message_duration_seconds']}s")
    print(f"Cache Hits - Images: {stats2['image_cache_hits']}/{stats2['image_count']}, Messages: {stats2['message_cache_hits']}")
    print(f"Run 2 Usage Stats: {json.dumps(stats2.get('usage_stats', {}), indent=2)}")

    print("\n=== EXTRACTOR BREAKDOWN FOR ALL 16 IMAGES ===")
    for c, src in img_claims1:
        print(f"- {c.source_id} ({c.target_event_id}): amount={c.currency} {c.amount}, conf={c.confidence}, extractor={src}")

    print("\n=== RAW API RESPONSES FOR TARGET IMAGES (image_02, image_11, image_12) ===")
    target_ids = {"image_02", "image_11", "image_12"}
    for c, _ in img_claims1:
        if c.source_id in target_ids:
            print(f"\n--- {c.source_id} ({c.target_event_id}) ---")
            print(json.dumps(c.to_dict(), indent=2))


if __name__ == "__main__":
    main()
