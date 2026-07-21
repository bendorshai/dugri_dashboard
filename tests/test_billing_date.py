"""TDD for the monthly-anniversary billing date helper (dashboard copy).

Anchored, no-drift monthly date math. See billing_date.next_bill_date.
"""

from datetime import date

import pytest

from billing_date import next_bill_date


def test_mid_month_advances_one_month():
    assert next_bill_date(15, date(2026, 1, 15)) == date(2026, 2, 15)


def test_year_rollover():
    assert next_bill_date(10, date(2026, 12, 10)) == date(2027, 1, 10)


def test_anchor_31_clamps_feb_nonleap():
    assert next_bill_date(31, date(2026, 1, 31)) == date(2026, 2, 28)


def test_anchor_31_clamps_feb_leap():
    assert next_bill_date(31, date(2028, 1, 31)) == date(2028, 2, 29)


def test_anchor_31_no_drift_returns_to_31():
    # Feb clamp must NOT pull the anchor earlier: from Feb 28 -> Mar 31.
    assert next_bill_date(31, date(2026, 2, 28)) == date(2026, 3, 31)


def test_anchor_31_april_30day_clamp():
    assert next_bill_date(31, date(2026, 3, 31)) == date(2026, 4, 30)


def test_anchor_29_leap_vs_nonleap():
    assert next_bill_date(29, date(2026, 1, 29)) == date(2026, 2, 28)
    assert next_bill_date(29, date(2028, 1, 29)) == date(2028, 2, 29)


def test_full_year_no_drift():
    anchor, d = 31, date(2026, 1, 31)
    expected = [
        date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30), date(2026, 5, 31),
        date(2026, 6, 30), date(2026, 7, 31), date(2026, 8, 31), date(2026, 9, 30),
        date(2026, 10, 31), date(2026, 11, 30), date(2026, 12, 31), date(2027, 1, 31),
    ]
    got = []
    for _ in range(12):
        d = next_bill_date(anchor, d)
        got.append(d)
    assert got == expected


@pytest.mark.parametrize("bad", [0, 32, -1])
def test_rejects_out_of_range_anchor(bad):
    with pytest.raises(ValueError):
        next_bill_date(bad, date(2026, 1, 15))
