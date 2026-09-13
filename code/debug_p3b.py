"""
Debug batch 2 - understand the trickier mismatches
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import csv
import forecast_engine as fe
import data_layer as dl
import decision_engine as de

_DATASET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dataset")
samples = list(csv.DictReader(open(os.path.join(_DATASET, "sample_requests.csv"), encoding="utf-8")))
samp_by_id = {r["request_id"]: r for r in samples}

# request_08: why is min_balance negative? edfp should be 2025-04-15
print("=== request_08 detailed trajectory ===")
row = samp_by_id["request_08"]
uid = row["user_id"]
rdate = row["request_date"]
requested = float(row["requested_amount"])
profile = dl.get_profile(uid)
min_keep = float(profile["minimum_balance_to_keep"])
sim = fe.simulate(uid, rdate)
print(f"request_date={rdate} requested={requested} min_keep={min_keep}")
print(f"min_balance={sim['min_balance']} at {sim['min_balance_date']}")
# Look at the balance around April 15
traj = sim["trajectory"]
for d, b in traj:
    if "2025-04" in d or "2025-03-30" in d or "2025-03-28" in d:
        print(f"  {d}: {b:.2f}")

# Check if the balance ever recovers above requested + min_keep
print("\nDoes balance ever recover so edfp is possible?")
for d, b in traj:
    headroom = b - min_keep
    if headroom >= requested:
        print(f"  First safe date: {d} balance={b:.2f} headroom={headroom:.2f}")
        break
else:
    print("  NO date found in trajectory where balance is safe for full payment")
    print("  Max balance in trajectory:")
    max_b = max(traj, key=lambda x: x[1])
    print(f"  {max_b[0]}: {max_b[1]:.2f} headroom={max_b[1]-min_keep:.2f} requested={requested}")

print("\n=== request_03 ===")
row = samp_by_id["request_03"]
uid = row["user_id"]
rdate = row["request_date"]
requested = float(row["requested_amount"])
profile = dl.get_profile(uid)
min_keep = float(profile["minimum_balance_to_keep"])
sim = fe.simulate(uid, rdate)
print(f"request_date={rdate} requested={requested} min_keep={min_keep}")
print(f"min_balance={sim['min_balance']} at {sim['min_balance_date']}")
print(f"edfp from fe: {fe.earliest_date_for_full_payment(uid, rdate, requested)}")
print("Looking for date in trajectory:")
traj = sim["trajectory"]
for d, b in traj:
    headroom = b - min_keep - requested
    if headroom >= -0.01:
        print(f"  First candidate: {d} balance={b:.2f}")
        break
print("Checking around Nov 15:")
for d, b in traj:
    if "2019-11" in d:
        print(f"  {d}: {b:.2f} headroom_for_req={b-min_keep-requested:.2f}")

print("\n=== request_13: desired_completion_date ===")
row = samp_by_id["request_13"]
print(f"desired_completion_date={row['desired_completion_date']}")
print(f"request_date={row['request_date']}")
print(f"amount_safe={row['amount_safe_to_pay']}")
opts = dl.get_payment_options("request_13")
for o in opts:
    print(f"  {o['payment_option_id']} method={o['payment_method']} first={o['first_payment_date']} n={o['number_of_payments']}")

print("\n=== request_19: desired_completion_date + total payable ===")
row = samp_by_id["request_19"]
print(f"desired_completion_date={row['desired_completion_date']}")
print(f"request_date={row['request_date']}")
print(f"amount_safe={row['amount_safe_to_pay']} requested={row['requested_amount']}")
opts = dl.get_payment_options("request_19")
for o in opts:
    print(f"  {o['payment_option_id']} method={o['payment_method']} n={o['number_of_payments']} total={o['total_payable_amount']} first={o['first_payment_date']}")
# partial_payment total = requested_amount (no fee) vs installments?

print("\n=== request_06: spending changes - why does it pass without them? ===")
row = samp_by_id["request_06"]
uid = row["user_id"]
rdate = row["request_date"]
requested = float(row["requested_amount"])
profile = dl.get_profile(uid)
min_keep = float(profile["minimum_balance_to_keep"])
print(f"desired_completion_date={row['desired_completion_date']}")
sim = fe.simulate(uid, rdate)
print(f"min_balance={sim['min_balance']} at {sim['min_balance_date']}")
print(f"amount_safe (without changes)={fe.amount_safe_to_pay(uid, rdate, requested)}")
# The expected edfp=2026-01-15 but we're getting 2026-01-03
# The expected changes=stop:event_476
# What is event_476?
events = dl.get_events(uid)
for ev in events:
    if ev["event_id"] == "event_476":
        print(f"event_476: {ev}")
