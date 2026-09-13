"""
Debug installment safety for request_07 and request_02
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import csv
import forecast_engine as fe
import data_layer as dl
import decision_engine as de

_DATASET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dataset")

# request_07: installments 3x68432 on sep12, oct10, nov7
# user_07, rdate=2024-09-05, min_keep=93000
uid = "user_07"
rdate = "2024-09-05"
requested = 197400.0
profile = dl.get_profile(uid)
min_keep = float(profile["minimum_balance_to_keep"])
print(f"min_keep={min_keep}")

sim = fe.simulate(uid, rdate)
print(f"starting={sim['starting_balance']} min_balance={sim['min_balance']} at {sim['min_balance_date']}")
traj = sim["trajectory"]

# Test safety for installment plan: Sep12, Oct10, Nov7 all at 68432
plan = [("2024-09-12", 68432.0), ("2024-10-10", 68432.0), ("2024-11-07", 68432.0)]
safe = de._passes_safety(uid, rdate, plan, [], min_keep)
print(f"\nInstallment plan (3x68432) safety: {safe}")

# Trace through the safety check manually
print("\nTracing cumulative payments:")
cumulative = 0.0
plan_sorted = sorted(plan, key=lambda x: x[0])
plan_idx = 0
for d_str, balance in traj:
    while plan_idx < len(plan_sorted) and plan_sorted[plan_idx][0] <= d_str:
        cumulative += plan_sorted[plan_idx][1]
        plan_idx += 1
    effective = balance - cumulative
    if effective < min_keep or (cumulative > 0 and d_str < "2024-11-10"):
        print(f"  {d_str}: bal={balance:.2f} cumPaid={cumulative:.0f} effective={effective:.2f} {'FAIL' if effective < min_keep else 'ok'}")

print(f"\nWait date (suffix-min approach):")
wait = de._earliest_wait_date(uid, rdate, requested, profile, [])
print(f"  wait_edfp={wait}")

print(f"\nFullPayment options for request_07:")
opts = dl.get_payment_options("request_07")
for o in opts:
    print(f"  {o['payment_option_id']} {o['payment_method']} first={o['first_payment_date']} n={o['number_of_payments']} total={o['total_payable_amount']}")

print("\nGenerating candidates:")
samples = list(csv.DictReader(open(os.path.join(_DATASET, "sample_requests.csv"), encoding="utf-8")))
req = {r["request_id"]: r for r in samples}["request_07"]
cands = de._generate_candidates("request_07", uid, profile, req, [])
for c in cands:
    print(f"  {c.method} option={c.payment_option_id} n={c.num_payments} first={c.first_payment_date} deadline={c.completes_by_deadline}")
    safe_c = de._passes_safety(uid, rdate, c.payment_plan, [], min_keep) if c.method != "wait" else "wait"
    print(f"    safety={safe_c}")
    print(f"    user_allows={de._user_allows_method(c.method, profile)}")
    if c.method == "installments":
        print(f"    months_ok={de._installment_months_ok(c.num_payments, profile)}")
