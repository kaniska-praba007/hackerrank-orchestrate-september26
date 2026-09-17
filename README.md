# Buy or Wait? — Autonomous Financial Planning Agent

A production-grade, deterministic financial decision pipeline with multimodal VLM extraction, lifecycle reconciliation, multi-tier conflict arbitration, 90-day daily cash projection, agentic orchestration scrutiny, and deterministic explanation rendering.

---

## 1. System Architecture

The pipeline consists of 5 modular stages and an agentic orchestration scrutiny router:

```
                  ┌───────────────────────────────┐
                  │ Stage 1: Ingestion & Normalizer│
                  │ (Foreign exchange & metadata) │
                  └──────────────┬────────────────┘
                                 │
                  ┌──────────────▼────────────────┐
                  │ Stage 2: Multimodal Extraction │
                  │ (Gemini VLM & Structured NLP) │
                  └──────────────┬────────────────┘
                                 │
                  ┌──────────────▼────────────────┐
                  │ Stage 3: Deterministic Verifier│
                  │ (Lifecycle Dedup & Arbitration)│
                  └──────────────┬────────────────┘
                                 │
                  ┌──────────────▼────────────────┐
                  │ Stage 4: Simulator & Planner  │
                  │ (90-Day Projection & Ranking) │
                  └──────────────┬────────────────┘
                                 │
                  ┌──────────────▼────────────────┐
                  │ Stage 5: Deterministic Renderer│
                  │ (Trace-bound Explanations)    │
                  └──────────────┬────────────────┘
                                 │
                  ┌──────────────▼────────────────┐
                  │  Agentic Orchestration Layer   │
                  │ (Scrutiny Router & Dual Audit)│
                  └──────────────┬────────────────┘
                                 │
                             output.csv
```

1. **Stage 1 — Normalization (`code/normalization/`):** Standardizes all 25,342 source financial transactions, resolving exact-date currency conversion across INR, ZAR, IDR, USD, and EUR.
2. **Stage 2 — Multimodal Extraction (`code/extraction/`):** Live VLM extraction on 16 PNG images (`ImageExtractor`) and batch message parsing (`MessageParser`) powered by `gemini-3.6-flash`. Backed by deterministic SHA-256 disk caching under `cache/extraction/`.
3. **Stage 3 — Deterministic Verification (`code/verification/`):** Resolves missing-amount image claims, executes lifecycle deduplication across linked transactions, and enforces a strict 4-tier arbitration hierarchy (amendments > newer records from same source > confirmed vs unconfirmed > directional fallback).
4. **Stage 4 — Simulator & Planner (`code/simulation/` & `code/planning/`):** 90-day day-by-day cash projection checking the minimum balance floor after every event and payment. Evaluates 5 payment methods (`full_payment`, `installments`, `partial_payment`, `wait`, `not_recommended`), identifies recurring commitments, and generates candidate spending adjustments (`stop` / `reduce_to`).
5. **Stage 5 — Deterministic Explanation Renderer (`code/rendering/`):** Factual, grounded explanation string generator strictly bound to typed `DecisionTrace` fields without free LLM generation.
6. **Agentic Orchestration Layer (`code/orchestration/router.py`):** Dynamic scrutiny router assessing transaction complexity, multi-event user conflict volume, and margin-to-floor ratios to trigger second-pass grounding audits.

---

## 2. Environment Setup

### Prerequisites
- Python 3.10+
- Google Gemini API Key (set as `GEMINI_API_KEY` environment variable or in `.env`)

### Installation
From the repository root:
```bash
pip install -r requirements.txt
```

---

## 3. Running the Pipeline

### Main Execution
To run the full end-to-end pipeline on `dataset/requests.csv` and generate `output.csv`:

```bash
python code/main.py --requests-file requests.csv --output output.csv
```

### Options
- `--input-dir`: Path to dataset directory (defaults to `./dataset`).
- `--requests-file`: Name or path of requests CSV (defaults to `requests.csv`).
- `--output`: Output CSV target path (defaults to `./output.csv`).

### Caching Behavior
The pipeline automatically manages disk caching under `cache/extraction/` and `cache/orchestration/`. If the `cache/` directory is absent, it is created automatically on first run and populates seamlessly without manual intervention.

---

## 4. Test & Verification Suite

All modules include dedicated verification and regression gates:

```bash
# 1. Validate Stage 1 normalization invariants across all 25,342 rows
python code/evaluation/validate_normalization.py

# 2. Run Stage 3 4-tier arbitration unit tests
python code/verification/test_conflict_resolver.py

# 3. Run Stage 4 simulation, recurrence, and planning unit tests
python code/planning/test_planner.py

# 4. Run Stage 5 structural output validator
python code/evaluation/validate_output.py

# 5. Run Stage 5 sample regression gate
python code/evaluation/regress_samples.py
```

---

## 5. Token Usage & Cost Report

Detailed token counts and per-request costs are documented in [`code/evaluation/usage_report.md`](code/evaluation/usage_report.md).
- **Model:** `gemini-3.6-flash`
- **Total Requests Evaluated:** 250
- **Average Cost per Request:** ~$0.00005 / request
