"""
smoke_test.py -- Phase 1 data layer smoke test.
Run from repo root: python code/smoke_test.py

Checks:
1. Row counts for every loaded file match expected values
2. Event count for user_01 is correct
3. A known currency conversion produces the expected result
4. Flexibility helper functions return correct results for all 4 values
5. Missing-rate ValueError is raised correctly
"""
import sys
import os
sys.stdout.reconfigure(encoding="utf-8")

# Make sure code/ is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import data_layer as dl

PASS = "[PASS]"
FAIL = "[FAIL]"

errors = 0

def check(label: str, condition: bool, detail: str = "") -> None:
    global errors
    if condition:
        print(f"  {PASS}  {label}" + (f"  ({detail})" if detail else ""))
    else:
        print(f"  {FAIL}  {label}" + (f"  -- {detail}" if detail else ""))
        errors += 1

print("=" * 60)
print("Phase 1 Smoke Test -- data_layer.py")
print("=" * 60)

# ── 1. Row counts ───────────────────────────────────────────────────────────
print("\n[1] Row counts")
counts = dl.get_row_counts()
EXPECTED = {
    "requests.csv":                  250,
    "financial_profiles.csv":        275,
    "financial_events.csv":        25342,
    "exchange_rates.csv":            134,
    "request_payment_options.csv":   790,
    "messages.csv":                  215,
    "images.csv":                     16,
}
for fname, expected in EXPECTED.items():
    actual = counts.get(fname, -1)
    check(f"{fname}: {actual} rows", actual == expected, f"expected {expected}")

# ── 2. user_01 event count ──────────────────────────────────────────────────
print("\n[2] get_events('user_01')")
u01_events = dl.get_events("user_01")
check(
    f"user_01 has events",
    len(u01_events) > 0,
    f"{len(u01_events)} events found",
)
# Spot check: verify first event uses settlement_date, not just event_date
first = u01_events[0]
check(
    "First event has settlement_date field",
    "settlement_date" in first and first["settlement_date"] != "",
    f"settlement_date={first.get('settlement_date')}",
)

# ── 3. get_profile ──────────────────────────────────────────────────────────
print("\n[3] get_profile('user_01')")
p = dl.get_profile("user_01")
check("Balance is 58481.1", float(p["current_available_balance"]) == 58481.1,
      p["current_available_balance"])
check("Min balance is 18000", float(p["minimum_balance_to_keep"]) == 18000.0,
      p["minimum_balance_to_keep"])
check("Home currency is ZAR", p["home_currency"] == "ZAR", p["home_currency"])

# ── 4. Currency conversion ──────────────────────────────────────────────────
print("\n[4] convert()")

# Known: USD -> ZAR. No direct pair in file. Must pivot via EUR.
# EUR -> ZAR rate on 2025-06-15: 20. USD -> EUR on 2025-06-15: 0.92
# So 100 USD -> 100 * 0.92 * 20 = 1840 ZAR
result = dl.convert(100.0, "USD", "ZAR", "2025-06-15")
check("100 USD -> ZAR via EUR pivot (2025-06-15)",
      abs(result - 1840.0) < 0.01,
      f"got {result:.4f}, expected 1840.0000")

# EUR -> ZAR direct: rate=20, settlement 2025-07-01 (uses 2025-06-15 rate)
result2 = dl.convert(500.0, "EUR", "ZAR", "2025-07-01")
check("500 EUR -> ZAR (2025-07-01, uses 2025-06-15 rate)",
      abs(result2 - 10000.0) < 0.01,
      f"got {result2:.4f}, expected 10000.0000")

# Same currency
result3 = dl.convert(1234.56, "ZAR", "ZAR", "2025-01-01")
check("Same currency (ZAR->ZAR) returns unchanged",
      abs(result3 - 1234.56) < 0.0001,
      f"got {result3}")

# Rate before first available date should raise ValueError
raised = False
try:
    dl.convert(100.0, "EUR", "ZAR", "2020-01-01")
except ValueError as e:
    raised = True
    print(f"         ValueError correctly raised: {e}")
check("convert() raises ValueError for missing rate", raised)

# settlement_date BEFORE first rate in file
raised2 = False
try:
    dl.convert(100.0, "USD", "IDR", "2023-01-01")  # first USD->IDR is 2023-10-15
except ValueError:
    raised2 = True
check("convert() raises ValueError for date before first rate", raised2)

# ── 5. Flexibility helpers ──────────────────────────────────────────────────
print("\n[5] Flexibility helpers")
CASES = [
    ({"flexibility": "fixed"},                  False, False, False),
    ({"flexibility": "reducible"},              False, True,  True),
    ({"flexibility": "stoppable"},              True,  False, True),
    ({"flexibility": "reducible_or_stoppable"}, True,  True,  True),
]
for ev, exp_stop, exp_reduce, exp_change in CASES:
    flex = ev["flexibility"]
    check(f"is_stoppable('{flex}')", dl.is_stoppable(ev) == exp_stop,
          f"expected {exp_stop}")
    check(f"is_reducible('{flex}')", dl.is_reducible(ev) == exp_reduce,
          f"expected {exp_reduce}")
    check(f"is_changeable('{flex}')", dl.is_changeable(ev) == exp_change,
          f"expected {exp_change}")

# ── 6. Payment options spot check ───────────────────────────────────────────
print("\n[6] get_payment_options('request_01')")
opts = dl.get_payment_options("request_01")
check("request_01 has payment options", len(opts) >= 2, f"found {len(opts)}")
methods = [o["payment_method"] for o in opts]
check("Has a full_payment option", "full_payment" in methods, str(methods))

# ── 7. Messages / images spot checks ────────────────────────────────────────
print("\n[7] Messages and images")
msgs_u02 = dl.get_messages_for_user("user_02")
check("user_02 has messages", len(msgs_u02) > 0, f"{len(msgs_u02)} messages")
# Check first message has message_text field
check("Message has message_text", "message_text" in msgs_u02[0])

imgs_all = dl.get_images_for_user("user_03")
check("user_03 has images", len(imgs_all) > 0, f"{len(imgs_all)} images")
check("image_path resolves correctly",
      dl.image_path("image_01").endswith("image_01.png"))

# ── Summary ─────────────────────────────────────────────────────────────────
print()
print("=" * 60)
if errors == 0:
    print(f"ALL CHECKS PASSED (0 failures)")
else:
    print(f"{errors} CHECK(S) FAILED")
print("=" * 60)
sys.exit(errors)
