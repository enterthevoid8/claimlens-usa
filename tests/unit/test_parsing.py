from datetime import date

import pytest

from claimlens.extraction.parsing import normalize_name, parse_amount, parse_date


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("03/12/2025", date(2025, 3, 12)),
        ("03-12-2025", date(2025, 3, 12)),
        ("Mar 12, 2025", date(2025, 3, 12)),
        ("12 Mar 2025", date(2025, 3, 12)),
        ("2025-03-12", date(2025, 3, 12)),
        ("03/12/25", date(2025, 3, 12)),
        ("13/03/2025", date(2025, 3, 13)),  # impossible as month-first, so read day-first
        ("March 5th, 2024", date(2024, 3, 5)),
        ("DOA: 02/01/2024 10:30", date(2024, 2, 1)),
        ("02/31/2025", None),
        ("not a date", None),
        (None, None),
    ],
)
def test_parse_date_is_month_first(text: str | None, expected: date | None) -> None:
    assert parse_date(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("$12,000.00", 12000.0),
        ("USD 1,500", 1500.0),
        ("US$ 99", 99.0),
        ("$1,234,567.89", 1234567.89),
        ("4000", 4000.0),
        ("abc", None),
        (None, None),
    ],
)
def test_parse_amount_handles_us_formats(text: str | None, expected: float | None) -> None:
    assert parse_amount(text) == expected


def test_normalize_name_strips_titles() -> None:
    assert normalize_name("Mr. Michael Johnson Jr.") == "michael johnson"
    assert normalize_name("DR. A. Banerjee, MD") == "a banerjee"
    assert normalize_name(None) == ""
