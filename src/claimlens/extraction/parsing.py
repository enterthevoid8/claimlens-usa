"""Tolerant parsers for dates, money and names found in US hospital paperwork."""

from __future__ import annotations

import re
from datetime import date, datetime

_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"],
        start=1,
    )
}

_NUM_DATE = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DAY_FIRST_TEXT = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+([A-Za-z]{3,9})\.?[\s,\-]+(\d{2,4})\b"
)
_MONTH_FIRST_TEXT = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{2,4})\b")


def _year(y: int) -> int:
    return y + 2000 if y < 100 else y


def parse_date(text: str | None) -> date | None:
    """Parse the first date in ``text``. Month-first for numeric dates, as is the US convention
    (falls back to day-first only when the first number cannot be a month)."""
    if not text:
        return None
    m = _ISO_DATE.search(text)
    try:
        if m:
            return date(int(m[1]), int(m[2]), int(m[3]))
        m = _NUM_DATE.search(text)
        if m:
            a, b, y = int(m[1]), int(m[2]), _year(int(m[3]))
            return date(y, a, b) if a <= 12 else date(y, b, a)
        m = _MONTH_FIRST_TEXT.search(text)
        if m and m[1][:3].lower() in _MONTHS:
            return date(_year(int(m[3])), _MONTHS[m[1][:3].lower()], int(m[2]))
        m = _DAY_FIRST_TEXT.search(text)
        if m and m[2][:3].lower() in _MONTHS:
            return date(_year(int(m[3])), _MONTHS[m[2][:3].lower()], int(m[1]))
    except ValueError:
        return None
    return None


_AMOUNT = re.compile(r"(?:usd|us\$|\$)?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.IGNORECASE)


def parse_amount(text: str | None) -> float | None:
    if not text:
        return None
    m = _AMOUNT.search(text.replace("\u00a0", " "))
    if not m:
        return None
    try:
        return round(float(m[1].replace(",", "")), 2)
    except ValueError:
        return None


def normalize_name(name: str | None) -> str:
    if not name:
        return ""
    name = re.sub(
        r"\b(mr|mrs|ms|miss|dr|md|jr|sr|ii|iii|iv|master|baby)\b\.?", "", name, flags=re.IGNORECASE
    )
    return re.sub(r"[^a-z ]", "", name.lower()).strip()


def clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip(" \t:-|")
    return value or None


def iso(d: date | datetime | None) -> str | None:
    return d.isoformat() if d else None
