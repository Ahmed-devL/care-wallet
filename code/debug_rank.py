import sys, os; sys.path.insert(0, '.')
import csv, data_layer as dl, decision_engine as de
_DATASET = '../dataset'
samples = {r['request_id']: r for r in csv.DictReader(open(_DATASET+'/sample_requests.csv', encoding='utf-8'))}

for rid in ['request_07', 'request_02', 'request_12', 'request_17', 'request_22']:
    req = samples[rid]
    uid = req['user_id']
    profile = dl.get_profile(uid)
    cands = de._generate_candidates(rid, uid, profile, req, [])
    surviving = de._filter_candidates(cands, uid, profile, req['request_date'], float(req['requested_amount']), [])
    print(f'=== {rid} surviving candidates:')
    for c in surviving:
        key = de._rank_key(c)
        print(f'  {c.method} option={c.payment_option_id} first={c.first_payment_date} deadline={c.completes_by_deadline} total={c.total_payable} key={key}')
    ranked = de._sort_candidates(surviving)
    if ranked:
        w = ranked[0]
        print(f'  WINNER: {w.method} option={w.payment_option_id}')
    print()
