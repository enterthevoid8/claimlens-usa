"""US medical coding reference: code formats, NPI check digit, and a small code-edit table.

The table pairs a principal procedure code (CPT, or an MS-DRG for medical stays) with the ICD-10-CM
diagnosis families that normally support it and a typical length of stay. Real payers publish this kind
of logic as coverage policies (LCD/NCD, commercial medical policies) and claim-scrubber edits; the
entries here are a small, hand-written, *illustrative* stand-in and are not a substitute for a licensed
code set. CPT is a registered trademark of the American Medical Association.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --------------------------------------------------------------------------- formats

_ICD10 = re.compile(r"^[A-TV-Z][0-9][0-9AB](?:\.[0-9A-TV-Z]{1,4})?$")
_CPT = re.compile(r"^(?:\d{5}|\d{4}[FTU])$")
_HCPCS = re.compile(r"^[A-V]\d{4}$")
_DRG = re.compile(r"^DRG\d{3}$")


def normalize_code(code: str | None) -> str | None:
    """Upper-case and strip separators: ' drg 194 ' -> 'DRG194', 's72.301a' -> 'S72.301A'."""
    if not code:
        return None
    c = re.sub(r"[\s\-_]", "", code.strip().upper())
    return c or None


def is_valid_icd10(code: str | None) -> bool:
    c = normalize_code(code)
    return bool(c and _ICD10.match(c))


def is_valid_procedure_code(code: str | None) -> bool:
    c = normalize_code(code)
    return bool(c and (_CPT.match(c) or _HCPCS.match(c) or _DRG.match(c)))


def npi_check_digit(first_nine: str) -> int:
    """Luhn check digit for an NPI (computed over the 80840 prefix + the first nine digits)."""
    digits = [int(ch) for ch in "80840" + first_nine]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:  # these positions are doubled once the (absent) check digit is appended
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10


def make_npi(first_nine: str) -> str:
    return f"{first_nine}{npi_check_digit(first_nine)}"


def is_valid_npi(npi: str | None) -> bool:
    if not npi or not re.fullmatch(r"[12]\d{9}", npi):
        return False
    return npi_check_digit(npi[:9]) == int(npi[9])


# --------------------------------------------------------------------------- code edits


@dataclass(frozen=True)
class CodeEdit:
    code: str
    description: str
    dx_prefixes: tuple[str, ...]  # () means any diagnosis is acceptable
    typical_los: tuple[int, int]  # days, inclusive


CODE_EDITS: dict[str, CodeEdit] = {
    e.code: e
    for e in [
        CodeEdit("44970", "Laparoscopic appendectomy", ("K35", "K36", "K37", "K38"), (0, 3)),
        CodeEdit(
            "66984",
            "Cataract extraction with intraocular lens",
            ("H25", "H26", "H27", "H28"),
            (0, 0),
        ),
        CodeEdit("49505", "Inguinal hernia repair, initial, age 5 or older", ("K40",), (0, 1)),
        CodeEdit("47562", "Laparoscopic cholecystectomy", ("K80", "K81", "K82"), (0, 2)),
        CodeEdit("27447", "Total knee arthroplasty", ("M17", "M12", "M19"), (1, 3)),
        CodeEdit("27130", "Total hip arthroplasty", ("M16", "M19", "M87"), (1, 3)),
        CodeEdit(
            "92928",
            "Percutaneous coronary intervention with stent",
            ("I20", "I21", "I24", "I25"),
            (1, 3),
        ),
        CodeEdit(
            "22612",
            "Posterolateral lumbar arthrodesis, single level",
            ("M43", "M47", "M48", "M51", "M53"),
            (1, 4),
        ),
        CodeEdit(
            "45380",
            "Colonoscopy with biopsy",
            (
                "K50",
                "K51",
                "K52",
                "K57",
                "K58",
                "K59",
                "K62",
                "K63",
                "K92",
                "D12",
                "D37",
                "Z12",
                "R19",
            ),
            (0, 0),
        ),
        CodeEdit(
            "58570",
            "Total laparoscopic hysterectomy",
            ("D25", "D26", "N80", "N83", "N85", "N92", "N93"),
            (0, 2),
        ),
        CodeEdit("42826", "Tonsillectomy, age 12 or older", ("J03", "J35", "J36"), (0, 1)),
        CodeEdit("59510", "Obstetric care including cesarean delivery", ("O",), (2, 4)),
        CodeEdit("59400", "Obstetric care including vaginal delivery", ("O",), (1, 3)),
        CodeEdit("27506", "Open treatment of femoral shaft fracture with nail", ("S72",), (3, 7)),
        CodeEdit("43775", "Laparoscopic sleeve gastrectomy", ("E66", "Z68", "K95"), (1, 3)),
        CodeEdit("30400", "Rhinoplasty, primary", ("J34", "M95", "Z41", "S02"), (0, 1)),
        CodeEdit("99284", "Emergency department visit, moderate-high severity", (), (0, 0)),
        CodeEdit(
            "DRG194",
            "Simple pneumonia and pleurisy with CC",
            ("J12", "J13", "J14", "J15", "J16", "J17", "J18"),
            (2, 6),
        ),
        CodeEdit("DRG292", "Heart failure and shock with CC", ("I11", "I13", "I50"), (2, 6)),
        CodeEdit("DRG871", "Septicemia or severe sepsis with MCC", ("A40", "A41", "R65"), (4, 10)),
        CodeEdit("DRG638", "Diabetes with CC", ("E08", "E09", "E10", "E11", "E13"), (2, 5)),
        CodeEdit("DRG089", "Concussion with CC", ("S06", "S09"), (1, 4)),
    ]
}


def lookup(code: str | None) -> CodeEdit | None:
    c = normalize_code(code)
    return CODE_EDITS.get(c) if c else None


def dx_supports(code: str | None, diagnosis_codes: list[str]) -> bool | None:
    """True/False if the diagnoses support the procedure; None when we have no rule for the code."""
    edit = lookup(code)
    if edit is None:
        return None
    if not edit.dx_prefixes:
        return True
    return any(
        (normalize_code(d) or "").startswith(prefix)
        for d in diagnosis_codes
        for prefix in edit.dx_prefixes
    )
