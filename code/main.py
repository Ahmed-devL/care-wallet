"""
main.py — Buy or Wait? Full pipeline entry point.

Usage:
    python main.py [--replay] [--output path/to/output.csv]

Flags:
    --replay        Read only from cache; make zero new API calls.
    --output FILE   Write output CSV to FILE (default: ../dataset/output.csv)

Pipeline:
    Phase 1: data_layer loads all CSVs once.
    Phase 2/3: decision_engine.decide() runs the forecast + decision pipeline.
    Phase 4: extraction.extract_for_request() runs LLM extraction (or replay).
    Phase 5: LLM-generated explanation appended to each output row.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time

# Ensure our code directory is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import data_layer as dl
import decision_engine as de

# Conditional extraction import — if llm_client is not available, run without
try:
    import extraction
    import llm_client
    _EXTRACTION_AVAILABLE = True
except ImportError:
    _EXTRACTION_AVAILABLE = False

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATASET = os.path.join(_HERE, "..", "dataset")

OUTPUT_COLUMNS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]

# Cache extraction results per user (each user's messages extracted once)
_user_overrides_cache: dict[str, list[dict]] = {}


def get_overrides_for_user(user_id: str) -> list[dict]:
    """Get Phase 4 extraction overrides for a user, cached per user."""
    global _user_overrides_cache
    if user_id in _user_overrides_cache:
        return _user_overrides_cache[user_id]
    if not _EXTRACTION_AVAILABLE:
        _user_overrides_cache[user_id] = []
        return []
    try:
        facts = extraction.extract_user_facts(user_id)
        overrides = extraction.facts_to_overrides(facts)
    except Exception as e:
        print(f"  [user={user_id}] Extraction error (no overrides): {type(e).__name__}: {e}")
        overrides = []
    _user_overrides_cache[user_id] = overrides
    return overrides


def parse_args():
    parser = argparse.ArgumentParser(description="Buy or Wait? financial decision pipeline")
    parser.add_argument("--replay", action="store_true",
                        help="Read from LLM cache only; make zero new API calls.")
    parser.add_argument("--output", default=os.path.join(_DATASET, "output.csv"),
                        help="Output CSV path (default: dataset/output.csv)")
    return parser.parse_args()


def generate_explanation(result: dict, request: dict, user_id: str) -> str:
    """
    Phase 5: Generate a concise, grounded decision explanation.
    Uses only the numbers already computed — never invents new facts.
    Falls back to a rule-based explanation if LLM is unavailable.
    """
    method = result["recommended_payment_method"]
    status = result["affordability_status"]
    amount_safe = result["amount_safe_to_pay"]
    requested = float(request.get("requested_amount", 0))
    plan = result["payment_plan"]
    edfp = result["earliest_date_for_full_payment"]
    changes = result["spending_changes_needed"]
    profile = dl.get_profile(user_id)
    currency = profile.get("home_currency", "")

    if method == "not_recommended":
        return (
            f"The requested amount of {requested:.2f} {currency} is not affordable "
            f"within the 90-day forecast window. Current safe payment capacity is "
            f"{amount_safe:.2f} {currency}, which is insufficient even after considering "
            f"all projected income and expenses. No safe payment plan can be constructed "
            f"without exceeding minimum balance requirements."
        )
    elif method == "full_payment":
        if status == "affordable_now":
            return (
                f"The full amount of {requested:.2f} {currency} can be paid immediately "
                f"on {edfp}. After accounting for all projected expenses and commitments "
                f"over the next 90 days, the balance remains above the minimum required level. "
                f"{'Spending adjustments (' + changes + ') are required to maintain sufficient balance.' if changes != 'none' else 'No spending changes are needed.'}"
            )
        else:
            return (
                f"Full payment of {requested:.2f} {currency} is feasible with a plan. "
                f"The payment can be made on {edfp}. "
                f"{'Spending adjustments (' + changes + ') unlock the necessary headroom.' if changes != 'none' else 'The balance supports this payment without spending changes.'}"
            )
    elif method == "installments":
        n_payments = plan.count("|") + 1 if plan and plan != "none" else 0
        return (
            f"The requested amount is best paid in {n_payments} installments per the "
            f"offered payment plan ({plan[:80] if plan else 'see plan'}). "
            f"Each installment stays within the safe payment window given projected cash flow. "
            f"{'Spending adjustments (' + changes + ') are needed.' if changes != 'none' else 'No spending changes are required.'}"
        )
    elif method == "partial_payment":
        parts = plan.split("|") if plan and plan != "none" else []
        return (
            f"A partial payment of {amount_safe:.2f} {currency} can be made immediately, "
            f"with the remainder of {requested - amount_safe:.2f} {currency} payable on {edfp}. "
            f"This splits the total into two payments that each respect the minimum balance requirement."
        )
    elif method == "wait":
        return (
            f"The full amount of {requested:.2f} {currency} cannot be safely paid today "
            f"(current safe capacity: {amount_safe:.2f} {currency}). "
            f"The earliest safe date for full payment is {edfp}, when projected cash flow "
            f"provides sufficient headroom above the minimum balance requirement."
        )
    else:
        return f"Decision: {status}. Recommended method: {method}."


def run_pipeline(args):
    """Main pipeline: load data, run decisions, write output.csv."""
    print("Buy or Wait? — Starting pipeline run...")
    if args.replay:
        print("  [REPLAY MODE] Reading from cache only. No new API calls.")
        if _EXTRACTION_AVAILABLE:
            llm_client.set_replay_mode(True)

    # Load all requests
    requests = dl.get_all_requests()
    print(f"  Loaded {len(requests)} requests from requests.csv")

    output_rows = []
    errors = []
    start_time = time.time()

    for i, req in enumerate(requests, 1):
        rid = req["request_id"]
        uid = req["user_id"]
        rdate = req["request_date"]

        # Phase 4: Extract overrides from messages/images
        overrides = get_overrides_for_user(uid)

        try:
            # Phase 2+3: Decision engine
            result = de.decide(rid, uid, overrides=overrides, request=req)

            # Phase 5: Explanation
            explanation = generate_explanation(result, req, uid)
            result["decision_explanation"] = explanation

            row = {
                "request_id": rid,
                "amount_safe_to_pay": f"{result['amount_safe_to_pay']:.2f}",
                "affordability_status": result["affordability_status"],
                "recommended_payment_method": result["recommended_payment_method"],
                "payment_plan": result["payment_plan"] or "none",
                "earliest_date_for_full_payment": result.get("earliest_date_for_full_payment") or "",
                "spending_changes_needed": result.get("spending_changes_needed") or "none",
                "decision_explanation": explanation,
            }
            output_rows.append(row)

        except Exception as e:
            errors.append((rid, str(e)))
            print(f"  [{rid}] ERROR: {e}")
            # Write a fallback row
            output_rows.append({
                "request_id": rid,
                "amount_safe_to_pay": "0",
                "affordability_status": "not_affordable",
                "recommended_payment_method": "not_recommended",
                "payment_plan": "none",
                "earliest_date_for_full_payment": "",
                "spending_changes_needed": "none",
                "decision_explanation": f"Error during processing: {e}",
            })

        if i % 25 == 0:
            elapsed = time.time() - start_time
            print(f"  Progress: {i}/{len(requests)} requests ({elapsed:.1f}s)")

    # Write output.csv
    output_path = args.output
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(output_rows)

    elapsed = time.time() - start_time
    print(f"\nDone! {len(output_rows)} rows written to {output_path}")
    print(f"Total time: {elapsed:.1f}s")
    if errors:
        print(f"Errors on {len(errors)} requests: {[r for r, _ in errors]}")
    else:
        print("No errors.")

    return output_rows


if __name__ == "__main__":
    args = parse_args()
    run_pipeline(args)
