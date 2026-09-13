"""
Deep debug on request_08 and request_13
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import csv
import forecast_engine as fe
import data_layer as dl

_DATASET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dataset")

# request_08 user_08 - why does expected say wait until 2025-04-15?
print("=== request_08: full trajectory analysis ===")
uid = "user_08"
rdate = "2025-02-07"
profile = dl.get_profile(uid)
min_keep = float(profile["minimum_balance_to_keep"])
requested = 996.6
sim = fe.simulate(uid, rdate)
print(f"starting_balance={sim['starting_balance']}")
print(f"min_keep={min_keep}")

# Show the deltas around April
deltas, _ = fe.build_forecast_deltas(uid, rdate)
print("\nAll deltas in March-May range:")
for d, amt, tag in sorted(deltas):
    if "2025-03" in d or "2025-04" in d or "2025-05" in d:
        print(f"  {d}: {amt:+.2f} ({tag})")

# What's the max balance in the trajectory?
traj = sim["trajectory"]
max_bal = max(traj, key=lambda x: x[1])
print(f"\nMax balance: {max_bal[0]} = {max_bal[1]:.2f}")
print(f"  Can pay {requested} on that date? {max_bal[1] - requested:.2f} vs min_keep {min_keep}")

# Look at the trajectory around Feb-March when balance is high
print("\nTrajectory Feb 7 to Mar 1:")
for d, b in traj:
    if "2025-02" in d or ("2025-03" in d and b > 1000):
        print(f"  {d}: {b:.2f} headroom={b-min_keep:.2f} can_pay={b-min_keep-requested:.2f}")

# Maybe the "wait" edfp is based on daily balance BEFORE applying suffix-min?
# i.e. first day when: balance_at_d - requested >= min_keep
print("\nFirst day where balance_at_d - requested >= min_keep:")
for d, b in traj:
    if b - requested >= min_keep:
        print(f"  {d}: balance={b:.2f} b-req={b-requested:.2f} vs min_keep={min_keep}")
        break
else:
    print("  NONE found in 90-day window")

print("\n=== request_13: Why does our forecast get wrong amount_safe? ===")
uid = "user_13"
rdate = "2024-03-07"
profile = dl.get_profile(uid)
min_keep = float(profile["minimum_balance_to_keep"])
requested = 941.6
sim = fe.simulate(uid, rdate)
print(f"starting_balance={sim['starting_balance']}")
print(f"min_keep={min_keep}")
print(f"min_balance={sim['min_balance']} at {sim['min_balance_date']}")
safe = fe.amount_safe_to_pay(uid, rdate, requested)
print(f"our amount_safe={safe}") 
print(f"expected amount_safe=433.4")

print("\nTrajectory:")
for d, b in sim["trajectory"]:
    if b < 2000:
        print(f"  {d}: {b:.2f} headroom={b-min_keep:.2f}")

print("\nAll deltas:")
deltas, _ = fe.build_forecast_deltas(uid, rdate)
for d, amt, tag in sorted(deltas):
    print(f"  {d}: {amt:+.2f} ({tag})")
