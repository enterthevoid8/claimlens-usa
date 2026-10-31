"""Deterministic, offline extractor.

This is the CI/laptop baseline and the fallback when the LLM extractor is disabled. It understands the
layouts our synthetic generator produces (pipe tables, whitespace columns, "qty x rate" narrative
lines) and a reasonable range of key spellings. It is *not* a general OCR/extraction engine: real
scans go through Azure Document Intelligence + the LLM extractor, and both are scored by the same
evaluation harness (``claimlens eval``).
"""

from __future__ import annotations

import re

from claimlens.domain.models import DischargeSummary, HospitalBill, LineItem
from claimlens.extraction.categorize import categorize
from claimlens.extraction.parsing import clean, parse_amount, parse_date
from claimlens.rules.coding import normalize_code

_KEYS: dict[str, tuple[str, ...]] = {
    "bill_number": (
        "account no",
        "account number",
        "patient account no",
        "patient account number",
        "invoice no",
        "invoice number",
        "bill no",
        "bill number",
    ),
    "patient_name": ("patient name", "name of patient", "patient", "member name"),
    "admission_date": ("date of admission", "admission date", "admit date", "doa", "admitted on"),
    "discharge_date": (
        "date of discharge",
        "discharge date",
        "dod",
        "discharged on",
        "through date",
    ),
    "room_type": ("room type", "room category", "accommodation"),
    "diagnosis": ("final diagnosis", "principal diagnosis", "diagnosis", "provisional diagnosis"),
    "procedure": ("principal procedure", "procedure performed", "procedure", "surgery"),
    "diagnosis_codes": ("diagnosis codes", "dx codes", "icd codes", "icd diagnosis codes"),
    "procedure_code": ("procedure code", "principal procedure code", "cpt code", "cpt", "drg"),
    "npi": ("facility npi", "provider npi", "billing npi", "npi"),
    "city": ("city", "location"),
    "state": ("state",),
    "hospital": ("facility", "facility name", "hospital", "hospital name"),
    "doctor": ("attending physician", "attending", "treating physician", "physician"),
    "mode": ("admission type", "type of admission", "mode of admission"),
    "cause": ("cause", "nature of illness", "mode of injury", "injury type"),
    "liability": (
        "third party liability",
        "third-party liability",
        "other party insurance",
        "liability",
    ),
}

_KV = re.compile(r"^\s*([A-Za-z][A-Za-z .#/()]{1,40}?)\s*[:\-–]\s*(.+?)\s*$")
_SKIP_DESC = re.compile(
    r"^(sr|s\.?no|sl|line|description|particulars|item|total|sub\s*total|grand|net|tax|amount|discount|adjustment|payment|balance|paid|insurance|patient responsibility)\b",
    re.I,
)
_NUM = r"[0-9][0-9,]*(?:\.[0-9]{1,2})?"
_CUR = r"(?:\$|usd|us\$)?"
_PIPE_NUM = re.compile(rf"^{_CUR}\s*({_NUM})$", re.I)
_COLUMNS = re.compile(
    rf"^\s*(?:\d{{1,3}}[.)]?\s+)?(?P<desc>[A-Za-z(].*?)\s{{2,}}(?P<qty>\d+(?:\.\d+)?)\s+(?P<rate>{_NUM})\s+(?P<amt>{_NUM})\s*$"
)
_NARRATIVE = re.compile(
    rf"^\s*(?:\d{{1,3}}[.)]\s+)?(?P<desc>[A-Za-z].*?)\s*\(\s*(?P<qty>\d+(?:\.\d+)?)\s*[x×*]\s*{_CUR}\s*(?P<rate>{_NUM})\s*\)\s*[.\s:\-]*\s*{_CUR}\s*(?P<amt>{_NUM})\s*$",
    re.I,
)
_SIMPLE = re.compile(
    rf"^\s*(?:\d{{1,3}}[.)]\s+)?(?P<desc>[A-Za-z][A-Za-z0-9 ,\-/.&()]+?)\s*[.\s:]{{3,}}\s*{_CUR}\s*(?P<amt>{_NUM})\s*$",
    re.I,
)
_TOTAL = re.compile(
    rf"^\s*(grand\s+total|total\s+charges|total\s+billed(?:\s+charges)?|total\s+amount(?:\s+billed)?|total\s+bill(?:\s+amount)?|bill\s+total|total)\b[^0-9\n]{{0,25}}{_CUR}\s*({_NUM})",
    re.I,
)
_TOTAL_PRIORITY = (
    "grand",
    "total charges",
    "total billed",
    "total amount",
    "total bill",
    "bill total",
    "total",
)


def _key_of(label: str) -> str | None:
    lab = re.sub(r"\s+", " ", label.strip().lower().rstrip(":"))
    for key, variants in _KEYS.items():
        if lab in variants:
            return key
    return None


