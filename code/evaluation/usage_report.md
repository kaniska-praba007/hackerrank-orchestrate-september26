# Token usage report

This report summarizes model usage across the two LLM layers in the pipeline using `gemini-3.6-flash`:
1. **Stage 2 Multimodal Extraction**: 16 PNG financial document images and 215 message claims.
2. **Stage 5 Agentic Orchestration Router**: Structured complexity routing and scrutiny classification across 250 requests.

## Full Pipeline Token & Cost Breakdown (Cold Pass)

| Layer | Live Calls | Input Tokens | Output Tokens | Total Tokens | Cost (USD) |
|---|---:|---:|---:|---:|---:|
| **Stage 2 Multimodal Extraction** | 23 | 52,950 | 28,212 | 81,162 | $0.0124 |
| **Stage 5 Orchestration Router** | 250 | 60,862 | 29,232 | 90,094 | $0.0133 |
| **Total Cold Run (All 250 Requests)** | **273** | **113,812** | **57,444** | **171,256** | **$0.0257** |

### Per-Request Economics
- **Average Tokens per Request:** 685.0 tokens / request
- **Average Total Cost per Request:** **$0.000103 / request** (~$0.01 per 100 requests)

---

## Deterministic Caching Invariants

1. **Content-Addressed Disk Cache**:
   - Stage 2 extractions are cached under `cache/extraction/`.
   - Stage 5 orchestration routing decisions are cached under `cache/orchestration/`.
   - All keys are computed deterministically via `sha256(model + prompt + schema + media)`.
2. **Subsequent Run (Warm Pass)**:
   - **Live Calls**: `0`
   - **Cache Hits**: `273 / 273` (100% cache hit rate)
   - **Total Duration**: `< 5s`
   - **Incremental API Cost**: **$0.0000**

