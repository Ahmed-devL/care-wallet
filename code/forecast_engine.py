"""
forecast_engine.py — Phase 2: deterministic 90-day cash-flow forecast.

Pure function core: given a user_id and request_date (+ optional evidence
overrides), simulate day-by-day and find the worst point in the 90-day window.
No file I/O, no network calls inside the simulation functions themselves.

DESIGN (see process.md / MASTER-CONTEXT.md for the reasoning):

1. current_available_balance already reflects every settled event with
   settlement_date <= request_date. We NEVER re-apply those. We only need to
   simulate what happens AFTER request_date.

2. Status filtering:
   - settled  -> already in current_available_balance if settlement_date <= request_date.
                 (A settled row with settlement_date > request_date would be unusual;
                 treated as a known future event if it occurs.)
   - scheduled -> confirmed future event, always included as given (e.g. the
                 "Next confirmed salary" row).
   - pending   -> included ONLY if direction == debit (a pending charge will
                 likely settle -> conservative to include). Pending CREDITS are
                 excluded per spec ("ignore pending credits").
   - cancelled, failed, unrealized -> always excluded.

3. Recurring detection: for each (user, category) with >=2 known events
   (settled history + any scheduled/pending future rows) at a fairly
   consistent interval, we treat it as a recurring series. We anchor on the
   LATEST known event in that series (which may already be in the future,
   e.g. a scheduled "next confirmed salary") and project further future
   occurrences at the median interval, using the anchor's amount, until we
   exit the 90-day window.

4. Termination signal: before projecting a series beyond its anchor, we check
   the anchor event's own description (and any linked messages) for explicit
   termination language. This is evidence, not a hardcoded single keyword.
   If found, we stop projecting that series (this is what makes user_05's
   salary correctly stop instead of projecting forever).

5. Evidence overrides (from the extraction layer, Phase 4) can be passed in
   as `overrides`: a list of dicts that amend amounts/dates/cancel a series.
   Phase 2 works with overrides=None (pure structured-data forecast); this
   lets Phase 2 be tested and trusted on its own before the LLM layer exists.
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import Optional

import data_layer as dl

WINDOW_DAYS = 90

TERMINATION_SIGNALS = (
    "final", "last payment", "terminated", "termination", "resigned",
    "resignation", "no longer employed", "severance", "laid off", "layoff",
    "let go", "contract ended", "position eliminated", "redundancy",
)

EXCLUDED_STATUSES = {"cancelled", "failed", "unrealized"}


def _parse(d: str) -> date:
    y, m, dd = d.split("-")
    return date(int(y), int(m), int(dd))


def _fmt(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _is_known_future_or_present(ev: dict, request_date: date) -> bool:
    """True if this row should be taken as-is (not projected) in the sim."""
    status = ev["status"]
    if status in EXCLUDED_STATUSES:
        return False
    sdate = ev.get("settlement_date") or ""
    if not sdate:
        return False
    d = _parse(sdate)
    if status == "settled":
        # Already baked into current_available_balance if <= request_date.
        return d > request_date
    if status == "scheduled":
        return d > request_date
    if status == "pending":
        return d > request_date and ev["direction"] != "credit"
    return False


def _amount_of(ev: dict, home_ccy: str, request_date: date) -> Optional[float]:
    """Returns None (unresolved) if amount is blank -- needs the extraction
    layer to pull it from a linked image. Phase 2 skips these; Phase 4 fills
    them in via `overrides`."""
    if not ev.get("amount"):
        return None
    amt = float(ev["amount"])
    ccy = ev["currency"]
    sdate = ev.get("settlement_date") or _fmt(request_date)
    if ccy == home_ccy:
        return amt
    return dl.convert(amt, ccy, home_ccy, sdate)


def _has_termination_signal(ev: dict, messages: list[dict]) -> bool:
    text = (ev.get("description") or "").lower()
    if any(sig in text for sig in TERMINATION_SIGNALS):
        return True
    for m in messages:
        if m.get("related_event_id") == ev["event_id"]:
            body = (m.get("message_text") or "").lower()
            if any(sig in body for sig in TERMINATION_SIGNALS):
                return True
    return False


def _detect_series(events: list[dict], category: str, request_date: date,
                    home_ccy: str) -> Optional[dict]:
    """
    Look at all non-excluded events in `category`, sorted by settlement_date.
    Returns a series dict {interval_days, anchor_date, anchor_amount,
    direction, sample_event} if a consistent recurring cadence is found,
    else None.
    """
    cat_events = [
        e for e in events
        if e["category"] == category and e["status"] not in EXCLUDED_STATUSES
        and e.get("settlement_date")
    ]
    if len(cat_events) < 2:
        return None
    cat_events.sort(key=lambda e: e["settlement_date"])
    dates = [_parse(e["settlement_date"]) for e in cat_events]
    deltas = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    deltas = [d for d in deltas if d > 0]
    if not deltas:
        return None
    median_delta = statistics.median(deltas)
    if median_delta <= 0:
        return None
    # Consistency check: at least half the deltas within 30% of the median.
    consistent = sum(1 for d in deltas if abs(d - median_delta) <= 0.3 * median_delta)
    if consistent < max(1, len(deltas) // 2):
        return None

    anchor = cat_events[-1]
    anchor_amount = _amount_of(anchor, home_ccy, request_date)
    if anchor_amount is None:
        # Walk back to the most recent event in this series that DOES have a
        # resolvable amount, so an unresolved (image-only) row doesn't kill
        # projection of the whole series.
        for prior in reversed(cat_events[:-1]):
            amt = _amount_of(prior, home_ccy, request_date)
            if amt is not None:
                anchor_amount = amt
                break
        if anchor_amount is None:
            return None  # every occurrence unresolved -- can't detect cadence
    return {
        "interval_days": median_delta,
        "anchor_date": _parse(anchor["settlement_date"]),
        "anchor_amount": anchor_amount,
        "direction": anchor["direction"],
        "anchor_event": anchor,
    }


def build_forecast_deltas(
    user_id: str,
    request_date_str: str,
    overrides: Optional[list[dict]] = None,
) -> list[tuple[str, float, str]]:
    """
    Returns (deltas, unresolved):
      deltas: list of (settlement_date_str, signed_amount_in_home_ccy, source_tag)
        for every event/projection landing in (request_date, request_date+90].
        signed_amount: positive = credit (adds to balance), negative = debit.
      unresolved: list of raw event dicts with a blank `amount` that couldn't
        be resolved (needs Phase 4's image extraction to fill in).

    `overrides` (from the extraction layer) is a list of dicts, each either:
      {"type": "amend_amount", "category": ..., "new_amount": ..., "effective_date": ...}
      {"type": "cancel_series", "category": ...}
      {"type": "one_time", "date": ..., "amount": ..., "direction": "debit"/"credit"}
    Phase 2 ignores this arg (pass None); Phase 4 will populate it.
    """
    overrides = overrides or []
    profile = dl.get_profile(user_id)
    home_ccy = profile["home_currency"]
    events = dl.get_events(user_id)
    messages = dl.get_messages_for_user(user_id)
    request_date = _parse(request_date_str)
    window_end = request_date + timedelta(days=WINDOW_DAYS)

    deltas: list[tuple[str, float, str]] = []

    # 1) Known future/present rows taken as-is (scheduled, pending debits, etc.)
    known_future_by_category: dict[str, list[dict]] = {}
    unresolved: list[dict] = []
    for ev in events:
        if _is_known_future_or_present(ev, request_date):
            d = _parse(ev["settlement_date"])
            if d <= window_end:
                signed = _amount_of(ev, home_ccy, request_date)
                if signed is None:
                    unresolved.append(ev)  # needs Phase 4 image extraction
                else:
                    if ev["direction"] == "debit":
                        signed = -signed
                    deltas.append((ev["settlement_date"], signed, f"known:{ev['event_id']}"))
            known_future_by_category.setdefault(ev["category"], []).append(ev)

    # 2) Recurring series detection + projection, per category.
    categories = sorted(set(e["category"] for e in events))
    for category in categories:
        series = _detect_series(events, category, request_date, home_ccy)
        if series is None:
            continue
        anchor_ev = series["anchor_event"]
        if _has_termination_signal(anchor_ev, messages):
            continue  # e.g. user_05's "Final employer payroll"

        cancelled = any(
            o.get("type") == "cancel_series" and o.get("category") == category
            for o in overrides
        )
        if cancelled:
            continue

        amend = next(
            (o for o in overrides
             if o.get("type") == "amend_amount" and o.get("category") == category),
            None,
        )
        amount = series["anchor_amount"]
        if amend:
            amount = float(amend["new_amount"])

        # Advance from the anchor date to the first occurrence strictly after
        # request_date (anchor itself is already emitted above if it's a
        # known future row; if anchor_date <= request_date, we still need to
        # start projecting from there without re-emitting it).
        interval = timedelta(days=series["interval_days"])
        next_date = series["anchor_date"] + interval
        while next_date <= request_date:
            next_date += interval
        while next_date <= window_end:
            signed = amount if series["direction"] == "credit" else -amount
            deltas.append((_fmt(next_date), signed, f"projected:{category}"))
            next_date += interval

    # 3) One-off evidence-sourced events (Phase 4 overrides only).
    for o in overrides:
        if o.get("type") == "one_time":
            d = _parse(o["date"])
            if request_date < d <= window_end:
                amt = float(o["amount"])
                signed = amt if o["direction"] == "credit" else -amt
                deltas.append((o["date"], signed, "evidence:one_time"))

    return deltas, unresolved


def simulate(
    user_id: str,
    request_date_str: str,
    overrides: Optional[list[dict]] = None,
) -> dict:
    """
    Run the 90-day simulation. Returns:
      {
        "starting_balance": float,
        "min_balance": float,          # worst point over the whole window
        "min_balance_date": str,
        "trajectory": [(date_str, running_balance), ...],  # end-of-day balances
      }
    """
    profile = dl.get_profile(user_id)
    starting_balance = float(profile["current_available_balance"])
    request_date = _parse(request_date_str)

    deltas, unresolved = build_forecast_deltas(user_id, request_date_str, overrides)
    by_date: dict[str, float] = {}
    for d_str, amt, _tag in deltas:
        by_date[d_str] = by_date.get(d_str, 0.0) + amt

    balance = starting_balance
    min_balance = starting_balance
    min_date = request_date_str
    trajectory = [(request_date_str, balance)]

    cur = request_date
    end = request_date + timedelta(days=WINDOW_DAYS)
    while cur < end:
        cur += timedelta(days=1)
        cur_str = _fmt(cur)
        if cur_str in by_date:
            balance += by_date[cur_str]
        trajectory.append((cur_str, balance))
        if balance < min_balance:
            min_balance = balance
            min_date = cur_str

    return {
        "starting_balance": starting_balance,
        "min_balance": min_balance,
        "min_balance_date": min_date,
        "trajectory": trajectory,
        "unresolved_events": unresolved,
    }


def amount_safe_to_pay(
    user_id: str,
    request_date_str: str,
    requested_amount: float,
    overrides: Optional[list[dict]] = None,
) -> float:
    """
    Largest amount payable TODAY (request_date) without the 90-day min balance
    check ever failing, capped at requested_amount, floored at 0.

    Paying X today just shifts the whole trajectory down by X uniformly (since
    it happens on day 0 and every later balance already includes it). So:
      max_payable = min_balance - minimum_balance_to_keep
    """
    profile = dl.get_profile(user_id)
    min_keep = float(profile["minimum_balance_to_keep"])
    sim = simulate(user_id, request_date_str, overrides)
    headroom = sim["min_balance"] - min_keep
    safe = max(0.0, headroom)
    return round(min(safe, float(requested_amount)), 2)


def earliest_date_for_full_payment(
    user_id: str,
    request_date_str: str,
    requested_amount: float,
    overrides: Optional[list[dict]] = None,
) -> Optional[str]:
    """
    First date d >= request_date such that paying requested_amount on d keeps
    the balance >= minimum_balance_to_keep for the rest of the 90-day window
    (measured from d, i.e. d..d+90). We approximate using the ORIGINAL
    request_date's 90-day trajectory: for each candidate day d in the window,
    check whether (balance-at-d-and-after, minus requested_amount) stays
    above minimum_balance_to_keep from d to request_date+90.
    Returns None if no such date exists within the 90-day forecast horizon.
    """
    profile = dl.get_profile(user_id)
    min_keep = float(profile["minimum_balance_to_keep"])
    sim = simulate(user_id, request_date_str, overrides)
    traj = sim["trajectory"]  # (date_str, balance) for day 0..90

    for i, (d_str, _bal) in enumerate(traj):
        # Suffix-min from day i onward, if we pay requested_amount on day i.
        suffix_min = min(b for _, b in traj[i:])
        if suffix_min - requested_amount >= min_keep:
            return d_str
    return None
