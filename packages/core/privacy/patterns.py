from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from typing import Any

# Order matters: more specific patterns before generic digit runs.
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b", re.IGNORECASE)
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
AMKA_RE = re.compile(r"\b\d{3}\s?\d{2}\s?\d{2}\s?\d{4}\s?\d\b")
PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)?\d{3,4}[\s.-]?\d{3,4}\b"
)
ADDRESS_RE = re.compile(
    r"\b\d{1,5}\s+\w+(?:\s+\w+){0,4}\s+(?:street|st|avenue|ave|road|rd|odos|λεωφώρου|λεωφ)\b",
    re.IGNORECASE,
)

DETECTOR_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": EMAIL_RE,
    "credit_card": CREDIT_CARD_RE,
    "iban": IBAN_RE,
    "ssn": SSN_RE,
    "amka": AMKA_RE,
    "phone": PHONE_RE,
    "address_heuristic": ADDRESS_RE,
}
