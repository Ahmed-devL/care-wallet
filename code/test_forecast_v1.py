"""
test_forecast_v1.py — Phase 2 sample validation (no LLM/evidence overrides).

Compares forecast_engine.amount_safe_to_pay() and earliest_date_for_full_payment()
against dataset/sample_requests.csv for all 25 rows. Run directly:
    python3 test_forecast_v1.py
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import forecast_engine as fe

_DATASET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dataset")


def load_samples():
    with open(os.path.join(_DATASET, "sample_requests.csv"), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    samples = load_samples()
    amt_pass = 0
    date_pass = 0
    rows_out = []
    for row in samples:
        rid = row["request_id"]
        uid = row["user_id"]
        rdate = row["request_date"]
        requested = float(row["requested_amount"])
        expected_amt = float(row["amount_safe_to_pay"])
        expected_date = row["earliest_date_for_full_payment"] or None

        got_amt = fe.amount_safe_to_pay(uid, rdate, requested)
        got_date = fe.earliest_date_for_full_payment(uid, rdate, requested)

        amt_ok = abs(got_amt - expected_amt) < 1.0  # tolerance for rounding
        date_ok = (got_date == expected_date)

        amt_pass += amt_ok
        date_pass += date_ok

        rows_out.append((rid, uid, expected_amt, got_amt, amt_ok, expected_date, got_date, date_ok))

    print(f"{'request':10} {'user':8} {'exp_amt':>14} {'got_amt':>14} {'ok':3}  {'exp_date':10} {'got_date':10} {'ok':3}")
    for r in rows_out:
        rid, uid, exp_a, got_a, aok, exp_d, got_d, dok = r
        print(f"{rid:10} {uid:8} {exp_a:14.2f} {got_a:14.2f} {'Y' if aok else 'N':3}  "
              f"{(exp_d or '-'):10} {(got_d or '-'):10} {'Y' if dok else 'N':3}")

    print()
    print(f"amount_safe_to_pay: {amt_pass}/{len(samples)} match")
    print(f"earliest_date_for_full_payment: {date_pass}/{len(samples)} match")


if __name__ == "__main__":
    main()
