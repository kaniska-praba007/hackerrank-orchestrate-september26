# Buy or Wait? — Complete Architecture & Interview Walkthrough

A concise, factual technical walkthrough of the autonomous financial decision agent, structured for an engineer to explain end-to-end in a live technical interview.

---

## 1. One-Paragraph Summary

The system is a deterministic, audit-traceable financial decision engine that determines whether a user can safely afford a discretionary purchase today, with payment restructuring, or at a future date without breaching their protected minimum balance floor over a 90-day forward horizon. It ingests multi-currency raw ledger transactions, extracts ground-truth amounts and updates from unstructured invoices (images) and user/merchant messages using structured multimodal LLM calls, arbitrates evidence through a strict 4-tier precedence policy, and projects daily cash flows across 5 payment strategies (`full_payment`, `partial_payment`, `installments`, `wait`, `not_recommended`). All final outputs and user-facing explanations are compiled deterministically from an underlying `DecisionTrace` dataclass rather than free-form generative LLM text, guaranteeing mathematical consistency and zero hallucinations.

---

## 2. The 5-Stage Pipeline

### Stage 1: Ingestion & Normalization (`code/normalization/`)
- **Input**: Raw `financial_events.csv` (25,342 rows), `financial_profiles.csv`, `images.csv`, `messages.csv`, and `exchange_rates.csv`.
- **Processing**: Resolves exact-date foreign currency conversion across the 5 supported currencies (INR, ZAR, IDR, USD, EUR), normalizes dates into ISO-8601 (`YYYY-MM-DD`), links foreign keys, and assigns empty-string `""` null sentinels.
- **Output**: Canonical `normalized_events.csv` (25,342 rows) and `normalization_report.json`.
- **Likely Interview Question**: *"How do you handle currency conversion when a transaction date lacks an exact forex rate entry?"*  
  **Answer**: Exact date match is prioritized; if missing, it falls back to the nearest prior available historical rate; if earlier than all rates, it uses the earliest available rate.

### Stage 2: Multimodal & NLP Evidence Extraction (`code/extraction/`)
- **Input**: 16 raw receipt/invoice PNGs (`dataset/media/images/`) and 215 unstructured message texts (`messages.csv`).
- **Processing**: Uses `gemini-3.6-flash` with strict JSON schemas, temperature 0.0, and Pydantic validation to extract tax-inclusive amounts, transaction intent, confirmation status, and timestamps.
- **Output**: Typed `Claim` objects cached deterministically under `cache/extraction/`.
- **Likely Interview Question**: *"Why extract exact tax-inclusive totals instead of reading the 'Total' label?"*  
  **Answer**: Invoices frequently contain rounded cash totals or pre-tax subtotals; summing subtotal plus itemized SGST/CGST taxes yields the mathematically exact legal liability.

### Stage 3: Deterministic Verification & Conflict Arbitration (`code/verification/`)
- **Input**: 25,342 normalized events, 16 verified image claims, 215 message claims, and 58 linked lifecycle events.
- **Processing**: Reconciles event lifecycles (authorizations, settlements, refunds, chargebacks, reversals) and arbitrates competing claims via a strict 4-tier hierarchy: (1) Document/invoice amendments supersede estimates, (2) Newer same-source records by `sent_at` timestamp win, (3) Confirmed records supersede unconfirmed estimates, (4) Financially safer directional fallback (conservative min credit / max debit).
- **Output**: Verified, deduplicated ledger and resolved recurring salary streams (`resolved_salary_streams`).
- **Likely Interview Question**: *"What happens if an unconfirmed bonus message promises a huge cash inflow?"*  
  **Answer**: A hard early-return guard prevents `unconfirmed_bonus` or `general_informational` claims from ever modifying baseline cash flows.

