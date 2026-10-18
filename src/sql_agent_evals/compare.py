"""Execution accuracy: does a query's result equal the gold result?

Rules (from the plan):
- Rows are compared as multisets; order matters only when the gold answer is ordered.
- Column names and aliases are ignored. Column count and values must match; the columns may
  come in a different order.
- Numbers match within 1% relative tolerance (an agent rounding 4.0864 to 4.09 is right).
- Strings are trimmed and lower-cased; numeric strings compare as numbers.
- Dates and timestamps are normalized: a timestamp at midnight equals its date.
"""

import datetime as dt
import itertools
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

REL_TOL = 0.01
# Trying every column order is cheap for the narrow results questions here have.
_MAX_PERMUTED_COLUMNS = 5
# Greedy matching is O(n^2); sorted pairwise comparison handles almost everything first.
_MAX_GREEDY_ROWS = 2000

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?$")
_NUMBER = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")


def _timestamp_text(value: dt.datetime) -> str:
    if value.time() == dt.time(0) and value.tzinfo is None:
        return value.date().isoformat()
    return value.isoformat(sep=" ")


def normalize(value: Any) -> Any:
    """A comparable form: None, bool, float or a canonical string."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int | float | Decimal):
        return float(value)
    if isinstance(value, dt.datetime):
        return _timestamp_text(value)
    if isinstance(value, dt.date):
        return value.isoformat()
    text = str(value).strip()
    if _NUMBER.match(text):
        return float(text)
    if _ISO_DATE.match(text):
        parsed = dt.datetime.fromisoformat(text)
        return _timestamp_text(parsed) if len(text) > 10 else parsed.date().isoformat()
    return text.lower()


def values_equal(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=1e-9)
    return a == b


def _rows_equal(a: tuple, b: tuple) -> bool:
    return all(values_equal(x, y) for x, y in zip(a, b, strict=True))


def _sort_key(row: tuple) -> tuple:
    rank = {type(None): 0, bool: 1, float: 2, str: 3}
    return tuple((rank[type(v)], v if v is not None else 0) for v in row)


def _same_multiset(gold: list[tuple], other: list[tuple]) -> bool:
    if all(map(_rows_equal, sorted(gold, key=_sort_key), sorted(other, key=_sort_key))):
        return True
    if len(gold) > _MAX_GREEDY_ROWS:
        return False
    # Tolerance can reorder near-equal rows in sorting; greedy matching settles it.
    unmatched = list(other)
    for row in gold:
        for i, candidate in enumerate(unmatched):
            if _rows_equal(row, candidate):
                del unmatched[i]
                break
        else:
            return False
    return True


@dataclass(frozen=True)
class Comparison:
    match: bool
    reason: str


def compare_results(
    gold: Sequence[Sequence[Any]], actual: Sequence[Sequence[Any]], *, ordered: bool
) -> Comparison:
    gold_rows = [tuple(map(normalize, row)) for row in gold]
    rows = [tuple(map(normalize, row)) for row in actual]
    if len(rows) != len(gold_rows):
        return Comparison(False, f"{len(rows)} rows, expected {len(gold_rows)}")
    if not gold_rows:
        return Comparison(True, "both empty")
    width = len(gold_rows[0])
    if len(rows[0]) != width:
        return Comparison(False, f"{len(rows[0])} columns, expected {width}")

    identity = tuple(range(width))
    orders = itertools.permutations(identity) if width <= _MAX_PERMUTED_COLUMNS else [identity]
    for order in orders:
        permuted = [tuple(row[i] for i in order) for row in rows]
        same = (
            all(map(_rows_equal, gold_rows, permuted))
            if ordered
            else _same_multiset(gold_rows, permuted)
        )
        if same:
            note = "" if order == identity else " (columns in a different order)"
            return Comparison(True, f"match{note}")

    if ordered and compare_results(gold, actual, ordered=False).match:
        return Comparison(False, "same rows in a different order")
    return Comparison(False, "values differ")
