import sys, os; sys.path.insert(0, '.')
import csv, data_layer as dl, decision_engine as de, forecast_engine as fe

_DATASET = '../dataset'
samples = {r['request_id']: r for r in csv.DictReader(open(_DATASET+'/sample_requests.csv', encoding='utf-8'))}

# request_02: installments n=3 x 15952906.67 on Aug8, Sep7, Oct7
# Expected: should pass safety
req = samples['request_02']
uid, rdate, requested = req['user_id'], req['request_date'], float(req['requested_amount'])
profile = dl.get_profile(uid)
min_keep = float(profile['minimum_balance_to_keep'])
print(f"=== request_02 uid={uid} min_keep={min_keep}")
plan = [("2025-08-08", 15952906.67), ("2025-09-07", 15952906.67), ("2025-10-07", 15952906.67)]
print(f"Plan: {plan}")
safe = de._passes_safety(uid, rdate, plan, [], min_keep)
print(f"_passes_safety: {safe}")

# Trace it
sim = fe.simulate(uid, rdate)
print(f"starting={sim['starting_balance']} min_balance={sim['min_balance']} at {sim['min_balance_date']}")
traj = sim['trajectory']
# Find key dates
for d, b in traj:
    if '2025-08' in d or '2025-09' in d or '2025-10' in d:
        print(f"  {d}: {b:.2f}")
    if d > '2025-11-01':
        break

print()
# request_22: installments n=3 x 253.59 on Dec8, Jan5, Feb2
req = samples['request_22']
uid, rdate, requested = req['user_id'], req['request_date'], float(req['requested_amount'])
profile = dl.get_profile(uid)
min_keep = float(profile['minimum_balance_to_keep'])
print(f"=== request_22 uid={uid} min_keep={min_keep}")
opts = dl.get_payment_options('request_22')
for o in opts:
    print(f"  opt {o['payment_option_id']} {o['payment_method']} n={o['number_of_payments']} first={o['first_payment_date']} freq={o['payment_frequency_days']}")
sim = fe.simulate(uid, rdate)
print(f"starting={sim['starting_balance']} min_balance={sim['min_balance']} at {sim['min_balance_date']}")
cands = de._generate_candidates('request_22', uid, profile, req, [])
surviving = de._filter_candidates(cands, uid, profile, rdate, requested, [])
print(f"Surviving: {[(c.method, c.payment_option_id, c.first_payment_date) for c in surviving]}")

print()
# request_10: false wait
req = samples['request_10']
uid, rdate, requested = req['user_id'], req['request_date'], float(req['requested_amount'])
profile = dl.get_profile(uid)
min_keep = float(profile['minimum_balance_to_keep'])
print(f"=== request_10 uid={uid} min_keep={min_keep}")
print(f"requested={requested}")
sim = fe.simulate(uid, rdate)
print(f"starting={sim['starting_balance']} min_balance={sim['min_balance']} at {sim['min_balance_date']}")
wait = de._earliest_wait_date(uid, rdate, requested, profile, [])
print(f"wait_edfp={wait}")
# If wait is found, that's wrong - check the trajectory at that date
if wait:
    traj = sim['trajectory']
    for d, b in traj:
        if d >= '2024-12':
            print(f"  traj {d}: {b:.2f} suffix_min=check")
            suffix_min = min(bal for _, bal in traj[traj.index((d,b)):])
            print(f"  suffix_min={suffix_min:.2f} - requested={requested} = {suffix_min-requested:.2f} vs min_keep={min_keep}")
            break
