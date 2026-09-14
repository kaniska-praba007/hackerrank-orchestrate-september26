# Architecture & Design Decisions: "Buy or Wait?" Financial Decision Agent

This document serves as the consolidated, immutable source of truth for all confirmed architectural, financial, and algorithmic design decisions across all stages of the project.

---

## 1. Pipeline Architecture & Execution Boundaries
- **5-Stage Deterministic Pipeline**:
  - **Stage 1**: Event Normalization (`normalized_events.csv`, 25,342 rows).
  - **Stage 2**: Multimodal Evidence Extraction (Live `gemini-3.6-flash` extraction for 16 PNG images and 215 messages, backed by SHA-256 disk caching).
  - **Stage 3**: Deterministic Verifier & Conflict Resolver (4-tier arbitration, image claim resolution, lifecycle deduplication).
  - **Stage 4**: Simulator & Action Planner (90-day daily balance forecast, generic recurrence modeling, plan generator, spending optimizer, strict 6-tier ranking).
  - **Stage 5**: Grounded Renderer & Entrypoint (Deterministic explanation generation from `DecisionTrace`, root `output.csv` writer, parity validation).
- **Submission Entry Point (`code/main.py`)**:
  - `code/main.py` is the official top-level CLI entry point for the submission (invoked by `python code/main.py` and tested by `code/evaluation/regress_samples.py`).
  - Evidence lookups such as `code/evidence_amounts.json` serve as an event_id-keyed reference/cache artifact, while runtime multimodal extraction dynamically processes documents via the live VLM pipeline.
  - Root `output.csv` must be generated dynamically from runtime execution; `dataset/output.csv` must never be modified.
  - No hardcoded request IDs, sample labels, or synthetic test answers in production logic.

---

## 2. Output Schema & Invariants
- **Root `output.csv` Schema**: Exactly 8 columns in strict order:
  1. `request_id`
  2. `amount_safe_to_pay`
  3. `affordability_status` (`affordable_now`, `affordable_with_plan`, `affordable_later`, `not_affordable`)
  4. `recommended_payment_method` (`full_payment`, `partial_payment`, `installments`, `wait`, `not_recommended`)
  5. `payment_plan` (Formatted date:amount schedule or `"none"`)
  6. `earliest_date_for_full_payment` (`YYYY-MM-DD` or `""` empty string if unsafe; never `"none"`)
  7. `spending_changes_needed` (Formatted string e.g. `reduce_to:evt_id:amt|stop:evt_id` or `"none"`)
  8. `decision_explanation` (Plaintext explanation synthesized deterministically from `DecisionTrace`)
- **`payment_plan` Formatting Rules (Ground-Truth Verified)**:
  - `"none"` applies **exclusively** when `recommended_payment_method` is `not_recommended` (e.g. sample rows `request_05`, `request_10`, `request_14`, `request_15`, `request_20`, `request_24`, `request_25`).
  - For `full_payment` and `wait`, `payment_plan` is a single `<YYYY-MM-DD>:<amount>` entry (confirmed by `request_01`, `request_09`, `request_16` for `full_payment`, and `request_03`, `request_04`, `request_08`, `request_13`, `request_18`, `request_23` for `wait`).
  - For `partial_payment`, `payment_plan` contains exactly two chronological entries (`<request_date>:<safe_amt>|<completion_date>:<rem_amt>`) summing to `requested_amount` (confirmed by `request_19`).
  - For `installments`, `payment_plan` copies the verbatim provider schedule from `request_payment_options.csv` (confirmed by `request_02`, `request_07`, `request_12`, `request_17`, `request_22`).
- **Safety Floors**:
  - Minimum buffer floor per user currency: INR 5,000 / IDR 1,000,000.
  - Account balance must never violate the floor on any day $t \in [t_{\text{req}}, t_{\text{req}} + 90]$.
- **`amount_safe_to_pay` Invariants**:
  - If `affordable_now`: `amount_safe_to_pay == requested_amount`.
  - If `affordable_with_plan` (partial / installments): safe immediate payment amount.
  - If `not_affordable` / `affordable_later` (`wait`): `amount_safe_to_pay == 0.00` (or safe immediate partial if applicable).
- **Wait Schedule & Deadline Consistency Rule**:
  - `wait` candidates are scheduled strictly on `earliest_date_for_full_payment` (`earliest_full_date`).
  - If `earliest_date_for_full_payment` falls after `desired_completion_date` (as in `request_28`, `request_33`, `request_45`), the request cannot be safely completed by the deadline and falls back to `not_recommended` with `payment_plan: none`.
  - When `wait` is recommended, `payment_plan`, `earliest_date_for_full_payment`, and `decision_explanation` dates are guaranteed to match identically.
