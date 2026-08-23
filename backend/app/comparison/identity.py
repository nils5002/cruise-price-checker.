"""Offer identity check.

Two prices may only be compared when they describe the *same product*.  This
module compares the identity-relevant attributes and reports exactly where two
offers differ -- so the UI can say "Angebote unterscheiden sich" instead of
falsely claiming a price difference.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: field -> (German label, critical?)
IDENTITY_FIELDS: List[Tuple[str, str, bool]] = [
    ("ship", "Schiff", True),
    ("departure_date", "Abfahrtsdatum", True),
    ("return_date", "Rückreisedatum", True),
    ("nights", "Reisedauer (Nächte)", True),
    ("route", "Route", False),
    ("cabin_type", "Kabinentyp", True),
    ("cabin_category", "Kabinenkategorie", True),
    ("tariff", "Tarif", True),
    ("board", "Verpflegung", True),
    ("passenger_count", "Anzahl Passagiere", True),
    ("flight_included", "Flug enthalten", True),
    ("drinks_package", "Getraenkepaket", False),
    ("cancellation_terms", "Stornobedingungen", False),
    ("promo_terms", "Aktionsbedingungen", False),
    ("price_code", "Preiscode", False),
]

_WORD_RE = re.compile(r"[a-z0-9äöüß]+")


def _normalise(value: Any) -> Optional[Any]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    text = " ".join(str(value).split()).strip().lower()
    if not text or text in {"-", "n/a", "unbekannt", "null"}:
        return None
    return text


def _similar_text(left: str, right: str) -> bool:
    """Loose comparison for free-text fields (route, terms)."""
    left_tokens = set(_WORD_RE.findall(left))
    right_tokens = set(_WORD_RE.findall(right))
    if not left_tokens or not right_tokens:
        return left == right
    overlap = len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))
    return overlap >= 0.8


@dataclass
class IdentityDifference:
    field: str
    label: str
    critical: bool
    left: Any
    right: Any

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field": self.field,
            "label": self.label,
            "critical": self.critical,
            "left": self.left,
            "right": self.right,
        }


@dataclass
class IdentityComparison:
    identical: bool
    differences: List[IdentityDifference] = field(default_factory=list)
    not_comparable_fields: List[str] = field(default_factory=list)
    compared_fields: List[str] = field(default_factory=list)

    @property
    def critical_differences(self) -> List[IdentityDifference]:
        return [d for d in self.differences if d.critical]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identical": self.identical,
            "differences": [d.to_dict() for d in self.differences],
            "not_comparable_fields": list(self.not_comparable_fields),
            "compared_fields": list(self.compared_fields),
        }

    def summary(self) -> str:
        if self.identical:
            return "Angebote sind in allen vergleichbaren Merkmalen identisch."
        parts = [f"{d.label}: '{d.left}' vs. '{d.right}'" for d in self.differences]
        return "Angebote unterscheiden sich - " + "; ".join(parts)


def compare_identity(left: Optional[Dict[str, Any]], right: Optional[Dict[str, Any]]) -> IdentityComparison:
    left = left or {}
    right = right or {}
    differences: List[IdentityDifference] = []
    missing: List[str] = []
    compared: List[str] = []

    for name, label, critical in IDENTITY_FIELDS:
        left_value = _normalise(left.get(name))
        right_value = _normalise(right.get(name))
        if left_value is None or right_value is None:
            # Unknown on one side -> not comparable, NOT a difference.
            if left_value != right_value:
                missing.append(name)
            continue
        compared.append(name)
        if isinstance(left_value, str) and isinstance(right_value, str):
            equal = left_value == right_value or (
                name in {"route", "cancellation_terms", "promo_terms", "offer_name"}
                and _similar_text(left_value, right_value)
            )
        else:
            equal = left_value == right_value
        if not equal:
            differences.append(
                IdentityDifference(
                    field=name,
                    label=label,
                    critical=critical,
                    left=left.get(name),
                    right=right.get(name),
                )
            )
    return IdentityComparison(
        identical=not differences,
        differences=differences,
        not_comparable_fields=missing,
        compared_fields=compared,
    )


def group_identical(items: Sequence[Tuple[str, Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Group ``(key, identity_dict)`` pairs into buckets of identical offers."""
    groups: List[Dict[str, Any]] = []
    for key, identity in items:
        placed = False
        for group in groups:
            comparison = compare_identity(group["identity"], identity)
            if comparison.identical:
                group["members"].append(key)
                # Fill blanks so the group description gets more complete.
                for name, value in (identity or {}).items():
                    if group["identity"].get(name) in (None, "") and value not in (None, ""):
                        group["identity"][name] = value
                placed = True
                break
        if not placed:
            groups.append({"id": len(groups) + 1, "identity": dict(identity or {}), "members": [key]})
    return groups


def describe_group_differences(groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Differences of every group relative to the first (largest) group."""
    if len(groups) < 2:
        return []
    reference = groups[0]
    out: List[Dict[str, Any]] = []
    for group in groups[1:]:
        comparison = compare_identity(reference["identity"], group["identity"])
        out.append(
            {
                "group_id": group["id"],
                "members": list(group["members"]),
                "reference_members": list(reference["members"]),
                "differences": [d.to_dict() for d in comparison.differences],
                "summary": comparison.summary(),
            }
        )
    return out
