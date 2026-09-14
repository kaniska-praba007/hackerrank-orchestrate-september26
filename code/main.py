"""Main Stage 5 Entry Point for Buy or Wait Financial Decision Agent."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.extraction.claims import Claim
from code.orchestration.router import AuditOrchestrator
from code.planning.planner import ActionPlanner
from code.rendering.explainer import (
    render_explanation,
    verify_grounding_and_consistency,
)
from code.simulation.ledger import parse_date
from code.verification.verifier_orchestrator import Stage3Verifier

FIELDS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]


def load_csv(path: Path, columns: tuple[str, ...] | None = None) -> list[dict[str, str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if columns is None:
            return list(reader)
        return [{col: row[col] for col in columns} for row in reader]


def load_exchange_rates(path: Path) -> dict[tuple[str, str, str], Decimal]:
    rates: dict[tuple[str, str, str], Decimal] = {}
    if not path.exists():
        return rates
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            rates[(row["from_currency"], row["to_currency"], row["rate_date"])] = Decimal(row["rate"])
    return rates


def fmt(value: Decimal | str | None) -> str:
    if value is None:
        return "0"
    v = Decimal(str(value).replace(",", ""))
    v = v.quantize(Decimal("0.01")) if v.as_tuple().exponent < -2 else v
    f_str = format(v, "f")
    return f_str.rstrip("0").rstrip(".") if "." in f_str else f_str


def get_verified_events_and_summary(
    root: Path,
    dataset_dir: Path,
    exchange_rates: dict[tuple[str, str, str], Decimal],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cache_dir = root / "cache" / "verification"
    verified_path = cache_dir / "verified_events.json"
    summary_path = cache_dir / "verification_summary.json"

    if verified_path.exists() and summary_path.exists():
        verified_events = json.loads(verified_path.read_text(encoding="utf-8"))
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        return verified_events, summary

    # Otherwise run Stage 3 verifier
    normalized_path = root / "normalized_events.csv"
    if not normalized_path.exists():
        from code.normalization.amounts import rate_index
        from code.normalization.events import FIELDS, normalize_events
        from code.normalization.joins import image_index, message_index, profile_currency_index
        
        events = load_csv(dataset_dir / "financial_events.csv")
        profiles = load_csv(dataset_dir / "financial_profiles.csv")
        images = load_csv(dataset_dir / "images.csv")
        messages = load_csv(dataset_dir / "messages.csv", ("message_id", "related_event_id"))
        rates_data = load_csv(dataset_dir / "exchange_rates.csv")
        normalized_events, _ = normalize_events(
            events,
            profile_currency_index(profiles),
            image_index(images),
            message_index(messages),
            rate_index(rates_data),
        )
        with normalized_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(normalized_events)
    else:
        normalized_events = load_csv(normalized_path)

    extraction_cache_dir = root / "cache" / "extraction"
    img_claims_path = extraction_cache_dir / "extracted_image_claims.json"
    msg_claims_path = extraction_cache_dir / "extracted_message_claims.json"

    if not (img_claims_path.exists() and msg_claims_path.exists()):
        from code.extraction.run_stage2 import run_stage_2
        img_tuples, msg_objs, _ = run_stage_2(
            use_llm=True,
            dataset_dir=dataset_dir,
            cache_dir=extraction_cache_dir,
        )
        img_data = [c.to_dict() for c, _ in img_tuples]
        msg_data = [c.to_dict() for c in msg_objs]
        extraction_cache_dir.mkdir(parents=True, exist_ok=True)
        img_claims_path.write_text(json.dumps(img_data, indent=2), encoding="utf-8")
        msg_claims_path.write_text(json.dumps(msg_data, indent=2), encoding="utf-8")

    image_claims: list[Claim] = []
    if img_claims_path.exists():
        raw_imgs = json.loads(img_claims_path.read_text(encoding="utf-8"))
        image_claims = [Claim.from_dict(d) for d in raw_imgs]

    message_claims: list[Claim] = []
    if msg_claims_path.exists():
        raw_msgs = json.loads(msg_claims_path.read_text(encoding="utf-8"))
        message_claims = [Claim.from_dict(d) for d in raw_msgs]

    verifier = Stage3Verifier(
        normalized_events=normalized_events,
        exchange_rates=exchange_rates,
        image_claims=image_claims,
        message_claims=message_claims,
    )
    verified_events, summary = verifier.verify_and_build_ledger()

    cache_dir.mkdir(parents=True, exist_ok=True)
    verified_path.write_text(json.dumps(verified_events, indent=2, default=str), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    return verified_events, summary


def run(
    input_dir: Path,
    output_path: Path,
    requests_file: str = "requests.csv",
) -> list[dict[str, str]]:
    req_file_path = input_dir / requests_file if not Path(requests_file).is_absolute() else Path(requests_file)
    if not req_file_path.exists():
        req_file_path = ROOT / requests_file

    requests = load_csv(req_file_path)
    profiles_list = load_csv(input_dir / "financial_profiles.csv")
    profiles = {p["user_id"]: p for p in profiles_list}

    payment_options_list = load_csv(input_dir / "request_payment_options.csv")
    payment_options_by_req = defaultdict(list)
    for opt in payment_options_list:
        payment_options_by_req[opt["request_id"]].append(opt)

    exchange_rates = load_exchange_rates(input_dir / "exchange_rates.csv")

    # Load verified events and summary
    verified_events, summary = get_verified_events_and_summary(ROOT, input_dir, exchange_rates)

    events_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    events_by_id: dict[str, dict[str, Any]] = {}
    for evt in verified_events:
        u_id = evt.get("user_id", "")
        events_by_user[u_id].append(evt)
        e_id = evt.get("event_id", "")
        if e_id:
            events_by_id[e_id] = evt

    salary_streams = summary.get("resolved_salary_streams", {})

    planner = ActionPlanner(exchange_rates=exchange_rates)
    orchestrator = AuditOrchestrator(cache_dir=ROOT / "cache" / "orchestration")

    output_rows: list[dict[str, str]] = []
    grounding_audit_results: list[dict[str, Any]] = []

    for req in requests:
        req_id = req["request_id"]
        u_id = req["user_id"]
        profile = profiles.get(u_id, {})
        user_evts = events_by_user.get(u_id, [])
        req_options = payment_options_by_req.get(req_id, [])
        u_salary_stream = salary_streams.get(u_id)

        decision = planner.evaluate_request(
            request=req,
            user_profile=profile,
            user_events=user_evts,
            payment_options=req_options,
            salary_stream=u_salary_stream,
        )

        trace = decision.decision_trace
        trace["request_type"] = req.get("request_type", "")
        trace["desired_completion_date"] = req.get("desired_completion_date", "")

        explanation = render_explanation(trace, events_by_id)

        row = {
            "request_id": decision.request_id,
            "amount_safe_to_pay": fmt(decision.amount_safe_to_pay),
            "affordability_status": decision.affordability_status,
            "recommended_payment_method": decision.recommended_payment_method,
            "payment_plan": decision.payment_plan,
            "earliest_date_for_full_payment": decision.earliest_date_for_full_payment,
            "spending_changes_needed": decision.spending_changes_needed,
            "decision_explanation": explanation,
        }

        # 1. Default Grounding & Consistency Check (Unconditionally runs for all requests)
        is_grounded, ground_issues = verify_grounding_and_consistency(row, trace)

        # 2. Agentic Orchestration Router: Decide whether to add an EXTRA scrutiny pass
        user_conflicts_count = len([
            e for e in summary.get("audit_log", [])
            if e.get("event_id") in {x.get("event_id") for x in user_evts}
        ])
        orch_decision = orchestrator.route_and_audit(
            request=req,
            decision_trace=trace,
            num_candidates=len(req_options) + 2,
            conflicts_resolved_count=user_conflicts_count,
        )

        # 3. EXTRA Scrutiny Pass (Runs when requires_grounding_recheck=True OR risk_flag='elevated')
        if orch_decision.extra_pass_ran:
            extra_grounded, extra_issues = verify_grounding_and_consistency(row, trace)
            grounding_audit_results.append({
                "request_id": req_id,
                "extra_pass_ran": True,
                "is_grounded": extra_grounded,
                "risk_flag": orch_decision.risk_flag,
                "router_status": orch_decision.router_call_status,
                "reasoning": orch_decision.reasoning,
            })

        output_rows.append(row)

    orchestrator.save_log(ROOT / "orchestration_log.json")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(output_rows)

    return output_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Buy or Wait Financial Decision Agent")
    parser.add_argument("--input-dir", type=Path, default=ROOT / "dataset")
    parser.add_argument("--requests-file", default="requests.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "output.csv")
    args = parser.parse_args()

    # Safety check: Never write to dataset/output.csv
    out_resolved = args.output.resolve()
    dataset_out = (args.input_dir / "output.csv").resolve()
    if out_resolved == dataset_out:
        print(f"Error: Writing to dataset/output.csv is prohibited. Target: {out_resolved}", file=sys.stderr)
        sys.exit(1)

    run(
        input_dir=args.input_dir,
        output_path=args.output,
        requests_file=args.requests_file,
    )


if __name__ == "__main__":
    main()