- **Ineligible Accepted Payment Methods (`request_133`)**:
  - When immediate capacity `amount_safe_to_pay == requested_amount` but the user's accepted payment methods exclude `full_payment` and the merchant prohibits `partial_payment`, the request falls back to `not_recommended`.
  - The explanation renderer uses the fallback template `"Do not make this payment by <deadline>. None of the available options keeps the <floor> minimum protected."`, avoiding the contradictory "cannot be completed safely within 90 days" phrasing.

---

## 3. Stage 1: Event Normalization Invariants & Rules
- **Null / Missing Value Sentinel**:
  - Empty strings `""` are used for optional/missing fields (e.g. `merchant`, `description`, `linked_event_id`), NEVER `"null"`, `"None"`, or `"N/A"`.
- **Date & Timestamp Invariants**:
  - Standardized to ISO-8601 (`YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SSZ`).
  - `cash_effective_date` logic: `settlement_date` if present, else `authorization_date` (or `scheduled_date` for scheduled events).
- **Exchange Rates & Currency Conversion**:
  - Converted using `dataset/exchange_rates.csv` with exact `(from_currency, to_currency, rate_date)` match, falling back to the nearest prior available rate.
  - All amounts converted using Python `Decimal` with rounding to 2 decimal places.
- **Dataset Invariant**: Exactly 25,342 normalized rows produced and verified by `validate_normalization.py`.

---

## 4. Stage 2: Multimodal Evidence Extraction
- **Live VLM Model**: `gemini-3.6-flash` via `google.genai` SDK with automatic rate-limit backoff and persistent disk caching in `cache/extraction/`.
- **Extraction Precision Rule (Tax-Inclusive Mathematical Total)**:
  - Prefer the mathematically exact, tax-inclusive total (verified by summing subtotal + itemized taxes like SGST/CGST) over any integer cash-denomination or rounded total, regardless of document label text ("Grand Total", "Total", "Amount Due", etc.).
  - Exact paise/cents decimal preservation (e.g. `8528.10` for `image_07`).
- **Approved Confidence Thresholds**:
  - Image claims: `0.80` (`IMAGE_CONFIDENCE_THRESHOLD`).
  - Message claims: `0.75` (`MESSAGE_CONFIDENCE_THRESHOLD`).
  - Implemented strictly in `Claim.is_confident()` branching by `source_type`.

---

## 5. Stage 3: Deterministic Verifier & Evidence Arbitration
- **Arbitration Hierarchy (problem_statement.md line 200)**:
  1. **Tier 1 (Explicit Cancellation / Amendment)**: Explicit notices (`event_cancellation`, `missing_amount`) supersede unamended baselines.
  2. **Tier 2 (Newer Record from Same Source)**: When two claims share originating counterparty (`is_same_originating_source`), the claim with the newer ISO `sent_at` timestamp wins.
  3. **Tier 3 (Settled vs Estimate)**: Confirmed claims (`is_confirmed=True`) supersede unconfirmed forecasts/estimates (`is_confirmed=False`). Settled baseline events take precedence over unconfirmed adjustments.
  4. **Tier 4 (Financially Safer Directional Fallback)**:
     - **Credit / Income**: Conservative lower amount (`min(amt_a, amt_b)`).
     - **Debit / Expense**: Conservative higher amount (`max(amt_a, amt_b)`).
     - Driven by explicit `Claim.direction` (`credit` vs `debit`) with fallback to schema `claim_type` (`salary_update` $\rightarrow$ `credit`).
     - Direction mismatches are logged as data anomalies and default to conservative debit behavior.
- **Informational Claims Early-Return Guard**:
  - `claim_type` in `{"general_informational", "unconfirmed_income", "unconfirmed_bonus"}` can **never** alter baseline financial commitments or ledger balances, regardless of confidence or confirmation flags.
- **Counterparty Originating Source Matching**:
  - `is_same_originating_source` matches `user_id`, `source_type`, and non-empty case-insensitive `counterparty` (e.g. `"Cobalt Systems"` == `"cobalt systems"`).
- **Competing Claims Pre-Resolution**:
  - When multiple claims target the same event or salary stream, `resolve_competing_claims` reduces them pairwise via `resolve_claim_pair` before `resolve_event_conflict` is applied to the baseline event.
- **Event Lifecycle Deduplication (6 Patterns)**:
  - Pattern 1 (Settled + Pending Duplicate): Settle active, pending multiplier = 0.0.
  - Pattern 2 (Auth + Settle): Settle active, auth multiplier = 0.0.
  - Pattern 3 (Refund + Reversal): Net credit/debit adjustment.
  - Pattern 4 (Reversal / Cancelled): Multiplier = 0.0.
  - Pattern 5 (Account Transfer Pair): Net internal transfer = 0.0.
  - Pattern 6 (Duplicate Pending Charge without cancellation): Reserved as real pending debit (multiplier = 1.0) by default.

---

