"""
decision_engine.py — Phase 3: Generate → Filter → Rank decision pipeline.

Architecture: strictly generate-then-filter-then-rank. No hardcoded if/else
rules about which method to pick. Every method is generated as a Candidate,
filtered through the forecast safety check and eligibility rules, then ranked
by the 6-key ordering from the spec.

Public API
----------
  decide(request_id, user_id, overrides=None) -> dict
    Returns the 8 output fields for a single request.

  spending_changes_to_overrides(changes_str, user_id) -> list[dict]
    Converts a "stop:event_X|reduce_to:event_Y:amount" string into a list
    of override dicts suitable for forecast_engine.simulate().
"""

from __future__ import annotations

import itertools
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import data_layer as dl
import forecast_engine as fe

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse(d: str) -> date:
    y, m, dd = d.split("-")
    return date(int(y), int(m), int(dd))


def _fmt(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _parse_list(field_value: str) -> list[str]:
    """Split a pipe-separated profile field into a cleaned list."""
    if not field_value:
        return []
    return [x.strip() for x in field_value.split("|") if x.strip()]


# ---------------------------------------------------------------------------
# Candidate dataclass
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    method: str                          # full_payment | partial_payment | installments | wait
    payment_plan: list[tuple[str, float]]  # [(date_str, amount), ...]
    total_payable: float
    num_payments: int
    first_payment_date: str
    completes_by_deadline: bool
    payment_option_id: Optional[str] = None
    spending_changes: str = "none"        # "none" or "stop:X|reduce_to:X:Y"
    overrides_used: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Filter 2: eligibility against user preferences
# ---------------------------------------------------------------------------

def _user_allows_method(method: str, profile: dict) -> bool:
    """True if method is in user's payment_methods_user_will_consider (or 'wait'/'not_recommended')."""
    methods_allowed = _parse_list(profile.get("payment_methods_user_will_consider", ""))
    if not methods_allowed:
        return True  # no restriction = anything allowed
    if method in ("wait", "not_recommended"):
        return True
    return method in methods_allowed


def _installment_months_ok(num_payments: int, profile: dict) -> bool:
    """True if number of installments doesn't exceed user's max_installment_months."""
    max_months_str = (profile.get("max_installment_months") or "").strip()
    if not max_months_str:
        return False  # blank = user will not consider installments
    try:
        max_months = int(max_months_str)
    except ValueError:
        return False
    return num_payments <= max_months


# ---------------------------------------------------------------------------
# Filter 1: safety — passes forecast_engine.simulate() balance check
# ---------------------------------------------------------------------------

def _passes_safety(
    user_id: str,
    request_date_str: str,
    plan: list[tuple[str, float]],
    overrides: list[dict],
    min_keep: float,
) -> bool:
    """
    Return True if every payment in `plan` can be made without the balance
    ever dipping below min_keep for the 90-day window from request_date.

    Algorithm:
    - Start with the unmodified trajectory (spending-change overrides already baked in).
    - For each day in the trajectory, subtract the cumulative payments made
      UP TO AND INCLUDING that day. Check that the resulting balance >= min_keep.

    This correctly handles installment plans: payment 2 only starts reducing
    balances from its own date onward, not from payment 1's date.
    """
    sim = fe.simulate(user_id, request_date_str, overrides)
    trajectory = sim["trajectory"]  # [(date_str, balance), ...]

    request_date = _parse(request_date_str)
    window_end = request_date + timedelta(days=fe.WINDOW_DAYS)

    # Filter plan to payments within the 90-day window
    plan_in_window = [
        (d, a) for d, a in plan
        if _parse(d) <= window_end
    ]
    sorted_plan = sorted(plan_in_window, key=lambda t: t[0])

    # For each trajectory date, compute cumulative paid so far
    cumulative_paid = 0.0
    plan_idx = 0
    n_plan = len(sorted_plan)

    for traj_date_str, traj_balance in trajectory:
        # Advance cumulative_paid for any payments on or before this date
        while plan_idx < n_plan and sorted_plan[plan_idx][0] <= traj_date_str:
            cumulative_paid += sorted_plan[plan_idx][1]
            plan_idx += 1

        effective_balance = traj_balance - cumulative_paid
        if effective_balance < min_keep - 0.01:
            return False

    return True



# ---------------------------------------------------------------------------
# Spending-change overrides
# ---------------------------------------------------------------------------

def spending_changes_to_overrides(changes_str: str, user_id: str) -> list[dict]:
    """
    Convert a spending_changes_needed string like
    "stop:event_476|reduce_to:event_989:665950"
    into a list of override dicts for forecast_engine.simulate().
    """
    overrides = []
    if not changes_str or changes_str == "none":
        return overrides
    events = dl.get_events(user_id)
    ev_by_id = {e["event_id"]: e for e in events}
    for action in changes_str.split("|"):
        action = action.strip()
        if not action:
            continue
        if action.startswith("stop:"):
            event_id = action[5:]
            ev = ev_by_id.get(event_id)
            if ev:
                overrides.append({
                    "type": "cancel_series",
                    "category": ev["category"],
                    # Also store event_id so we can reconstruct the string
                    "_event_id": event_id,
                })
        elif action.startswith("reduce_to:"):
            parts = action[10:].split(":")
            if len(parts) >= 2:
                event_id = parts[0]
                new_amount = float(parts[1])
                ev = ev_by_id.get(event_id)
                if ev:
                    overrides.append({
                        "type": "amend_amount",
                        "category": ev["category"],
                        "new_amount": new_amount,
                        "_event_id": event_id,
                    })
    return overrides


def _overrides_to_changes_str(overrides: list[dict]) -> str:
    """Reverse of spending_changes_to_overrides — for output."""
    parts = []
    for o in overrides:
        eid = o.get("_event_id", "")
        if o["type"] == "cancel_series":
            parts.append(f"stop:{eid}")
        elif o["type"] == "amend_amount":
            parts.append(f"reduce_to:{eid}:{o['new_amount']:.2f}")
    return "|".join(parts) if parts else "none"


# ---------------------------------------------------------------------------
# Payment plan builder for installment options
# ---------------------------------------------------------------------------

def _build_installment_plan(option: dict) -> list[tuple[str, float]]:
    """Build chronological [(date_str, amount)] list from a payment option row."""
    n = int(option["number_of_payments"])
    pay_amount = float(option["payment_amount"])
    first_date = _parse(option["first_payment_date"])
    freq = int(option["payment_frequency_days"]) if option.get("payment_frequency_days") else 30

    plan = []
    cur = first_date
    for _ in range(n):
        plan.append((_fmt(cur), round(pay_amount, 2)))
        cur += timedelta(days=freq)
    return plan


def _build_partial_payment_plan(
    amount_safe: float, requested_amount: float, request_date_str: str, edfp: Optional[str]
) -> Optional[list[tuple[str, float]]]:
    """
    Build the 2-payment plan for partial_payment:
      Payment 1: amount_safe on request_date
      Payment 2: (requested_amount - amount_safe) on earliest_date_for_full_payment
    Returns None if we can't build a valid plan.
    """
    if edfp is None:
        return None
    remainder = round(requested_amount - amount_safe, 2)
    if remainder <= 0.01:
        return None
    plan = [
        (request_date_str, round(amount_safe, 2)),
        (edfp, remainder),
    ]
    return plan


# ---------------------------------------------------------------------------
# Candidate generation helpers
# ---------------------------------------------------------------------------

def _earliest_wait_date(
    user_id: str,
    request_date_str: str,
    requested_amount: float,
    profile: dict,
    overrides: Optional[list[dict]],
) -> Optional[str]:
    """
    Find the first date d in the 90-day trajectory (strictly after request_date)
    where paying requested_amount on day d passes the safety check.

    The safety check for 'wait': paying on day d means we subtract requested_amount
    from the balance on day d and check whether the resulting balance >= min_keep
    for all days from d onward (suffix-min from d).

    This gives the first day where the user could safely do a lump-sum payment.
    """
    min_keep = float(profile["minimum_balance_to_keep"])
    sim = fe.simulate(user_id, request_date_str, overrides)
    traj = sim["trajectory"]

    for i, (d_str, _) in enumerate(traj):
        if d_str == request_date_str:
            continue  # must be strictly after request_date
        # Suffix-min from day i onward
        suffix_min = min(b for _, b in traj[i:])
        if suffix_min - requested_amount >= min_keep - 0.01:
            return d_str
    return None


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------

def _generate_candidates(
    request_id: str,
    user_id: str,
    profile: dict,
    request: dict,
    overrides: Optional[list[dict]],
) -> list[Candidate]:
    """
    Enumerate ALL possible plans for this request. Includes:
    - One candidate per row in request_payment_options.csv (full_payment and installments)
    - partial_payment (if allows_partial_payment is 'true' and amount_safe < requested)
    - wait (always generated)
    """
    candidates: list[Candidate] = []
    request_date_str = request["request_date"]
    request_date = _parse(request_date_str)
    requested_amount = float(request["requested_amount"])
    allows_partial = (request.get("allows_partial_payment") or "").strip().lower() == "true"
    desired_completion_date_str = (request.get("desired_completion_date") or "").strip()
    desired_date = _parse(desired_completion_date_str) if desired_completion_date_str else None

    # Payment options from CSV (full_payment and installments)
    payment_options = dl.get_payment_options(request_id)

    for option in payment_options:
        method = option["payment_method"]
        n_payments = int(option["number_of_payments"])

        if method == "full_payment":
            pay_date = option["first_payment_date"]
            plan = [(pay_date, round(float(option["total_payable_amount"]), 2))]
            total = float(option["total_payable_amount"])
            completes = (desired_date is None) or (_parse(pay_date) <= desired_date)
            candidates.append(Candidate(
                method="full_payment",
                payment_plan=plan,
                total_payable=total,
                num_payments=1,
                first_payment_date=pay_date,
                completes_by_deadline=completes,
                payment_option_id=option["payment_option_id"],
            ))

        elif method == "installments":
            plan = _build_installment_plan(option)
            total = float(option["total_payable_amount"])
            last_date = plan[-1][0] if plan else request_date_str
            completes = (desired_date is None) or (_parse(last_date) <= desired_date)
            candidates.append(Candidate(
                method="installments",
                payment_plan=plan,
                total_payable=total,
                num_payments=n_payments,
                first_payment_date=plan[0][0] if plan else request_date_str,
                completes_by_deadline=completes,
                payment_option_id=option["payment_option_id"],
            ))

    # partial_payment — only if allowed and amount_safe < requested
    if allows_partial:
        # We need the amount_safe_to_pay first (uses baseline overrides)
        base_safe = fe.amount_safe_to_pay(user_id, request_date_str, requested_amount, overrides)
        if 0 < base_safe < requested_amount - 0.01:
            edfp = fe.earliest_date_for_full_payment(user_id, request_date_str, requested_amount, overrides)
            partial_plan = _build_partial_payment_plan(base_safe, requested_amount, request_date_str, edfp)
            if partial_plan and edfp:
                edfp_date = _parse(edfp)
                completes = (desired_date is None) or (edfp_date <= desired_date)
                candidates.append(Candidate(
                    method="partial_payment",
                    payment_plan=partial_plan,
                    total_payable=requested_amount,
                    num_payments=2,
                    first_payment_date=request_date_str,
                    completes_by_deadline=completes,
                    payment_option_id=None,
                ))

    # wait — look for first date where point-in-time balance >= min_keep + requested
    # (simpler check than suffix-min: just needs enough balance on that specific day)
    wait_edfp = _earliest_wait_date(user_id, request_date_str, requested_amount, profile, overrides)
    if wait_edfp and wait_edfp != request_date_str:
        wait_plan = [(wait_edfp, round(requested_amount, 2))]
        edfp_date = _parse(wait_edfp)
        completes = (desired_date is None) or (edfp_date <= desired_date)
        candidates.append(Candidate(
            method="wait",
            payment_plan=wait_plan,
            total_payable=requested_amount,
            num_payments=1,
            first_payment_date=wait_edfp,
            completes_by_deadline=completes,
            payment_option_id=None,
        ))

    return candidates


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def _filter_candidates(
    candidates: list[Candidate],
    user_id: str,
    profile: dict,
    request_date_str: str,
    requested_amount: float,
    base_overrides: list[dict],
) -> list[Candidate]:
    """
    Apply Filter 1 (safety) and Filter 2 (eligibility) to each candidate.
    Returns the subset that passes both.
    """
    min_keep = float(profile["minimum_balance_to_keep"])
    passing = []

    for cand in candidates:
        # Filter 2a: user's accepted payment methods
        if not _user_allows_method(cand.method, profile):
            continue

        # Filter 2b: installment month limit
        if cand.method == "installments":
            if not _installment_months_ok(cand.num_payments, profile):
                continue

        # Filter 1: safety — 90-day balance never below min_keep
        if cand.method == "wait":
            # "wait" always passes safety by construction: we only create it
            # if earliest_date_for_full_payment exists, meaning there IS a
            # date it's safe.
            passing.append(cand)
            continue

        # For full_payment and installments, the first payment date may be
        # request_date (same-day) or in the future. Use the plan as-is.
        plan_to_check = cand.payment_plan
        # Combine spending-change overrides with base_overrides
        all_overrides = base_overrides + cand.overrides_used

        if _passes_safety(user_id, request_date_str, plan_to_check, all_overrides, min_keep):
            passing.append(cand)

    return passing


# ---------------------------------------------------------------------------
# Ranking — 6 keys, strictly applied
# ---------------------------------------------------------------------------

def _option_id_num(oid: Optional[str]) -> int:
    """Extract numeric suffix of payment_option_id for sorting; fallback to large number."""
    if not oid:
        return 99999
    try:
        return int(oid.split("_")[-1])
    except (ValueError, IndexError):
        return 99999


def _method_priority(method: str) -> int:
    """
    Priority for method selection: lower = better.
    wait and not_recommended are last resorts only.
    Among payment methods: full_payment first (no fee), then partial, then installments.
    """
    return {
        "full_payment": 0,
        "partial_payment": 1,
        "installments": 2,
        "wait": 3,
        "not_recommended": 4,
    }.get(method, 5)


def _rank_key(cand: Candidate) -> tuple:
    """
    Rank by (lower = better):
    1. completes_by_deadline (True first → 0, False → 1)
    2. no spending changes (True first → 0, has changes → 1)
    3. minimizes total paid (lower is better)
    4. starts earlier (earlier date is better)
    5. fewer payments (fewer is better)
    6. lowest payment_option_id numeric suffix
    NOTE: 'wait' is always ranked last within each tier (via method_priority added to tie-break)
    """
    return (
        0 if cand.completes_by_deadline else 1,
        0 if (cand.spending_changes == "none" or not cand.spending_changes) else 1,
        _method_priority(cand.method),  # prefer actual payment over wait
        cand.total_payable,
        cand.first_payment_date,
        cand.num_payments,
        _option_id_num(cand.payment_option_id),
    )


def _sort_candidates(candidates: list[Candidate]) -> list[Candidate]:
    return sorted(candidates, key=_rank_key)


# ---------------------------------------------------------------------------
# Spending-change search (Filter 3)
# ---------------------------------------------------------------------------

def _find_flexible_events(user_id: str, profile: dict) -> list[dict]:
    """
    Return recurring events that are (a) in a category the user permits
    changing, and (b) are flexible (stoppable or reducible).
    """
    events = dl.get_events(user_id)
    willing_to_reduce = set(_parse_list(profile.get("expense_categories_user_is_willing_to_reduce", "")))
    willing_to_stop = set(_parse_list(profile.get("expense_categories_user_is_willing_to_stop", "")))
    categories_allowed = willing_to_reduce | willing_to_stop

    seen_categories: set[str] = set()
    candidates = []
    for ev in events:
        cat = ev.get("category", "")
        if cat not in categories_allowed:
            continue
        if not dl.is_changeable(ev):
            continue
        if cat in seen_categories:
            continue
        # Only include recurring events (category has >= 2 settled events)
        cat_settled = [
            e for e in events
            if e["category"] == cat and e["status"] == "settled"
        ]
        if len(cat_settled) < 2:
            continue
        # Use the most recent settled event as the representative
        cat_settled.sort(key=lambda e: e["settlement_date"])
        rep = cat_settled[-1]

        # Determine what actions are allowed for this event
        can_stop = dl.is_stoppable(rep) and cat in willing_to_stop
        can_reduce = dl.is_reducible(rep) and cat in willing_to_reduce
        if can_stop or can_reduce:
            candidates.append({
                "event": rep,
                "can_stop": can_stop,
                "can_reduce": can_reduce,
                "category": cat,
            })
            seen_categories.add(cat)

    return candidates


def _try_spending_changes(
    user_id: str,
    profile: dict,
    request_id: str,
    request: dict,
    base_overrides: list[dict],
    max_changes: int = 3,
) -> Optional[tuple[list[Candidate], list[dict], str]]:
    """
    Try applying up to `max_changes` spending changes to unlock affordability.
    Returns (surviving_candidates, spending_overrides, changes_str) if successful,
    or None if no combo unlocks any passing candidate.
    """
    flexible = _find_flexible_events(user_id, profile)
    request_date_str = request["request_date"]
    requested_amount = float(request["requested_amount"])
    min_keep = float(profile["minimum_balance_to_keep"])

    # Build all possible spending-change override combos (up to max_changes)
    all_actions: list[dict] = []
    for item in flexible:
        ev = item["event"]
        eid = ev["event_id"]
        if item["can_stop"]:
            all_actions.append({
                "type": "cancel_series",
                "category": item["category"],
                "_event_id": eid,
            })
        if item["can_reduce"]:
            # Reduce to 50% of current amount (conservative heuristic)
            try:
                amt = float(ev.get("amount") or 0)
            except ValueError:
                amt = 0.0
            if amt > 0:
                all_actions.append({
                    "type": "amend_amount",
                    "category": item["category"],
                    "new_amount": round(amt * 0.5, 2),
                    "_event_id": eid,
                })

    # Try combos of size 1, 2, 3 (no repeated event_ids)
    for size in range(1, max_changes + 1):
        for combo in itertools.combinations(all_actions, size):
            # Ensure no two actions target the same event_id
            eids_in_combo = [a.get("_event_id") for a in combo]
            if len(set(eids_in_combo)) < len(eids_in_combo):
                continue

            spend_overrides = list(base_overrides) + list(combo)

            # Re-generate candidates with these overrides
            new_candidates = _generate_candidates(
                request_id, user_id, profile, request, spend_overrides
            )
            # Re-filter
            passing = _filter_candidates(
                new_candidates, user_id, profile, request_date_str,
                requested_amount, spend_overrides
            )
            # Exclude wait (we want a plan that actually makes the payment)
            non_wait = [c for c in passing if c.method != "wait"]
            if non_wait:
                changes_str = _overrides_to_changes_str(list(combo))
                # Attach spending changes info to each candidate
                for c in non_wait:
                    c.spending_changes = changes_str
                    c.overrides_used = list(combo)
                return non_wait, list(combo), changes_str

    return None


# ---------------------------------------------------------------------------
# Output field assembly
# ---------------------------------------------------------------------------

def _plan_to_str(plan: list[tuple[str, float]]) -> str:
    if not plan:
        return "none"
    return "|".join(f"{d}:{a:.2f}" for d, a in plan)


def _determine_affordability_status(
    method: str,
    spending_changes: str,
    amount_safe: float,
    requested_amount: float,
    request_date_str: str,
    first_payment_date: str,
) -> str:
    """
    Map the winning candidate to an affordability_status string.
    - affordable_now: full_payment or partial_payment, no spending changes, payment on request_date
    - affordable_with_plan: any plan that completes the request (via installments, partial, or spending changes)
    - affordable_later: wait (full payment on a future date)
    - not_affordable: not_recommended
    """
    if method == "not_recommended":
        return "not_affordable"
    if method == "wait":
        return "affordable_later"
    has_changes = spending_changes and spending_changes != "none"
    if method in ("full_payment", "partial_payment"):
        if not has_changes and first_payment_date == request_date_str:
            # Fully affordable today with no changes needed
            return "affordable_now"
        else:
            return "affordable_with_plan"
    if method == "installments":
        return "affordable_with_plan"
    return "affordable_with_plan"


# ---------------------------------------------------------------------------
# Main decision function
# ---------------------------------------------------------------------------

_DATASET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dataset")
_all_requests_cache: Optional[dict] = None


def _get_all_requests_by_id() -> dict:
    """Load requests.csv AND sample_requests.csv into a combined dict keyed by request_id."""
    global _all_requests_cache
    if _all_requests_cache is not None:
        return _all_requests_cache
    import csv
    combined: dict[str, dict] = {}
    for fname in ("requests.csv", "sample_requests.csv"):
        fpath = os.path.join(_DATASET_DIR, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    combined[row["request_id"]] = row
        except FileNotFoundError:
            pass
    _all_requests_cache = combined
    return combined


def decide(
    request_id: str,
    user_id: str,
    overrides: Optional[list[dict]] = None,
    request: Optional[dict] = None,
) -> dict:
    """
    Run the full generate→filter→rank pipeline for a single request.

    Returns a dict with keys:
      amount_safe_to_pay, affordability_status, recommended_payment_method,
      payment_plan, earliest_date_for_full_payment, spending_changes_needed,
      decision_explanation (placeholder — Phase 5 fills this in)
    """
    overrides = overrides or []

    # Load context
    profile = dl.get_profile(user_id)
    if request is None:
        all_requests = _get_all_requests_by_id()
        request = all_requests[request_id]
    request_date_str = request["request_date"]
    requested_amount = float(request["requested_amount"])
    min_keep = float(profile["minimum_balance_to_keep"])

    # Baseline safe amount (no spending changes)
    base_safe = fe.amount_safe_to_pay(user_id, request_date_str, requested_amount, overrides)
    edfp_full = fe.earliest_date_for_full_payment(user_id, request_date_str, requested_amount, overrides)

    # Step 1: Generate candidates
    candidates = _generate_candidates(
        request_id, user_id, profile, request, overrides
    )

    # Step 2 & 3: Filter (safety + eligibility)
    surviving = _filter_candidates(
        candidates, user_id, profile, request_date_str, requested_amount, overrides
    )

    spending_changes_str = "none"
    spending_overrides_used: list[dict] = []

    if not surviving:
        # Step 3: Attempt spending changes
        result = _try_spending_changes(
            user_id, profile, request_id, request, overrides
        )
        if result is not None:
            surviving, spending_overrides_used, spending_changes_str = result
        else:
            # not_affordable
            return {
                "amount_safe_to_pay": round(base_safe, 2),
                "affordability_status": "not_affordable",
                "recommended_payment_method": "not_recommended",
                "payment_plan": "none",
                "earliest_date_for_full_payment": "",
                "spending_changes_needed": "none",
                "decision_explanation": "",
            }

    # Step 4: Rank and pick winner
    ranked = _sort_candidates(surviving)
    winner = ranked[0]

    # Compute the actual amount safe with the spending changes applied
    final_overrides = overrides + spending_overrides_used
    amount_safe = fe.amount_safe_to_pay(user_id, request_date_str, requested_amount, final_overrides)
    edfp_with_changes = fe.earliest_date_for_full_payment(user_id, request_date_str, requested_amount, final_overrides)

    # Determine affordability status
    affordability = _determine_affordability_status(
        winner.method,
        winner.spending_changes,
        amount_safe,
        requested_amount,
        request_date_str,
        winner.first_payment_date,
    )

    # Format payment plan
    plan_str = _plan_to_str(winner.payment_plan)

    # Earliest date for full payment
    # The spec definition: first date d >= request_date where a single full payment of
    # requested_amount is safe. This is what fe.earliest_date_for_full_payment computes.
    # For affordable_now: it's request_date (since we can pay today).
    # For wait and affordable_later: it's the wait date itself.
    # For installments / partial: still the first date a FULL single payment would be safe.
    if affordability == "affordable_now":
        edfp_out = request_date_str
    elif winner.method == "wait":
        edfp_out = winner.first_payment_date
    elif winner.method == "partial_payment":
        # edfp = second payment date (when remainder is paid)
        edfp_out = winner.payment_plan[-1][0] if len(winner.payment_plan) > 1 else (edfp_with_changes or "")
    else:
        # For full_payment and installments: use fe.edfp (first date safe for a single full payment)
        edfp_out = edfp_with_changes or winner.first_payment_date or ""

    return {
        "amount_safe_to_pay": round(amount_safe, 2),
        "affordability_status": affordability,
        "recommended_payment_method": winner.method,
        "payment_plan": plan_str,
        "earliest_date_for_full_payment": edfp_out or "",
        "spending_changes_needed": winner.spending_changes if winner.spending_changes else "none",
        "decision_explanation": "",  # Phase 5 fills this
    }