### Stage 4: 90-Day Simulator & Action Planner (`code/simulation/`, `code/planning/`)
- **Input**: Verified ledger, user financial profile, merchant payment options, and requested purchase parameters.
- **Processing**: Detects recurring commitments ($ \ge 2 $ historical occurrences, $ \ge 50\% $ interval regularity), projects 90 days of day-by-day cash balances checking the floor after every single event/payment, generates candidate plans across 5 methods, synthesizes minimal lifestyle spending adjustments (`stop` / `reduce_to`, max 3), and ranks candidates through a 6-tier utility hierarchy.
- **Output**: Optimal `PlanDecision` and typed `DecisionTrace`.
- **Likely Interview Question**: *"How do you guarantee the minimum balance floor is never breached between paychecks?"*  
  **Answer**: The simulator evaluates daily closing balances and intraday transaction ordering (confirmed credits $\rightarrow$ scheduled debits $\rightarrow$ candidate payments), recording the global minimum projected balance across all 90 days.

### Stage 5: Deterministic Explanation Renderer (`code/rendering/`)
- **Input**: `DecisionTrace` dataclass and verified event lookup index.
- **Processing**: Populates exact, human-readable explanation templates directly from verified trace figures (`asked`, `safe_today`, `earliest_date`, `floor`, `payment_plan`), followed by an unconditional grounding check (`verify_grounding_and_consistency`) verifying 100% mutual alignment.
- **Output**: Final 8-column `output.csv` row.
- **Likely Interview Question**: *"How do you prevent the LLM from hallucinating advice or misstating numbers in the explanation?"*  
  **Answer**: LLMs are never used for text generation in Stage 5; all explanations are compiled deterministically from typed trace fields using factual templates.

---

## 3. The Orchestration Router (`code/orchestration/router.py`)

- **What It Actually Decides**: It analyzes transaction complexity (`num_candidate_plans`, `conflicts_resolved_count`, `spending_changes_needed`) and normalized margin ratio $\frac{\text{min\_balance} - \text{floor}}{\text{floor}}$. When risk is elevated (tight buffer $< 20\%$, spending adjustments required, or multiple candidate methods), it triggers an explicit second-pass grounding and consistency audit.
- **What It Does NOT Decide**: It **never** computes, modifies, or mutates any financial numbers, recommendation statuses, payment plans, dates, or output columns.
- **Honest "Agentic" Assessment**: The router is a **control-flow gatekeeper with LLM-assisted risk classification and fail-safe fallback**; it adds conditional scrutiny without violating the core invariant that all financial arithmetic remains 100% deterministic and byte-identical.

---

## 4. Four Critical Design Decisions

| Decision | Rejected Alternative & Why | Spec Citation / Evidence |
| :--- | :--- | :--- |
| **1. Deterministic Simulation & Template Rendering** | *End-to-end generative LLM decision making*. Rejected because LLMs hallucinate numbers, fail multi-step arithmetic over 90-day horizons, and produce non-reproducible outputs. | `problem_statement.md § Deterministic Planning & Zero Hallucination` |
| **2. Strict 4-Tier Arbitration Precedence** | *Majority voting or confidence averaging*. Rejected because confidence scores cannot resolve temporal amendments (a newer message superseding an older invoice) or financial safety. | `docs/decisions.md § 5 Stage 3 Conflict Arbitration` |
| **3. Baseline Earliest Date Calculation** | *Calculating earliest full payment with spending adjustments included*. Rejected because the spec defines `earliest_date_for_full_payment` as the earliest date the user naturally reaches safe headroom on baseline trajectory. | `problem_statement.md § Output Schema Definitions` |
| **4. Fail-Closed Materiality Guard** | *Guessing or ignoring unresolved claims*. Rejected because guessing unverified debts risks catastrophic account overdrafts; unresolved claims within 90 days immediately fail closed to `not_affordable`. | `docs/decisions.md § 6 Fail-Closed Guard` |

---

## 5. Known Limitations & Documented Trade-Offs

