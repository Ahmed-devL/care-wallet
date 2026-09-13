"""
test_decision_engine.py — Phase 3 tests, written BEFORE decision_engine.py exists.

Run with: python test_decision_engine.py
Expected on first run: ImportError / all-fail (no implementation yet).
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_DATASET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dataset")


def load_samples():
    with open(os.path.join(_DATASET, "sample_requests.csv"), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _fmt_plan(plan: list) -> str:
    if not plan:
        return "none"
    return "|".join(f"{d}:{a}" for d, a in plan)


def main():
    import decision_engine as de

    samples = load_samples()

    fields = [
        "affordability_status",
        "recommended_payment_method",
        "payment_plan",
        "earliest_date_for_full_payment",
        "spending_changes_needed",
    ]
    total = len(samples)
    passes = {f: 0 for f in fields}
    mismatches = []

    for row in samples:
        rid = row["request_id"]
        uid = row["user_id"]
        result = de.decide(rid, uid, overrides=None)

        row_ok = True
        row_diff = {"request_id": rid}

        # affordability_status
        expected_status = row["affordability_status"]
        got_status = result["affordability_status"]
        if got_status == expected_status:
            passes["affordability_status"] += 1
        else:
            row_ok = False
            row_diff["affordability_status"] = f"exp={expected_status} got={got_status}"

        # recommended_payment_method
        expected_method = row["recommended_payment_method"]
        got_method = result["recommended_payment_method"]
        if got_method == expected_method:
            passes["recommended_payment_method"] += 1
        else:
            row_ok = False
            row_diff["recommended_payment_method"] = f"exp={expected_method} got={got_method}"

        # payment_plan (compare normalised)
        expected_plan = row["payment_plan"].strip() or "none"
        got_plan_raw = result.get("payment_plan") or "none"
        if isinstance(got_plan_raw, list):
            got_plan = _fmt_plan(got_plan_raw)
        else:
            got_plan = str(got_plan_raw)

        def _norm(plan_str):
            if plan_str == "none":
                return "none"
            parts = []
            for seg in plan_str.split("|"):
                seg = seg.strip()
                if not seg:
                    continue
                d, a = seg.split(":")
                parts.append(f"{d}:{float(a):.2f}")
            return "|".join(parts)

        if _norm(got_plan) == _norm(expected_plan):
            passes["payment_plan"] += 1
        else:
            row_ok = False
            row_diff["payment_plan"] = f"exp={expected_plan} got={got_plan}"

        # earliest_date_for_full_payment
        expected_edfp = (row["earliest_date_for_full_payment"] or "").strip() or None
        got_edfp = result.get("earliest_date_for_full_payment") or None
        if got_edfp == expected_edfp:
            passes["earliest_date_for_full_payment"] += 1
        else:
            row_ok = False
            row_diff["earliest_date_for_full_payment"] = f"exp={expected_edfp} got={got_edfp}"

        # spending_changes_needed
        expected_changes = (row["spending_changes_needed"] or "none").strip()
        got_changes = (result.get("spending_changes_needed") or "none").strip()
        if got_changes == expected_changes:
            passes["spending_changes_needed"] += 1
        else:
            row_ok = False
            row_diff["spending_changes_needed"] = f"exp={expected_changes} got={got_changes}"

        if not row_ok:
            mismatches.append(row_diff)

    print("=" * 70)
    print("Phase 3 Decision Engine --- Sample Tests")
    print("=" * 70)
    for f in fields:
        print(f"  {f}: {passes[f]}/{total}")

    if mismatches:
        print(f"\nMISMATCHES ({len(mismatches)}):")
        for m in mismatches:
            print(f"  {m['request_id']}:")
            for k, v in m.items():
                if k != "request_id":
                    print(f"    {k}: {v}")
    else:
        print("\nAll fields match on all 25 rows.")

    # Invariant check: every recommended plan passes its own safety check
    print("\n--- Invariant check: recommended plan survives safety ---")
    import forecast_engine as fe
    import data_layer as dl

    invariant_passes = 0
    invariant_fails = []
    for row in samples:
        rid = row["request_id"]
        uid = row["user_id"]
        result = de.decide(rid, uid, overrides=None)
        method = result["recommended_payment_method"]
        if method in ("wait", "not_recommended"):
            invariant_passes += 1
            continue
        plan_str = result.get("payment_plan") or "none"
        if plan_str == "none" or not plan_str:
            invariant_passes += 1
            continue
        changes_str = result.get("spending_changes_needed") or "none"
        plan_overrides = de.spending_changes_to_overrides(changes_str, uid)
        profile = dl.get_profile(uid)
        min_keep = float(profile["minimum_balance_to_keep"])

        # Parse plan into list of (date_str, amount) tuples
        plan_parts = []
        for seg in plan_str.split("|"):
            seg = seg.strip()
            if seg:
                d, a = seg.split(":")
                plan_parts.append((d, float(a)))

        # For all methods: check that the plan itself passes safety
        rdate = row["request_date"]
        ok = de._passes_safety(uid, rdate, plan_parts, plan_overrides, min_keep)

        if ok:
            invariant_passes += 1
        else:
            invariant_fails.append((rid, method, plan_str[:60]))

    print(f"  Invariant passes: {invariant_passes}/{total}")
    if invariant_fails:
        print(f"  INVARIANT FAILURES ({len(invariant_fails)}):")
        for rid, method, plan in invariant_fails:
            print(f"    {rid}: method={method} plan={plan}")
    else:
        print("  All plans independently pass the safety check.")



if __name__ == "__main__":
    main()
