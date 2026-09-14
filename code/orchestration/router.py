"""Agentic Grounding & Scrutiny Router for Stage 5 Orchestration.

This router controls control-flow ONLY. It decides whether to add an EXTRA
grounding and consistency recheck pass for complex, elevated-risk requests.
It NEVER modifies, computes, or influences any financial amount, threshold,
plan, or output.csv field.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, Field

from code.extraction.llm_client import LLMClient

ROOT_DIR = Path(__file__).resolve().parents[2]
ORCHESTRATION_CACHE_DIR = ROOT_DIR / "cache" / "orchestration"
ORCHESTRATION_CACHE_DIR.mkdir(parents=True, exist_ok=True)


class RoutingDecisionSchema(BaseModel):
    requires_grounding_recheck: bool = Field(
        description="True if this request has financial complexity, multi-part payment plans, proposed spending adjustments, or tight margin headroom requiring an extra grounding verification pass."
    )
    risk_flag: Literal["standard", "elevated"] = Field(
        description="Risk tier: 'standard' for straightforward full payments or clear rejections, 'elevated' for complex multi-part plans, spending adjustments, or tight margin scenarios."
    )
    reasoning: str = Field(
        description="Concise one-sentence audit reasoning explaining the routing choice."
    )


@dataclass
class OrchestrationDecision:
    request_id: str
    requires_grounding_recheck: bool
    risk_flag: str
    reasoning: str
    extra_pass_ran: bool
    router_call_status: str  # "success" | "fallback_recheck_forced"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AuditOrchestrator:
    def __init__(
        self,
        client: LLMClient | None = None,
        cache_dir: Path = ORCHESTRATION_CACHE_DIR,
    ):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = client or LLMClient(model_name="gemini-3.6-flash", cache_dir=self.cache_dir)
        self.orchestration_log: list[dict[str, Any]] = []

    def route_and_audit(
        self,
        request: dict[str, Any],
        decision_trace: dict[str, Any],
        num_candidates: int = 1,
        conflicts_resolved_count: int = 0,
    ) -> OrchestrationDecision:
        """Route request for extra grounding scrutiny based on complexity and risk."""
        req_id = request.get("request_id", "")
        req_amt = request.get("requested_amount", "0")
        req_date = request.get("request_date", "")
        comp_date = request.get("desired_completion_date", "")
        partial_allowed = request.get("allows_partial_payment", "")
        req_type = request.get("request_type", "")

        rec_method = decision_trace.get("winning_method", "not_recommended")
        spending_changes = decision_trace.get("spending_changes_needed", "none")
        num_spending_adjs = len(spending_changes.split("|")) if spending_changes != "none" else 0

        # Normalized margin ratio: margin above floor divided by the minimum floor requirement
        min_proj_bal = Decimal(str(decision_trace.get("min_projected_balance", "0")).replace(",", ""))
        floor = Decimal(str(decision_trace.get("minimum_balance_floor", "0")).replace(",", ""))
        home_currency = str(decision_trace.get("home_currency", "INR"))
        margin = max(Decimal("0"), min_proj_bal - floor)
        margin_ratio = (margin / floor).quantize(Decimal("0.001")) if floor > Decimal("0") else Decimal("0.0")

        complexity_summary = {
            "num_candidate_plans_generated": num_candidates,
            "num_conflicting_claims_resolved_for_user": conflicts_resolved_count,
            "num_spending_adjustments_proposed": num_spending_adjs,
            "recommended_method": rec_method,
            "home_currency": home_currency,
            "margin_ratio_above_floor": f"{float(margin_ratio):.3f}",
            "margin_buffer_percentage": f"{float(margin_ratio) * 100:.1f}%",
        }

        prompt = f"""You are an expert financial audit orchestration router.
Evaluate the financial complexity and risk of the given decision to determine whether it warrants an EXTRA Stage 5 grounding/consistency verification pass beyond the standard baseline pass.

Request Details:
- request_id: {req_id}
- requested_amount: {req_amt}
- request_date: {req_date}
- desired_completion_date: {comp_date}
- allows_partial_payment: {partial_allowed}
- request_type: {req_type}

Decision Complexity Summary:
{json.dumps(complexity_summary, indent=2)}

Routing Guidelines:
- 'elevated' risk and requires_grounding_recheck=True:
  1. Requests requiring spending adjustments (num_spending_adjustments_proposed > 0).
  2. Requests with multi-payment schedules (installments or partial_payment).
  3. Requests where the normalized margin_ratio_above_floor is tight (< 0.20, or buffer < 20% of required floor).
  4. Complex multi-claim arbitration histories (num_conflicting_claims_resolved_for_user > 0).
- 'standard' risk and requires_grounding_recheck=False:
  1. Straightforward immediate full payment with ample normalized buffer ratio (>= 0.20).
  2. Clear unaffordable / wait requests with zero proposed spending modifications.

Provide:
1. requires_grounding_recheck: bool
2. risk_flag: "standard" | "elevated"
3. reasoning: Exactly one concise sentence explaining the routing decision.
"""
        # Call structured LLM with fail-safe fallback
        try:
            parsed, is_hit = self.client.generate_structured(
                prompt=prompt,
                response_schema=RoutingDecisionSchema,
            )
            req_recheck = bool(parsed.requires_grounding_recheck)
            risk_flag = str(parsed.risk_flag)
            reasoning = str(parsed.reasoning).strip()
            extra_ran = bool(req_recheck or risk_flag == "elevated")
            status = "success"

        except Exception as e:
            # FAIL-SAFE ON ROUTER FAILURE:
            # Treat failure as requires_grounding_recheck=True, run extra pass anyway
            req_recheck = True
            risk_flag = "elevated"
            reasoning = f"Fail-safe: Router call unavailable or timed out ({str(e)[:60]}); extra grounding recheck forced."
            extra_ran = True
            status = "fallback_recheck_forced"

        orch_decision = OrchestrationDecision(
            request_id=req_id,
            requires_grounding_recheck=req_recheck,
            risk_flag=risk_flag,
            reasoning=reasoning,
            extra_pass_ran=extra_ran,
            router_call_status=status,
        )

        self.orchestration_log.append(orch_decision.to_dict())
        return orch_decision

    def save_log(self, output_path: Path | None = None) -> None:
        path = output_path or (ROOT_DIR / "orchestration_log.json")
        path.write_text(json.dumps(self.orchestration_log, indent=2), encoding="utf-8")
