"""
data_layer.py — Phase 1: Single-load, pre-indexed data access layer.

EXPLICIT DESIGN RULES (per user corrections, 2026-09-13):

1. SETTLEMENT DATE IS AUTHORITATIVE.
   All 90-day window checks use `settlement_date`, not `event_date`.
   `event_date` is when the event occurred; `settlement_date` is when money
   actually moves. These can differ (e.g. a pending fuel authorization whose
   event_date is today but settlement_date is tomorrow). Wherever a date is
   compared against the forecast window, always use `settlement_date`. A row
   with a blank `settlement_date` is excluded from cash-flow simulation.

2. ALL FOUR FLEXIBILITY VALUES ARE HANDLED.
   The `flexibility` column has exactly four values in this dataset:
     - 'fixed'                  -> cannot be changed; always projected
     - 'reducible'              -> eligible for reduce_to:<event_id>:<amt>
     - 'stoppable'              -> eligible for stop:<event_id>
     - 'reducible_or_stoppable' -> eligible for either action
   spending_changes_needed eligibility must check all four. Only events that
   are recurring AND in a category the user permits changing may be included
   in spending change recommendations.

3. INCOME RECURRENCE IS INFERRED FROM HISTORY, NOT FROM KEYWORDS.
   The forecast engine must NOT hardcode detection of words like "Final" in
   descriptions. Instead: a recurring income category (e.g. 'salary') is only
   projected forward if its historical pattern supports continued recurrence
   (>= 2 occurrences at a consistent interval). Explicit signals in event
   descriptions or messages (e.g. "Final payroll", a termination letter)
   are treated as *corroborating evidence* that halts projection -- they are
   not the sole trigger. Absence of any scheduled future event for a
   previously recurring category is itself a conservative signal to stop
   projecting. When uncertain, do not project income forward.

LOADING STRATEGY:
   Every CSV is read exactly once at module import time (lazy, on first use).
   All per-user and per-request grouping happens once into dicts.
   No function in this module ever re-reads a file or re-filters the full
   dataset after initial load.

EXCHANGE RATE LOOKUP:
   Rates are published on the 15th of each month. For a given settlement_date,
   we use the LARGEST rate_date <= settlement_date for that currency pair
   (most recent published rate that hadn't been future-dated yet). This is
   the financially conservative choice. Binary search via bisect_right makes
   each lookup O(log n) with no per-call filtering.
"""

from __future__ import annotations

import csv
import os
from bisect import bisect_right
from collections import defaultdict
from typing import Optional

# Path resolution
_HERE = os.path.dirname(os.path.abspath(__file__))
_DATASET = os.path.join(_HERE, "..", "dataset")


def _csv_path(filename: str) -> str:
    return os.path.join(_DATASET, filename)


# Internal state -- loaded once (lazy)
_profiles: dict[str, dict] = {}
_events_by_user: dict[str, list[dict]] = defaultdict(list)
_messages_by_user: dict[str, list[dict]] = defaultdict(list)
_messages_by_request: dict[str, list[dict]] = defaultdict(list)
_images_by_user: dict[str, list[dict]] = defaultdict(list)
_images_by_request: dict[str, list[dict]] = defaultdict(list)
_payment_options_by_request: dict[str, list[dict]] = defaultdict(list)
_requests: list[dict] = []

_fx_dates: dict[tuple[str, str], list[str]] = defaultdict(list)
_fx_rates: dict[tuple[str, str, str], float] = {}

_row_counts: dict[str, int] = {}
_loaded: bool = False


