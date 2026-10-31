"""Synthetic world: US procedures, hospitals, metros, item prices.

Everything here is invented. Hospital names are fictional; prices are plausible-looking chargemaster-style
figures but are *not* real tariffs. The reference price book derived from this catalog is a stand-in for
one built from a payer's historical paid claims. The CPT/ICD-10/MS-DRG codes are real code values used
illustratively (CPT is a registered trademark of the AMA).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# metro -> (state, regional price multiplier)
METROS: dict[str, tuple[str, float]] = {
    "New York": ("NY", 1.32),
    "San Francisco": ("CA", 1.30),
    "Los Angeles": ("CA", 1.22),
    "Boston": ("MA", 1.18),
    "Seattle": ("WA", 1.12),
    "Chicago": ("IL", 1.08),
    "Miami": ("FL", 1.05),
    "Denver": ("CO", 1.05),
    "Houston": ("TX", 1.00),
    "Atlanta": ("GA", 1.00),
    "Dallas": ("TX", 1.00),
    "Phoenix": ("AZ", 0.98),
    "Minneapolis": ("MN", 0.97),
    "Charlotte": ("NC", 0.95),
    "Nashville": ("TN", 0.95),
    "Kansas City": ("MO", 0.88),
    "Omaha": ("NE", 0.85),
    "Boise": ("ID", 0.85),
    "Memphis": ("TN", 0.82),
    "Billings": ("MT", 0.78),
    "Jackson": ("MS", 0.75),
}
CITY_MULTIPLIER: dict[str, float] = {c: m for c, (_, m) in METROS.items()}
CITY_STATE: dict[str, str] = {c: s for c, (s, _) in METROS.items()}
# market tier: 1 = large high-cost metro, 2 = mid-size, 3 = small or rural market
CITY_TIER: dict[str, int] = {
    c: (1 if m >= 1.15 else 2 if m >= 0.9 else 3) for c, m in CITY_MULTIPLIER.items()
}

ROOMS: dict[str, tuple[str, float]] = {
    "room_semi": ("Room and board - Semi-private", 3200),
    "room_private": ("Room and board - Private", 4800),
    "room_stepdown": ("Room and board - Step-down unit", 5600),
    "room_suite": ("Room and board - Suite", 7500),
}
ROOM_LABEL = {
    "room_semi": "Semi-private",
    "room_private": "Private",
    "room_stepdown": "Step-down unit",
    "room_suite": "Suite",
}

# generic per-unit items: key -> (display names, base price in USD, category)
GENERIC_ITEMS: dict[str, tuple[list[str], float, str]] = {
    "icu": (["ICU room and board", "Intensive care unit charges"], 9500, "icu"),
    "nursing": (["Nursing services", "Nursing care charges"], 650, "nursing"),
    "doctor_visit": (
        ["Hospitalist physician visit", "Physician visit - inpatient"],
        380,
        "doctor_fee",
    ),
    "registration": (["Administrative and medical records fee"], 175, "admin"),
    "documentation": (["Medical records processing fee"], 120, "admin"),
    "inj_ceftriaxone": (["Ceftriaxone 1 g injection"], 95, "medicine"),
    "inj_pantoprazole": (["Pantoprazole 40 mg IV injection"], 110, "medicine"),
    "inj_vancomycin": (["Vancomycin 1 g IV infusion"], 210, "medicine"),
    "inj_furosemide": (["Furosemide 40 mg injection"], 85, "medicine"),
    "inj_insulin": (["Insulin regular IV infusion"], 320, "medicine"),
    "iv_fluid": (
        ["IV fluids - normal saline 1000 mL", "IV solution - lactated Ringer's 1000 mL"],
        140,
        "medicine",
    ),
    "tab_acetaminophen": (["Acetaminophen 650 mg tablet"], 12, "medicine"),
    "pharmacy": (
        ["Pharmacy - general medications", "Pharmacy - drugs and solutions"],
        2400,
        "medicine",
    ),
    "cbc": (["Laboratory - CBC with differential"], 165, "diagnostic"),
    "crp": (["Laboratory - C-reactive protein"], 210, "diagnostic"),
    "xray_chest": (["Radiology - Chest X-ray, 2 views"], 520, "diagnostic"),
    "usg_abdomen": (["Radiology - Abdominal ultrasound"], 1450, "diagnostic"),
    "ct_scan": (["Radiology - CT scan with contrast"], 3600, "diagnostic"),
    "ct_head": (["Radiology - CT head without contrast"], 3100, "diagnostic"),
    "mri": (["Radiology - MRI scan"], 4200, "diagnostic"),
    "ecg": (["ECG 12-lead"], 380, "diagnostic"),
    "echo": (["Echocardiogram, complete"], 2900, "diagnostic"),
    "metabolic": (["Laboratory - Basic metabolic panel"], 240, "diagnostic"),
    "hba1c": (["Laboratory - Hemoglobin A1c"], 190, "diagnostic"),
    "troponin": (["Laboratory - Troponin"], 320, "diagnostic"),
    "lactate": (["Laboratory - Lactate"], 260, "diagnostic"),
    "blood_culture": (["Laboratory - Blood culture"], 420, "diagnostic"),
}

# procedure-linked items: key suffix -> (label, share of procedure base cost, category)
PROC_ITEMS: dict[str, tuple[str, float, str]] = {
    "surgeon": ("Surgeon professional fee", 0.22, "surgeon"),
    "anesthesia": ("Anesthesia services", 0.09, "anesthesia"),
    "or": ("Operating room time", 0.20, "operating_room"),
    "consumables": ("Surgical supplies kit", 0.07, "consumable"),
    "implant": ("Implant and prosthesis charges", 0.28, "procedure"),
}
PACKAGE_LABEL = "Global surgical package"
ER_FEE_LABEL = "Emergency department visit, level 4 (facility fee)"


@dataclass(frozen=True)
class Procedure:
    key: str
    diagnosis: str  # text as printed on the bill
    procedure: str  # text as printed on the bill
    code: str  # principal CPT, or MS-DRG for medical stays
    icd: tuple[str, ...]  # ICD-10-CM codes used for this stay (principal first)
    kind: str  # surgical | medical | daycare
    los: tuple[int, int]
    base: float
    emergency_prob: float = 0.0
    accident: bool = False
    liability_prob: float = 0.0  # chance another party's insurance may be primary (accidents)
    implant: bool = False
    icu_prob: float = 0.0
    er_fee: bool = False
    diagnostics: tuple[str, ...] = ("cbc",)
    medicines: tuple[str, ...] = ("pharmacy",)


PROCEDURES: list[Procedure] = [
    Procedure(
        "appendectomy",
        "Acute appendicitis",
        "Laparoscopic appendectomy",
        "44970",
        ("K35.80", "K35.30"),
        "surgical",
        (1, 3),
        38000,
        0.9,
        diagnostics=("cbc", "usg_abdomen", "crp"),
        medicines=("inj_ceftriaxone", "inj_pantoprazole", "iv_fluid"),
    ),
    Procedure(
        "cataract",
        "Age-related cataract",
        "Cataract extraction with intraocular lens",
        "66984",
        ("H25.11", "H25.12"),
        "daycare",
        (0, 1),
        9500,
        implant=True,
        diagnostics=("cbc",),
        medicines=("pharmacy",),
    ),
    Procedure(
        "hernia",
        "Inguinal hernia",
        "Inguinal hernia repair with mesh",
        "49505",
        ("K40.90",),
        "daycare",
        (0, 1),
        16000,
        implant=True,
        diagnostics=("cbc", "metabolic"),
        medicines=("inj_ceftriaxone", "iv_fluid"),
    ),
    Procedure(
        "cholecystectomy",
        "Gallstones",
        "Laparoscopic cholecystectomy",
        "47562",
        ("K80.20", "K80.10"),
        "surgical",
        (0, 2),
        32000,
        0.35,
        diagnostics=("cbc", "usg_abdomen", "metabolic"),
        medicines=("inj_ceftriaxone", "inj_pantoprazole", "iv_fluid"),
    ),
    Procedure(
        "tka",
        "Osteoarthritis of the knee",
        "Total knee arthroplasty",
        "27447",
        ("M17.11", "M17.12"),
        "surgical",
        (1, 3),
        62000,
        implant=True,
        diagnostics=("cbc", "xray_chest", "ecg", "mri"),
        medicines=("inj_ceftriaxone", "inj_pantoprazole", "iv_fluid"),
    ),
    Procedure(
        "tha",
        "Osteoarthritis of the hip",
        "Total hip arthroplasty",
        "27130",
        ("M16.11", "M16.12"),
        "surgical",
        (1, 3),
        60000,
        implant=True,
        diagnostics=("cbc", "xray_chest", "ecg"),
        medicines=("inj_ceftriaxone", "inj_pantoprazole", "iv_fluid"),
    ),
    Procedure(
        "pci",
        "Coronary artery disease",
        "Percutaneous coronary intervention with stent",
        "92928",
        ("I25.10", "I21.4"),
        "surgical",
        (1, 3),
        68000,
        0.5,
        implant=True,
        icu_prob=0.45,
        diagnostics=("cbc", "ecg", "echo", "troponin"),
        medicines=("pharmacy", "iv_fluid"),
    ),
    Procedure(
        "spinal_fusion",
        "Lumbar spinal stenosis",
        "Lumbar arthrodesis (spinal fusion)",
        "22612",
        ("M48.061", "M43.16"),
        "surgical",
        (1, 4),
        95000,
        implant=True,
        diagnostics=("cbc", "mri", "metabolic"),
        medicines=("inj_ceftriaxone", "inj_pantoprazole", "iv_fluid"),
    ),
    Procedure(
        "colonoscopy",
        "Colon polyp",
        "Colonoscopy with biopsy",
        "45380",
        ("K63.5", "K57.30"),
        "daycare",
        (0, 0),
        4800,
        diagnostics=("cbc",),
        medicines=("pharmacy",),
    ),
    Procedure(
        "hysterectomy",
        "Uterine fibroids",
        "Total laparoscopic hysterectomy",
        "58570",
        ("D25.9", "N92.0"),
        "surgical",
        (0, 2),
        41000,
        0.05,
        diagnostics=("cbc", "usg_abdomen", "hba1c"),
        medicines=("inj_ceftriaxone", "iv_fluid"),
    ),
    Procedure(
        "tonsillectomy",
        "Chronic tonsillitis",
        "Tonsillectomy",
        "42826",
        ("J35.01", "J35.3"),
        "daycare",
        (0, 1),
        12500,
        diagnostics=("cbc",),
        medicines=("inj_ceftriaxone", "iv_fluid"),
    ),
    Procedure(
        "cesarean",
        "Pregnancy, cesarean delivery",
        "Cesarean delivery",
        "59510",
        ("O82", "O34.211"),
        "surgical",
        (2, 4),
        24000,
        0.4,
        diagnostics=("cbc", "metabolic"),
        medicines=("pharmacy", "iv_fluid"),
    ),
    Procedure(
        "vaginal_delivery",
        "Pregnancy, vaginal delivery",
        "Vaginal delivery",
        "59400",
        ("O80",),
        "medical",
        (1, 3),
        14000,
        0.6,
        diagnostics=("cbc",),
        medicines=("pharmacy", "iv_fluid"),
    ),
    Procedure(
        "orif_femur",
        "Fracture of femoral shaft",
        "ORIF femur with intramedullary nail",
        "27506",
        ("S72.301A", "S72.302A"),
        "surgical",
        (3, 7),
        72000,
        1.0,
        accident=True,
        liability_prob=0.25,
        implant=True,
        diagnostics=("cbc", "xray_chest", "ct_scan"),
        medicines=("inj_ceftriaxone", "inj_pantoprazole", "iv_fluid"),
    ),
    Procedure(
        "bariatric",
        "Morbid obesity",
        "Laparoscopic sleeve gastrectomy",
        "43775",
        ("E66.01", "Z68.41"),
        "surgical",
        (1, 3),
        38000,
        diagnostics=("cbc", "hba1c", "metabolic"),
        medicines=("inj_ceftriaxone", "inj_pantoprazole", "iv_fluid"),
    ),
    Procedure(
        "rhinoplasty",
        "Cosmetic nasal surgery",
        "Cosmetic rhinoplasty",
        "30400",
        ("Z41.1",),
        "surgical",
        (0, 1),
        15000,
        diagnostics=("cbc",),
        medicines=("pharmacy",),
    ),
    Procedure(
        "er_visit",
        "Chest pain",
        "Emergency department evaluation",
        "99284",
        ("R07.9", "R10.9"),
        "medical",
        (0, 0),
        3800,
        1.0,
        er_fee=True,
        diagnostics=("cbc", "ecg", "troponin", "xray_chest"),
        medicines=("iv_fluid",),
    ),
    Procedure(
        "pneumonia",
        "Community-acquired pneumonia",
        "Medical management of pneumonia",
        "DRG194",
        ("J18.9", "J15.9"),
        "medical",
        (2, 6),
        24000,
        0.85,
        icu_prob=0.15,
        diagnostics=("cbc", "xray_chest", "crp", "ct_scan"),
        medicines=("inj_ceftriaxone", "iv_fluid", "pharmacy"),
    ),
    Procedure(
        "chf",
        "Congestive heart failure",
        "Medical management of heart failure",
        "DRG292",
        ("I50.9", "I50.23"),
        "medical",
        (2, 6),
        28000,
        0.9,
        icu_prob=0.1,
        diagnostics=("cbc", "ecg", "echo", "metabolic"),
        medicines=("inj_furosemide", "iv_fluid", "pharmacy"),
    ),
    Procedure(
        "sepsis",
        "Sepsis",
        "Medical management of sepsis",
        "DRG871",
        ("A41.9",),
        "medical",
        (4, 10),
        52000,
        1.0,
        icu_prob=0.45,
        diagnostics=("cbc", "lactate", "blood_culture", "ct_scan"),
        medicines=("inj_vancomycin", "iv_fluid", "pharmacy"),
    ),
    Procedure(
        "dka",
        "Diabetic ketoacidosis",
        "Medical management of diabetic ketoacidosis",
        "DRG638",
        ("E11.10", "E10.10"),
        "medical",
        (2, 5),
        22000,
        0.9,
        icu_prob=0.35,
        diagnostics=("cbc", "hba1c", "metabolic", "ecg"),
        medicines=("inj_insulin", "iv_fluid", "pharmacy"),
    ),
    Procedure(
        "head_injury",
        "Concussion after motor-vehicle collision",
        "Observation and management of head injury",
        "DRG089",
        ("S06.0X0A", "S06.0X1A"),
        "medical",
        (1, 4),
        34000,
        1.0,
        accident=True,
        liability_prob=0.6,
        icu_prob=0.2,
        diagnostics=("cbc", "ct_head", "xray_chest"),
        medicines=("inj_pantoprazole", "iv_fluid", "pharmacy"),
    ),
]

HOSPITAL_WORDS_A = [
    "Riverside", "Lakeview", "Summit", "Oakwood", "Cedar", "Maple", "Pinecrest", "Harbor",
    "Bayview", "Sunset", "Mountain", "Valley", "Heritage", "Liberty", "Pioneer", "Evergreen",
    "Westside", "Northgate", "Cornerstone", "Meadowbrook",
]  # fmt: skip
HOSPITAL_WORDS_B = [
    "Regional Medical Center",
    "Community Hospital",
    "Memorial Hospital",
    "General Hospital",
    "Health System",
    "University Medical Center",
    "Medical Center",
    "Heart and Surgical Hospital",
]
FIRST_NAMES = [
    "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda", "William",
    "Elizabeth", "David", "Barbara", "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah",
    "Daniel", "Karen", "Carlos", "Aisha", "Wei", "Fatima", "Miguel", "Olivia", "Noah", "Emma",
    "Liam", "Sofia",
]  # fmt: skip
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez",
    "Martinez", "Hernandez", "Lopez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore",
    "Jackson", "Martin", "Lee", "Nguyen", "Patel", "Kim", "Okafor", "Cohen", "Schmidt", "Rossi",
    "Hughes",
]  # fmt: skip
DOCTORS = [
    "Dr. A. Alvarez, MD",
    "Dr. S. Patel, MD",
    "Dr. J. Brooks, MD",
    "Dr. L. Chen, MD",
    "Dr. M. Okafor, MD",
    "Dr. R. Feldman, MD",
]


@dataclass
class Hospital:
    hospital_id: str
    name: str
    city: str
    state: str
    npi: str
    layout: str  # pipe | columns | narrative
    date_fmt: str
    keys: dict[str, str]
    total_label: str
    propensity: (
        float  # latent: how often this hospital's claims get denied (not directly observable)
    )
    price_level: float = 1.0  # latent: pricing tendency vs peers
    extra: dict[str, str] = field(default_factory=dict)