1. **`request_01` Headroom Calculation**: Under strict chronological debit ordering, committed debits between request date and salary arrival leave 10,517.42 ZAR safe headroom above the 18,000 ZAR floor, differing from sample request's nominal balance (documented in `docs/decisions.md § 1`).
2. **`request_28 / 33 / 45` Wait + Spending Adjustments**: Documented interpretation where permitted spending changes apply across all payment timing methods, classifying required budget cuts as `affordable_with_plan` rather than `affordable_later`.
3. **`request_133` vs. `request_119 / 145 / 148 / 218 / 231` Explanation Distinction**: Disaggregates pure eligibility exhaustion (0 mutually accepted methods, e.g., `request_133`) from eligible installment plans that genuinely breached the minimum floor during simulation (6 total requests in dataset).
4. **Exchange Rate Fallback**: Missing daily forex rates fall back deterministically to the nearest prior date rather than linear interpolation.
5. **Router Currency-Ratio Normalization**: Raw nominal currency margins fail across scales (tens of millions in IDR vs hundreds in USD/EUR); resolved by evaluating normalized ratio `(min_balance - floor) / floor` with `< 0.20` elevated risk threshold (`code/orchestration/router.py:84`).
6. **Four Explanation Template Contradictions Resolved**: Audited and fixed historical template bugs: (1) date mismatch pulling desired completion date instead of earliest date, (2) false "cannot be completed safely" claim when requested amount is safe, (3) populated earliest date conflicting with 90-day failure template across 48 `not_recommended` rows, and (4) conflating floor-breaching installment plans with zero-method eligibility exhaustion (`request_119, 145, 148, 218, 231` vs `request_133`).
7. **Defensive `days=60` Default Deadline Fallback**: Audit confirmed all 250 requests in `dataset/requests.csv` and 25 sample requests have 100% populated `desired_completion_date` (0 missing rows); `timedelta(days=60)` in `planner.py:51` is defensive, unreachable code on the benchmark dataset.

---

## 6. End-to-End Walkthrough of One Request (`request_30`)

### Step 1: Input Data & Ingestion
- **User**: `user_30` | **Home Currency**: `USD`
- **Request**: `request_30` | **Amount**: `$775.20` | **Date**: `2026-04-06` | **Deadline**: `2026-06-06`
- **Profile**: Opening Balance: `$3,752.72` | Minimum Floor: `$900.00` | Max Installment Months: `4` | Considered Methods: `partial_payment|installments` (user explicitly excludes full payment).

### Step 2: Evidence Verification & Ledger
- Ingested 25,342 events; identified 0 conflicting claims for `user_30`. Confirmed recurring bills and monthly salary stream.

### Step 3: Simulation & Baseline Capacity
- `immediate_safe_amount` = `$775.20` (cash capacity exists, but user excludes `full_payment`).
- `earliest_date_for_full_payment` = `2026-04-06`.

### Step 4: Candidate Generation & Simulation
1. **Candidate 1 (Full Payment)**: Ineligible (user considered methods: `partial_payment|installments`).
2. **Candidate 2 (`payment_option_85`)**: 18 payments of `$49.10` every 31d (total `$883.80`). Ineligible: duration (18 months) exceeds user limit (4 months).
3. **Candidate 3 (`payment_option_83`)**: 3 payments of `$268.74` every 30d (total `$806.22`). Eligible: duration 2 months $\le 4$ months, completion `2026-06-05` $\le$ deadline `2026-06-06`.
   - **Simulation**: Tested day-by-day; minimum projected balance is **`$1,815.11`** on `2026-06-19` (comfortably above the `$900.00` safety floor; safe headroom = `+$915.11`).

### Step 5: Ranking & Selection
- `payment_option_83` is eligible, safe without spending changes, and completes within deadline.
- **Winning Method**: `installments`
- **Affordability Status**: `affordable_with_plan`
- **Payment Plan**: `2026-04-06:268.74|2026-05-06:268.74|2026-06-05:268.74`
- **Spending Changes Needed**: `none`

### Step 6: Orchestration Router & Rendered Explanation
- **Router Evaluation**: Margin ratio = $\frac{1815.11 - 900}{900} = +1.01$ ($> 20\%$), 3 candidate plans, 0 conflicts. Routes standard pass. Grounding check passes.
- **Rendered Output Explanation**:
  > *"Use 3 installments of USD 268.74, starting 6 April 2026. This leaves at least USD 900 available."*
- **Final Row in `output.csv`**:
  ```csv
  request_30,775.2,affordable_with_plan,installments,2026-04-06:268.74|2026-05-06:268.74|2026-06-05:268.74,2026-04-06,none,"Use 3 installments of USD 268.74, starting 6 April 2026. This leaves at least USD 900 available."
  ```
