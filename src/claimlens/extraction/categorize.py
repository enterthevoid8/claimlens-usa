"""Map free-text bill descriptions to coarse categories. Shared by every extractor."""

from __future__ import annotations

import re

from claimlens.domain.models import ItemCategory

_RULES: list[tuple[ItemCategory, tuple[str, ...]]] = [
    (ItemCategory.PACKAGE, ("package", "all inclusive", "all-inclusive", "global surgical")),
    (ItemCategory.ICU, ("icu", "iccu", "nicu", "intensive care", "critical care")),
    (
        ItemCategory.ROOM,
        (
            "room and board",
            "room & board",
            "room charge",
            "private room",
            "semi private",
            "semi-private",
            "step-down",
            "stepdown",
            "telemetry",
            "observation room",
            "suite",
        ),
    ),
    (ItemCategory.NURSING, ("nursing",)),
    (ItemCategory.SURGEON, ("surgeon", "surgical professional")),
    (ItemCategory.ANESTHESIA, ("anesthesia", "anaesthesia", "anesthesiologist")),
    (
        ItemCategory.OR,
        (
            "operating room",
            "or time",
            "or charge",
            "surgical suite",
            "recovery room",
            "pacu",
        ),
    ),
    (
        ItemCategory.DOCTOR_FEE,
        (
            "hospitalist",
            "consultation",
            "physician visit",
            "physician fee",
            "professional fee",
            "specialist",
            "emergency department visit",
            "ed visit",
            "facility fee",
        ),
    ),
    (
        ItemCategory.DIAGNOSTIC,
        (
            "x-ray",
            "xray",
            "radiology",
            "ct",
            "ct scan",
            "mri",
            "ultrasound",
            "laboratory",
            "lab -",
            "blood test",
            "cbc",
            "metabolic panel",
            "pathology",
            "ecg",
            "ekg",
            "echocardiogram",
            "biopsy",
            "culture",
            "troponin",
            "diagnostic",
            "hba1c",
            "lactate",
        ),
    ),
    (
        ItemCategory.PROCEDURE,
        (
            "procedure",
            "endoscopy",
            "colonoscopy",
            "arthroplasty",
            "implant",
            "prosthesis",
            "stent",
            "intraocular lens",
            "hardware",
            "mesh",
        ),
    ),
    (
        ItemCategory.MEDICINE,
        (
            "medicine",
            "tablet",
            "injection",
            "iv fluid",
            "iv solution",
            "intravenous",
            "drug",
            "pharmacy",
            "antibiotic",
            "infusion",
            "insulin",
            "anesthetic agent",
        ),
    ),
    (
        ItemCategory.CONSUMABLE,
        (
            "supply",
            "supplies",
            "consumable",
            "gloves",
            "syringe",
            "catheter",
            "dressing",
            "disposable",
            "surgical kit",
            "suture",
            "kit",
        ),
    ),
    (
        ItemCategory.ADMIN,
        (
            "registration",
            "administrative",
            "medical records",
            "processing fee",
            "service charge",
            "tax",
        ),
    ),
]


def _matches(needle: str, text: str) -> bool:
    n = needle.strip()
    if len(n) <= 4:  # short tokens such as "mri" or "icu" must not match inside other words
        return re.search(rf"(?<![a-z]){re.escape(n)}(?![a-z])", text) is not None
    return needle in text


def categorize(description: str) -> ItemCategory:
    d = description.lower()
    for category, needles in _RULES:
        if any(_matches(n, d) for n in needles):
            return category
    return ItemCategory.OTHER
