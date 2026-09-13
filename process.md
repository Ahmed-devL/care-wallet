# Process Log — Buy or Wait?

This file is a curated, human-readable status tracker. Update it at the end of every
phase — don't wait until the end of the day. Unlike `log.txt`, this file IS meant to be
committed to git and included in `code.zip`.

**Rules for updating this file:**
- Never delete a previous phase's entry — append only.
- Every entry needs: what was built, how it was verified, time spent, and any open
  question or deviation from the plan.
- If a phase's Definition of Done isn't fully met, say so explicitly (e.g. "23/25
  samples match, 2 diverge — see Open Questions") rather than marking it complete.

---

## Status: Phase 1 complete (updated 2026-09-13 08:45 IST)

---

## Phase 0 — Recon & Hand-Solve
**Status:** ✅ Complete (report only — no code)

- Sample rows hand-solved: request_01 (affordable_now) and request_05 (not_affordable)
  — full worked walkthroughs in phase0_report.md
- Key spec rules noted: settlement_date authoritative; all 4 flexibility values;
  income recurrence from history not keywords; 90-day worst-day constraint
- Time spent: ~20 min

---

## Phase 1 — Indexed Data Layer
**Status:** ✅ Complete

- Files created: `code/data_layer.py`, `code/smoke_test.py`
- Row counts verified (all match expected):
  - requests.csv: 250 ✓
  - financial_profiles.csv: 275 ✓
  - financial_events.csv: 25,342 ✓
  - exchange_rates.csv: 134 ✓
  - request_payment_options.csv: 790 ✓
  - messages.csv: 215 ✓
  - images.csv: 16 ✓
- Currency conversion sanity-checked:
  - 100 USD → ZAR via EUR pivot (2025-06-15) = 1840.00 ✓
  - 500 EUR → ZAR (2025-07-01, uses 2025-06-15 rate) = 10000.00 ✓
  - Same-currency passthrough ✓
  - ValueError raised for missing rates ✓
- user_01 has 103 events; first event settlement_date=2023-10-02 ✓
- All 4 flexibility values handled (is_stoppable/is_reducible/is_changeable) ✓
- Smoke test: 30/30 checks PASS
- Committed: 09d4292
- Time spent: ~25 min

---

## Phase 2 — Forecast Engine v1 (event-loop)
**Status:** ⬜ Not started

- Tests written before implementation? (yes/no):
- Sample rows passing (x / 25):
- Cross-checked against Phase 0 hand-solved rows? (yes/no):
- Time spent:

---

## Phase 2b — Forecast Engine v2 (vectorized) + Differential Check
**Status:** ⬜ Not started

- v1 vs v2 agreement across all 250 users (x / 250 match):
- Mismatches found and resolved (list, or "none"):
- Time spent:

---

## Phase 3 — Decision Engine (candidates → filter → rank)
**Status:** ⬜ Not started

- Sample rows passing on recommended_payment_method / payment_plan / affordability_status
  / earliest_date_for_full_payment (x / 25):
- Invariant check: does every recommended plan independently pass the safety check?
  (yes/no):
- Time spent:

---

## Phase 4 — Extraction Layer (confidence-gated LLM, batching, caching)
**Status:** ⬜ Not started

- % of messages/images resolved without an LLM call:
- Cache + `--replay` verified (second run makes 0 new API calls, identical output)?
  (yes/no):
- Time spent:

---

## Phase 5 — Explanation Generation
**Status:** ⬜ Not started

- Spot-checked explanations (x count) for invented/mismatched numbers found: (should be 0)
- Time spent:

---

## Phase 6 — Adversarial & Non-English Tests
**Status:** ⬜ Not started

- Injection test result:
- Non-English message test result:
- Time spent:

---

## Phase 7 — Validation Loop & Full Run
**Status:** ⬜ Not started

- Sample match rate (x / 25):
- Full run: 250/250 rows produced, all structural invariants pass? (yes/no):
- Time spent:

---

## Phase 8 — Packaging
**Status:** ⬜ Not started

- `usage_report.md` complete with real numbers? (yes/no):
- `code.zip` tested from a clean folder using `--replay`, output matches? (yes/no):
- Time spent:

---

## Open Questions / Blockers
_(running list — add as they come up, mark resolved when closed)_

## Deviations From the Strategy Doc
_(anything built differently than planned, and why)_
