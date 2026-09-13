import csv
samples = list(csv.DictReader(open('../dataset/sample_requests.csv', encoding='utf-8')))
options = list(csv.DictReader(open('../dataset/request_payment_options.csv', encoding='utf-8')))
opts_by_req = {}
for o in options:
    opts_by_req.setdefault(o['request_id'], []).append(o)

for r in samples:
    rid = r['request_id']
    opts = opts_by_req.get(rid, [])
    opt_strs = [o['payment_method'] + '(' + o['payment_option_id'] + ',months=' + o['number_of_payments'] + ')' for o in opts]
    print(f"--- {rid} status={r['affordability_status']} method={r['recommended_payment_method']} allows_partial={r['allows_partial_payment']}")
    print(f"    amount_safe={r['amount_safe_to_pay']} requested={r['requested_amount']} spend_changes={r['spending_changes_needed']}")
    print(f"    payment_plan={r['payment_plan'][:100]}")
    print(f"    options: {opt_strs}")
