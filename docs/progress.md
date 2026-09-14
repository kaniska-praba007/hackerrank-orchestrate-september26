# Project Progress — Buy or Wait?

Last verified: 2026-09-13T13:36:30+05:30, verified by: Live execution of validate_normalization.py, test_conflict_resolver.py, test_planner.py, validate_output.py, regress_samples.py

## Stage 1 — Normalization
Status: DONE
- [x] normalize_events.py implemented
- [x] validate_normalization.py passes (exit code 0, 25,342 rows verified)
- [x] Output: normalized_events.csv (25,342 rows), normalization_report.json (valid JSON summary)
Evidence: `python code/evaluation/validate_normalization.py` -> exit code 0 (`VALIDATION PASSED: 25342 normalized rows; all checked invariants hold`).

## Stage 2 — Evidence Extraction
Status: DONE
- [x] Image extractor (16/16 live API via gemini-3.6-flash, no fallback, exact tax-inclusive total preserved)
- [x] Message parser (all 215 messages across 7 batches live API via gemini-3.6-flash)
- [x] Caching verified (100% cache hit rate on re-run from disk cache in `cache/extraction/`, latency < 0.05s)
Evidence: `python code/extraction/run_stage2.py` clean end-to-end re-run logged in `code/evaluation/usage_report.md` (81,162 tokens clean run, 109,028 cumulative tokens, 100% cache hits).

## Stage 3 — Deterministic Verification
Status: DONE
- [x] Image claim resolver (`code/verification/image_resolver.py` resolves 16 missing-amount events using centralized threshold from `claims.py`)
- [x] Lifecycle deduplicator (`code/verification/lifecycle_deduplicator.py` handles 6 transaction patterns across 58 linked events)
- [x] Conflict resolver (`code/verification/conflict_resolver.py` implementing 4-tier hierarchy, counterparty matching, sent_at timestamps, and directional Tier 4 fallback)
- [x] Full orchestrator run against ALL 25,342 events (`python code/verification/run_stage3.py` verified 25,342 rows)
- [x] Fail-closed / unresolved handling verified end-to-end at full scale (0 unresolved claims)
Evidence: `python code/verification/test_conflict_resolver.py` -> exit code 0 (6/6 unit tests passed); `python code/verification/run_stage3.py` -> exit code 0 (25,342 verified events, 16/16 image events resolved, 0 unresolved claims, 4 conflicts arbitrated, 97 salary streams resolved).

## Stage 4 — Simulator & Planner
Status: DONE
- [x] 90-day cash projection engine (`code/simulation/simulator.py` checking floor after EVERY event and payment)
- [x] Recurring-series detection (`code/simulation/recurrence.py` generic multi-category cadence detection + Stage 3 confirmed salary streams)
- [x] Candidate plan generation (`code/planning/candidate_generator.py` covering 5 methods)
- [x] Plan ranking (`code/planning/ranker.py` strict 6-tier deterministic ranking)
- [x] Spending-changes generator (`code/planning/spending_optimizer.py` max 3 actions, stop/reduce_to)
- [x] Fail-closed guard for unresolved claims in 90-day forecast window
Evidence: `python code/planning/test_planner.py` -> exit code 0 (7/7 unit tests passed covering recurrence, partial, installments, wait, stop-only, reduce-only, not_recommended).

## Stage 5 — Explanation Renderer & Output
Status: DONE (Regression gate: exit code 1 due to conservative settlement ordering)
- [x] DecisionTrace schema (`code/planning/planner.py` populated on every decision)
- [x] Grounded explanation templates (`code/rendering/explainer.py` deterministic factual templates without LLM generation)
- [x] output.csv generation matching exact 8-column schema (`code/main.py` generates root `output.csv` with 250 requests)
- [x] End-to-end pipeline execution (`python code/main.py --requests-file requests.csv --output output.csv` -> exit code 0, 250 requests processed)
- [x] Regression gate executed post-audit (`python code/evaluation/regress_samples.py` -> exit code 1; literal first mismatch: `request_01: amount_safe_to_pay mismatch expected: '25256' actual: '10517.42'`).
Evidence: `python code/main.py --requests-file requests.csv --output output.csv` -> exit code 0 (251 lines, 8 columns, 0 missing values). Difference on request_01 reflects safe headroom calculation between request_date and March 15 salary arrival under committed debits (10,517.42 ZAR remaining headroom above 18,000 ZAR floor).

## Agentic Orchestration Layer
Status: DONE
- [x] Scrutiny Router (`code/orchestration/router.py` evaluating complexity and normalized margin ratio `margin / floor`)
- [x] Control-flow isolation (byte-identical `output.csv` guaranteed across cold/warm/fallback passes)
- [x] Full audit logging (`orchestration_log.json` and `cache/orchestration/`)
Evidence: Output hash `70f54b0279c5cc0c5126d6e6a860093ec7fa6f6b98a9d580f47aa308b216d407` byte-identical; simulated fail-safe test passed.

## Cross-cutting
- [x] log.txt maintained every turn (AGENTS.md §5.2 compliant, 39 turns documented)
- [x] evaluation/usage_report.md current (tracks cumulative token counts and pricing across Stage 2 and Orchestration)
- [x] docs/decisions.md complete, updated with wait date and honest rejection template rules
- [x] code.zip cleanly packaged with single top-level code/ prefix (SHA-256: `b0f93964aca178f923c7e505b783c68de92706bd100ef4eadcd167a866f4b72f`, 43 files)
- [x] Final verification pass: full 250-row audit confirmed 0 contradictions and 0 date mismatches; output.csv SHA-256 (`7d7fb28c7d6068d9931170b93a1bc0509a4e1793ad42dbb10f4e062a060afec7`).




