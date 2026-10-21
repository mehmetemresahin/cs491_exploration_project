"""Parsing helpers and the confidence policy shared by all extractors."""

import re

from mock491 import vkn

# Confidence deducted per issue. Anything ending below config.HITL_CONFIDENCE_THRESHOLD
# goes to the review queue, so these numbers decide what a human has to look at.
ISSUE_PENALTY = {
    "vkn_missing": 0.15,  # entity resolution must fall back to fuzzy name matching
    "vkn_checksum": 0.30,  # VKN present but invalid: misread or mistyped
    "currency_assumed": 0.20,
    "date_missing": 0.05,
}

CURRENCY_ALIASES = {"TL": "TRY", "TRY": "TRY", "₺": "TRY", "USD": "USD", "$": "USD",
                    "EUR": "EUR", "€": "EUR"}  # fmt: skip

_TR_NUMBER = re.compile(r"^\d{1,3}(\.\d{3})*(,\d+)?$|^\d+(,\d+)?$")


class ExtractionError(ValueError):
    pass


def confidence(base: float, issues: list[str]) -> float:
    return max(0.0, round(base - sum(ISSUE_PENALTY[i] for i in issues), 2))


def vkn_issues(value: str | None) -> list[str]:
    if not value:
        return ["vkn_missing"]
    return [] if vkn.is_valid(value) else ["vkn_checksum"]


def parse_tr_number(text: str) -> float:
    """'2.829.919,03' -> 2829919.03"""
    text = text.strip()
    if not _TR_NUMBER.match(text):
        raise ExtractionError(f"not a Turkish-formatted number: {text!r}")
    return float(text.replace(".", "").replace(",", "."))


def tr_lower(s: str) -> str:
    return s.replace("İ", "i").replace("I", "ı").lower()


_ASCII = str.maketrans("şğıçöüâîû", "sgicouaiu")


def fold(s: str) -> str:
    """Case- and diacritic-insensitive key: 'TEDARIKCI_UNVANI' == 'Tedarikçi Unvanı'."""
    return squash(tr_lower(s).replace("_", " ")).translate(_ASCII)


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()