## 6. Stage 4: Simulation, Recurrence & Action Planning
- **Recurrence Detection & Projection**:
  - **Salary / Regular Income Streams**: Grouped by `(category="salary", direction="credit")`. Uses the Stage 3 verified/arbitrated salary stream (`resolved_salary_streams`) when available to project future payroll credits from the last known date.
  - **All Other Recurring Commitments (Bills, Subscriptions, Utilities, Rent, etc.)**: Grouped strictly by exact `(description, category, direction)` matching $\ge 2$ settled historical events with a regular cadence check ($\ge 50\%$ interval regularity).
  - **Conservative Amount Selection**:
    - Variable Essential / Non-essential Debits: Conservative maximum historical debit (`max(amounts)`).
    - Credits / Income: Conservative minimum historical credit (`min(amounts)`).
  - **Projection Horizon**: Extrapolates forward across the 90-day simulation window $[t_{\text{req}}, t_{\text{req}} + 90]$.
- **`earliest_date_for_full_payment`**:
  - Calculated strictly against baseline cash capacity **without** optional spending adjustments.
  - Returns `YYYY-MM-DD` if achievable within 90 days; returns empty string `""` if not safely achievable (never `"none"` or `null`).
- **Spending Adjustment Optimizer**:
  - Generates candidate adjustments on flexible recurring debits (`subscription`, discretionary).
  - Supported actions: `stop:<event_id>` (complete pause) and `reduce_to:<event_id>:<amount>` (downgrade).
  - Max 3 concurrent spending adjustments per request.
  - Tie-breaking: fewer adjustments > `reduce_to` over `stop` > highest remaining flexible buffer.
- **Installment Terms**:
  - Read as-is from `dataset/request_payment_options.csv` (provider, installment count, interval, installment amount).
- **`desired_completion_date` Fallback (`days=60`)**:
  - Audit confirmed `desired_completion_date` is 100% populated for all 250 requests in `dataset/requests.csv` and all 25 sample requests (0 missing).
  - The `timedelta(days=60)` fallback in `planner.py` and `candidate_generator.py` is defensive/unreachable code on the current dataset.

---

## 7. Stage 5: Deterministic Decision Tracing & Grounded Explanation
- **Zero LLM Hallucination**:
  - Explanations are compiled deterministically from a typed `DecisionTrace` dataclass.
  - Trace encapsulates baseline trajectory, minimum buffer date/amount, applied winning claims, selected payment plan, and required spending changes.
- **Unconditional Grounding Verification**:
  - Every decision undergoes an unconditional baseline consistency check (`verify_grounding_and_consistency`) verifying mutual alignment of status, method, plan, spending changes, and trace figures.

---

## 8. Agentic Orchestration Layer (`code/orchestration/`)
- **Control-Flow Scrutiny Router (`AuditOrchestrator`)**:
  - Executes a single structured Gemini LLM call (`gemini-3.6-flash`) per request evaluating structured complexity metrics (`num_candidate_plans_generated`, `num_conflicting_claims_resolved_for_user`, `num_spending_adjustments_proposed`, and currency-agnostic `margin_ratio_above_floor`).
  - Emits typed schema: `requires_grounding_recheck` (bool), `risk_flag` (`"standard"` | `"elevated"`), and `reasoning` (string audit trail).
  - Characterized as rule-guided risk classification executed via structured LLM calls with fail-safe fallback (consistently elevating 100% of installment/spending-adjustment cases and tight buffer ratios $< 20\%$).
- **Normalized Margin Ratio Invariant**:
  - Evaluated as `(min_projected_balance - minimum_balance_floor) / minimum_balance_floor`, scaling proportionally across IDR (tens of millions), INR (thousands), USD/EUR (hundreds), and ZAR.
- **Control-Flow Isolation Invariant**:
  - The router controls control-flow ONLY. It can add an EXTRA explicit grounding pass for elevated-risk/complex scenarios, but CANNOT modify, compute, or mutate any financial values, statuses, dates, plans, or `output.csv` columns.
  - Output is 100% byte-identical whether router runs warm, cold, or in fallback mode.
- **Fail-Safe Robustness**:
  - Any LLM timeout, rate limit failure, or schema invalidity fails safe to `requires_grounding_recheck=True` and `risk_flag="elevated"`, ensuring scrutiny is never reduced on router errors.
- **Full Audit Logging**:
  - All routing decisions and scrutiny passes are recorded in `orchestration_log.json` and deterministically cached under `cache/orchestration/`.

---

## 9. Artifact and Packaging Dispositions
- **Cache Directory (`cache/`)**:
  - `cache/extraction/` and `cache/orchestration/` are generated at runtime and cached at repository root.
  - Excluded from `code.zip` distribution; rebuilt automatically on first execution without manual intervention.
- **Legacy Artifact Disposition (`evidence_amounts.json`)**:
  - `evidence_amounts.json` and `evidence_amounts.example.json` were unused developmental reference files and have been removed entirely from the production distribution in `code.zip`.