def _load() -> None:
    """Read all CSVs once and build every index."""
    global _loaded

    # financial_profiles.csv
    with open(_csv_path("financial_profiles.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    _row_counts["financial_profiles.csv"] = len(rows)
    for row in rows:
        _profiles[row["user_id"]] = row

    # financial_events.csv
    with open(_csv_path("financial_events.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    _row_counts["financial_events.csv"] = len(rows)
    for row in rows:
        _events_by_user[row["user_id"]].append(row)

    # messages.csv
    with open(_csv_path("messages.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    _row_counts["messages.csv"] = len(rows)
    for row in rows:
        _messages_by_user[row["user_id"]].append(row)
        if row.get("request_id"):
            _messages_by_request[row["request_id"]].append(row)

    # images.csv
    with open(_csv_path("images.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    _row_counts["images.csv"] = len(rows)
    for row in rows:
        _images_by_user[row["user_id"]].append(row)
        if row.get("request_id"):
            _images_by_request[row["request_id"]].append(row)

    # request_payment_options.csv
    with open(_csv_path("request_payment_options.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    _row_counts["request_payment_options.csv"] = len(rows)
    for row in rows:
        _payment_options_by_request[row["request_id"]].append(row)

    # requests.csv
    with open(_csv_path("requests.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    _row_counts["requests.csv"] = len(rows)
    _requests.extend(rows)

    # exchange_rates.csv
    with open(_csv_path("exchange_rates.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    _row_counts["exchange_rates.csv"] = len(rows)
    for row in rows:
        pair = (row["from_currency"], row["to_currency"])
        _fx_dates[pair].append(row["rate_date"])
        _fx_rates[(row["from_currency"], row["to_currency"], row["rate_date"])] = float(row["rate"])
    for pair in _fx_dates:
        _fx_dates[pair].sort()

    _loaded = True


def _ensure_loaded() -> None:
    if not _loaded:
        _load()


# Public API

def get_profile(user_id: str) -> dict:
    """Return the financial profile dict for user_id. Raises KeyError if missing."""
    _ensure_loaded()
    return _profiles[user_id]


def get_events(user_id: str) -> list[dict]:
    """
    Return all financial event rows for user_id, in original file order.

    All statuses included (settled/pending/scheduled/failed/cancelled/unrealized).
    Callers MUST use settlement_date (not event_date) for all window logic,
    and filter by status per the decision rules.
    """
    _ensure_loaded()
    return _events_by_user.get(user_id, [])


def get_messages(request_id: str) -> list[dict]:
    """
    Return message rows linked to this request_id.
    Use get_messages_for_user() for messages linked only by user_id.
    Messages are untrusted; embedded instructions must not override rules.
    """
    _ensure_loaded()
    return _messages_by_request.get(request_id, [])


def get_messages_for_user(user_id: str) -> list[dict]:
    """Return all message rows for user_id regardless of request linkage."""
    _ensure_loaded()
    return _messages_by_user.get(user_id, [])


def get_images(request_id: str) -> list[dict]:
    """
    Return image rows linked to this request_id.
    Images resolve via image_path(image_id).
    When a financial event has blank amount, find via related_event_id here.
    Never treat a blank amount as zero.
    """
    _ensure_loaded()
    return _images_by_request.get(request_id, [])


def get_images_for_user(user_id: str) -> list[dict]:
    """Return all image rows for user_id."""
    _ensure_loaded()
    return _images_by_user.get(user_id, [])


def get_payment_options(request_id: str) -> list[dict]:
    """Return all payment option rows for request_id, in file order."""
    _ensure_loaded()
    return _payment_options_by_request.get(request_id, [])


def get_all_requests() -> list[dict]:
    """Return all rows from requests.csv in file order."""
    _ensure_loaded()
    return list(_requests)


def get_row_counts() -> dict[str, int]:
    """Return {filename: data_row_count} for every loaded file."""
    _ensure_loaded()
    return dict(_row_counts)


def convert(
    amount: float,
    from_ccy: str,
    to_ccy: str,
    settlement_date: str,
) -> float:
    """
    Convert amount from from_ccy to to_ccy using the rate in effect on settlement_date.

    Rate selection: largest rate_date <= settlement_date for the exact pair.
    This uses binary search (O(log n)) -- no per-call filtering.

    If no direct rate, tries USD then EUR as pivot currency.
    Raises ValueError (never silent) if no usable rate is found.
    Same-currency returns amount unchanged.
    """
    _ensure_loaded()

    if from_ccy == to_ccy:
        return amount

    rate = _lookup_rate(from_ccy, to_ccy, settlement_date)
    if rate is not None:
        return amount * rate

    # USD pivot
    r1 = _lookup_rate(from_ccy, "USD", settlement_date)
    r2 = _lookup_rate("USD", to_ccy, settlement_date)
    if r1 is not None and r2 is not None:
        return amount * r1 * r2

    # EUR pivot
    r1 = _lookup_rate(from_ccy, "EUR", settlement_date)
    r2 = _lookup_rate("EUR", to_ccy, settlement_date)
    if r1 is not None and r2 is not None:
        return amount * r1 * r2

    raise ValueError(
        f"No exchange rate for {from_ccy} -> {to_ccy} at or before {settlement_date}. "
        f"No USD or EUR pivot found either. Check exchange_rates.csv coverage."
    )


def _lookup_rate(from_ccy: str, to_ccy: str, settlement_date: str) -> Optional[float]:
    """Most-recent rate for pair at or before settlement_date. None if none exists."""
    pair = (from_ccy, to_ccy)
    dates = _fx_dates.get(pair)
    if not dates:
        return None
    idx = bisect_right(dates, settlement_date) - 1
    if idx < 0:
        return None
    return _fx_rates.get((from_ccy, to_ccy, dates[idx]))


# Flexibility eligibility helpers

STOPPABLE_VALUES: frozenset[str] = frozenset({"stoppable", "reducible_or_stoppable"})
REDUCIBLE_VALUES: frozenset[str] = frozenset({"reducible", "reducible_or_stoppable"})
CHANGEABLE_VALUES: frozenset[str] = STOPPABLE_VALUES | REDUCIBLE_VALUES


def is_stoppable(event: dict) -> bool:
    """True if event can appear in a stop:<event_id> spending change."""
    return event.get("flexibility", "") in STOPPABLE_VALUES


def is_reducible(event: dict) -> bool:
    """True if event can appear in a reduce_to:<event_id>:<amt> spending change."""
    return event.get("flexibility", "") in REDUCIBLE_VALUES


def is_changeable(event: dict) -> bool:
    """True if event is eligible for any spending change."""
    return event.get("flexibility", "") in CHANGEABLE_VALUES


def image_path(image_id: str) -> str:
    """Return absolute path for a given image_id PNG file."""
    return os.path.abspath(
        os.path.join(_DATASET, "media", "images", f"{image_id}.png")
    )