def _kv_pairs(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if line.count("|") >= 2:
            continue
        m = _KV.match(line)
        if not m:
            continue
        key = _key_of(m[1])
        if key and key not in out:
            out[key] = m[2]
    return out


def _to_float(s: str) -> float:
    return round(float(s.replace(",", "")), 2)


_ROW_START = re.compile(r"^\s*\|?\s*\d{1,3}\s*[.)|]?\s+[A-Za-z]")
_MONEYISH = re.compile(r"[0-9OIl][0-9,OIl]*\.\d{2}")


def _looks_like_row(line: str) -> bool:
    return bool(_ROW_START.match(line) and (line.count("|") >= 4 or _MONEYISH.search(line)))


def parse_line_items(text: str) -> list[LineItem]:
    return parse_line_items_ex(text)[0]


def parse_line_items_ex(text: str) -> tuple[list[LineItem], list[str]]:
    """Items plus the rows that look like items but could not be read (reported, never silently dropped)."""
    items: list[LineItem] = []
    unparsed: list[str] = []
    for line in text.splitlines():
        item = _parse_line(line)
        if item is not None:
            items.append(item)
        elif _looks_like_row(line):
            unparsed.append((clean(line) or line)[:120])
    return items, unparsed


def _parse_line(line: str) -> LineItem | None:
    if "|" in line:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        nums: list[float] = []
        i = len(cells)
        while i > 0 and _PIPE_NUM.match(cells[i - 1] or "x"):
            i -= 1
            cell = _PIPE_NUM.match(cells[i])
            if cell is None:  # pragma: no cover - guarded by the loop condition
                break
            nums.insert(0, _to_float(cell[1]))
        desc_cells = [c for c in cells[:i] if c and not c.isdigit()]
        if len(nums) >= 3 and desc_cells:
            qty, rate, amt = nums[-3], nums[-2], nums[-1]
            desc = clean(desc_cells[-1])
            if desc and not _SKIP_DESC.match(desc):
                return LineItem(
                    description=desc,
                    category=categorize(desc),
                    quantity=qty,
                    unit_price=rate,
                    amount=amt,
                )
        if len(nums) == 1 and desc_cells:
            desc = clean(desc_cells[-1])
            if desc and not _SKIP_DESC.match(desc):
                return LineItem(
                    description=desc,
                    category=categorize(desc),
                    quantity=1.0,
                    unit_price=nums[0],
                    amount=nums[0],
                )
        return None
    for pattern in (_NARRATIVE, _COLUMNS):
        m = pattern.match(line)
        if m:
            desc = clean(m["desc"])
            if desc and not _SKIP_DESC.match(desc):
                return LineItem(
                    description=desc,
                    category=categorize(desc),
                    quantity=float(m["qty"]),
                    unit_price=_to_float(m["rate"]),
                    amount=_to_float(m["amt"]),
                )
            return None
    m = _SIMPLE.match(line)
    if m:
        desc = clean(m["desc"])
        if desc and not _SKIP_DESC.match(desc):
            amt = _to_float(m["amt"])
            return LineItem(
                description=desc,
                category=categorize(desc),
                quantity=1.0,
                unit_price=amt,
                amount=amt,
            )
    return None


def parse_total(text: str) -> float | None:
    found: dict[str, float] = {}
    for line in text.splitlines():
        if "sub" in line.lower()[:12]:
            continue
        m = _TOTAL.match(line)
        if m:
            label = re.sub(r"\s+", " ", m[1].lower())
            for p in _TOTAL_PRIORITY:
                if label.startswith(p):
                    found[p] = _to_float(m[2])
                    break
    for p in _TOTAL_PRIORITY:
        if p in found:
            return found[p]
    return None


_CODE_SPLIT = re.compile(r"[,;/\s]+")


def parse_code_list(value: str | None) -> list[str]:
    """Split a list of diagnosis codes; keeps unreadable tokens so the format rule can flag them."""
    if not value:
        return []
    return [t.upper() for t in _CODE_SPLIT.split(value) if t]


def parse_tri_state(value: str | None) -> bool | None:
    if not value:
        return None
    v = value.strip().lower()
    if v.startswith(("y", "true", "possible", "pending")):
        return True
    if v.startswith(("n", "false", "none")):
        return False
    return None


class RuleBasedExtractor:
    name = "rule_based"

    def extract_bill(self, text: str) -> HospitalBill:
        kv = _kv_pairs(text)
        first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        hospital = clean(kv.get("hospital")) or (
            first_line
            if first_line and not re.search(r"bill|invoice|statement|\d", first_line, re.I)
            else None
        )
        items, unparsed = parse_line_items_ex(text)
        npi = clean(kv.get("npi"))
        return HospitalBill(
            bill_number=clean(kv.get("bill_number")),
            hospital_name=hospital,
            provider_npi=re.sub(r"[\s\-]", "", npi) if npi else None,
            city=clean(kv.get("city")),
            state=(clean(kv.get("state")) or "").upper() or None,
            patient_name=clean(kv.get("patient_name")),
            admission_date=parse_date(kv.get("admission_date")),
            discharge_date=parse_date(kv.get("discharge_date")),
            diagnosis=clean(kv.get("diagnosis")),
            procedure=clean(kv.get("procedure")),
            diagnosis_codes=parse_code_list(kv.get("diagnosis_codes")),
            procedure_code=normalize_code(clean(kv.get("procedure_code"))),
            room_type=clean(kv.get("room_type")),
            line_items=items,
            unparsed_rows=unparsed,
            total_claimed=parse_total(text),
        )

    def extract_discharge(self, text: str) -> DischargeSummary:
        kv = _kv_pairs(text)
        mode = (kv.get("mode") or "").lower()
        cause = (kv.get("cause") or "").lower()
        return DischargeSummary(
            patient_name=clean(kv.get("patient_name")),
            diagnosis=clean(kv.get("diagnosis")),
            procedure=clean(kv.get("procedure")),
            admission_date=parse_date(kv.get("admission_date")),
            discharge_date=parse_date(kv.get("discharge_date")),
            diagnosis_codes=parse_code_list(kv.get("diagnosis_codes")),
            is_emergency=("emergency" in mode or "urgent" in mode) if mode else None,
            is_accident=(
                "accident" in cause
                or "injury" in cause
                or "trauma" in cause
                or "collision" in cause
            )
            if cause
            else None,
            third_party_liability=parse_tri_state(kv.get("liability")),
            treating_doctor=clean(kv.get("doctor")),
        )


def parse_amount_text(text: str) -> float | None:  # re-exported for tests
    return parse_amount(text)
