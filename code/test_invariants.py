import csv
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATASET = os.path.join(_HERE, "..", "dataset")

def check_invariants():
    output_path = os.path.join(_DATASET, "output.csv")
    requests_path = os.path.join(_DATASET, "requests.csv")
    options_path = os.path.join(_DATASET, "request_payment_options.csv")
    events_path = os.path.join(_DATASET, "financial_events.csv")
    
    # Load requests
    requests = {}
    with open(requests_path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            requests[row["request_id"]] = float(row["requested_amount"])
            
    # Load options
    options_by_req = {}
    with open(options_path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rid = row["request_id"]
            if rid not in options_by_req:
                options_by_req[rid] = []
            options_by_req[rid].append(row)
            
    # Load events to check flexible categories
    events_by_id = {}
    with open(events_path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            events_by_id[row["event_id"]] = row
            
    expected_cols = [
        "request_id", "amount_safe_to_pay", "affordability_status",
        "recommended_payment_method", "payment_plan",
        "earliest_date_for_full_payment", "spending_changes_needed",
        "decision_explanation"
    ]
    
    with open(output_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        if header != expected_cols:
            print(f"FAIL: Header mismatch. Got {header}")
            return
        
        rows = list(reader)
        if len(rows) != 250:
            print(f"FAIL: Expected 250 data rows, got {len(rows)}")
            return
            
        print("PASS: output.csv has exactly 250 data rows + 1 header row, in exact column order.")
        
        fails = {
            "amount_bounds": 0,
            "installment_match": 0,
            "spending_changes": 0,
            "chronological_plan": 0,
        }
        
        for i, row in enumerate(rows):
            r = dict(zip(header, row))
            rid = r["request_id"]
            method = r["recommended_payment_method"]
            plan = r["payment_plan"]
            changes = r["spending_changes_needed"]
            
            try:
                amt_safe = float(r["amount_safe_to_pay"])
            except ValueError:
                amt_safe = -1
                
            req_amt = requests.get(rid, 0)
            
            # Check 1: 0 <= amount_safe_to_pay <= requested_amount
            if not (0 <= amt_safe <= req_amt + 0.01):
                fails["amount_bounds"] += 1
                print(f"  [{rid}] amount_safe_to_pay ({amt_safe}) not in [0, {req_amt}]")
                
            # Check 2: payment_plan chronological and formatted
            if plan and plan != "none":
                dates = []
                try:
                    for part in plan.split("|"):
                        d, a = part.split(":")
                        dates.append(d)
                        float(a)
                    if dates != sorted(dates):
                        fails["chronological_plan"] += 1
                        print(f"  [{rid}] payment_plan not chronological: {plan}")
                except Exception as e:
                    fails["chronological_plan"] += 1
                    print(f"  [{rid}] payment_plan format error: {plan}")
                    
            # Check 3: installments match option
            if method == "installments":
                # We expect the number of payments to match one of the options
                num_payments = len(plan.split("|"))
                opts = options_by_req.get(rid, [])
                match = False
                for o in opts:
                    if o["payment_method"] == "installments" and int(o["number_of_payments"]) == num_payments:
                        match = True
                        break
                if not match:
                    fails["installment_match"] += 1
                    print(f"  [{rid}] installments plan ({num_payments} payments) doesn't match options")
                    
            # Check 4: spending changes target flexible
            if changes and changes != "none":
                for change in changes.split("|"):
                    parts = change.split(":")
                    action = parts[0]
                    ev_id = parts[1]
                    ev = events_by_id.get(ev_id)
                    if not ev:
                        fails["spending_changes"] += 1
                        print(f"  [{rid}] spending change targets unknown event {ev_id}")
                    else:
                        flex = ev["flexibility"].lower()
                        if action == "stop" and flex not in ["stoppable", "reducible_or_stoppable"]:
                            fails["spending_changes"] += 1
                            print(f"  [{rid}] stop targets non-stoppable event {ev_id}")
                        elif action == "reduce_to" and flex not in ["reducible", "reducible_or_stoppable"]:
                            fails["spending_changes"] += 1
                            print(f"  [{rid}] reduce_to targets non-reducible event {ev_id}")
                            
        for k, v in fails.items():
            if v == 0:
                print(f"PASS: {k}")
            else:
                print(f"FAIL: {k} ({v} violations)")

if __name__ == "__main__":
    check_invariants()
