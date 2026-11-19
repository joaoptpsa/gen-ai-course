"""Mask personal data in text that leaves the workbench (span files and trace exports)."""

from __future__ import annotations

import re

# Same patterns as agent/guardrails.py, which masks what the model reads.
PERSONAL_DATA = (
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[email]"),
    (re.compile(r"\bACC-\d{6}\b"), "[account]"),
    (re.compile(r"\+\d{1,3}(?: ?\d{2,4}){2,4}\b|\b\d{3} ?\d{3} ?\d{3}\b"), "[phone]"),
)


def mask_personal_data(text: str) -> str:
    masked = text
    for pattern, replacement in PERSONAL_DATA:
        masked = pattern.sub(replacement, masked)
    return masked
