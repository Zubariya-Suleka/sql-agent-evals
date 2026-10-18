import datetime as dt
from decimal import Decimal

import pytest

from sql_agent_evals.compare import compare_results, normalize


def match(gold, actual, ordered=False):
    return compare_results(gold, actual, ordered=ordered)


def test_identical_results_match():
    assert match([("SP", 41746), ("RJ", 12852)], [("SP", 41746), ("RJ", 12852)]).match


def test_row_order_matters_only_when_ordered():
    gold, swapped = [("SP", 1), ("RJ", 2)], [("RJ", 2), ("SP", 1)]
    assert match(gold, swapped).match
    result = match(gold, swapped, ordered=True)
    assert not result.match
    assert result.reason == "same rows in a different order"


def test_column_names_and_order_are_ignored():
    result = match([("SP", 41746)], [(41746, "SP")])
    assert result.match
    assert "different order" in result.reason


@pytest.mark.parametrize(
    ("gold", "actual", "same"),
    [
        (4.0864, 4.09, True),  # rounded by the agent: within 1%
        (100, 101.5, False),  # 1.5% off
        (Decimal("58.90"), 58.9, True),
        (625, "625", True),  # a numeric string compares as a number
        (0, 0.0, True),
        (None, None, True),
        (None, 0, False),
        (" SP ", "sp", True),
        ("bed_bath_table", "Bed_Bath_Table", True),
        (dt.datetime(2018, 1, 1), dt.date(2018, 1, 1), True),
        (dt.datetime(2018, 1, 1), "2018-01-01 00:00:00", True),
        (dt.datetime(2018, 1, 1, 10, 30), "2018-01-01T10:30:00", True),
        (dt.datetime(2018, 1, 1, 10, 30), dt.date(2018, 1, 1), False),
    ],
)
def test_value_normalization(gold, actual, same):
    assert match([(gold,)], [(actual,)]).match is same


def test_row_and_column_counts_must_match():
    assert match([(1,), (2,)], [(1,)]).reason == "1 rows, expected 2"
    assert match([(1, 2)], [(1,)]).reason == "1 columns, expected 2"


def test_empty_results_match_each_other():
    assert match([], []).match


def test_duplicates_count():
    assert not match([(1,), (1,), (2,)], [(1,), (2,), (2,)]).match


def test_tolerance_does_not_depend_on_sort_order():
    # 100.4 sorts after 100.3 but the closest pairing is crosswise; greedy matching finds it.
    assert match([(100.0, "a"), (100.4, "b")], [(100.3, "b"), (100.5, "a")]).match


def test_normalize_is_stable_for_stored_gold_values():
    # Gold results are stored as JSON: what goes in must compare equal to the live value.
    live = [dt.datetime(2017, 9, 19, 9, 45, 35), Decimal("13.29"), "sao paulo"]
    stored = ["2017-09-19 09:45:35", 13.29, "sao paulo"]
    assert [normalize(v) for v in live] == [normalize(v) for v in stored]
