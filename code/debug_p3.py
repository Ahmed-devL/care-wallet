"""
Debug script for Phase 3 mismatches
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

def debug_request(rid):
    row = samp_by_id[rid]
    uid = row["user_id"]
    rdate = row["request_date"]
    requested = float(row["requested_amount"])
    profile = dl.get_profile(uid)
    min_keep = float(profile["minimum_balance_to_keep"])
    print(f"\n=== {rid} uid={uid} ===")
    print(f"requested={requested} rdate={rdate} min_keep={min_keep}")
    print(f"payment_methods_allowed={profile['payment_methods_user_will_consider']}")
    print(f"max_installment_months={profile['max_installment_months']}")
    
    sim = fe.simulate(uid, rdate)
    print(f"starting_balance={sim['starting_balance']}")
    print(f"min_balance={sim['min_balance']} at {sim['min_balance_date']}")
    safe = fe.amount_safe_to_pay(uid, rdate, requested)
    edfp = fe.earliest_date_for_full_payment(uid, rdate, requested)
    print(f"amount_safe={safe} edfp={edfp}")
    
    opts = dl.get_payment_options(rid)
    print(f"payment options:")
    for o in opts:
        print(f"  {o['payment_option_id']} method={o['payment_method']} n={o['number_of_payments']} amt={o['payment_amount']} first={o['first_payment_date']}")
    
    result = de.decide(rid, uid)
    print(f"decide() => status={result['affordability_status']} method={result['recommended_payment_method']}")
    print(f"  plan={result['payment_plan']}")
    print(f"  edfp={result['earliest_date_for_full_payment']}")
    print(f"  changes={result['spending_changes_needed']}")
    
    expected = samp_by_id[rid]
    print(f"expected => status={expected['affordability_status']} method={expected['recommended_payment_method']}")
    print(f"  plan={expected['payment_plan']}")
    print(f"  edfp={expected['earliest_date_for_full_payment']}")
    print(f"  changes={expected['spending_changes_needed']}")

for rid in ["request_02", "request_03", "request_06", "request_07", "request_08", "request_13", "request_19"]:
    debug_request(rid)
