"""Neutral evaluation of a scan.

Design rules (deliberately conservative):

* Never claim a vendor "does device pricing".  We report what was measured.
* Only compare prices of offers whose identity matched.
* A single deviation is not called reproducible -- that needs several rounds.
* Missing prices stay missing; nothing is estimated.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from app.comparison.identity import describe_group_differences, group_identical

TOLERANCE = 0.51  # EUR -- rounding noise, not a price difference


def _fmt(amount: Optional[float]) -> str:
    if amount is None:
        return "-"
    return f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def _price_of(result: Any) -> Optional[float]:
    for attribute in ("final_price", "total_price", "cabin_price"):
        value = getattr(result, attribute, None)
        if value is not None:
            return float(value)
    return None


def _identity_of(result: Any) -> Dict[str, Any]:
    identity = getattr(result, "identity", None) or {}
    if not isinstance(identity, dict):
        return {}
    return identity


def build_analysis(results: Iterable[Any], *, rounds_planned: int = 1) -> Dict[str, Any]:
    """Build the full comparison payload for a scan.

    ``results`` are ``ScanResult`` rows (or any object with the same fields).
    """
    results = list(results)
    analysis: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "currency": "EUR",
        "rounds_planned": rounds_planned,
        "rows": [],
        "warnings": [],
        "interpretation": [],
        "cause_hypotheses": [],
    }
    if not results:
        analysis["verdict"] = "insufficient_data"
        analysis["headline"] = "Keine Testergebnisse vorhanden."
        return analysis

    currencies = {r.currency for r in results if getattr(r, "currency", None)}
    if len(currencies) > 1:
        analysis["warnings"].append(
            f"Unterschiedliche Währungen erkannt ({', '.join(sorted(currencies))}) - "
            "Preise sind nicht direkt vergleichbar."
        )
    analysis["currency"] = (sorted(currencies)[0] if currencies else "EUR")

    # --- one row per profile/cookie/referrer/proxy combination ------------
    buckets: Dict[str, Dict[str, Any]] = {}
    for result in results:
        key = "|".join(
            [
                str(result.profile),
                str(result.cookie_mode or ""),
                str(result.referrer or "direct"),
                str(result.proxy_name or "direkt"),
            ]
        )
        bucket = buckets.setdefault(
            key,
            {
                "key": key,
                "profile": result.profile,
                "profile_label": getattr(result, "profile_label", "") or result.profile,
                "device": result.device,
                "browser": result.browser,
                "platform": getattr(result, "platform", None),
                "cookie_mode": result.cookie_mode,
                "cookie_mode_applied": getattr(result, "cookie_mode_applied", None),
                "referrer": result.referrer or "direct",
                "proxy_name": result.proxy_name,
                "session_type": getattr(result, "session_type", "clean"),
                "rounds": {},
                "statuses": [],
                "identity": {},
                "tariff": None,
                "cabin_category": None,
                "screenshot_path": None,
                "result_ids": [],
                "errors": [],
            },
        )
        bucket["rounds"][int(getattr(result, "round", 1) or 1)] = _price_of(result)
        bucket["statuses"].append(result.status)
        bucket["result_ids"].append(getattr(result, "id", None))
        bucket["tariff"] = bucket["tariff"] or result.tariff
        bucket["cabin_category"] = bucket["cabin_category"] or result.cabin_category
        bucket["screenshot_path"] = bucket["screenshot_path"] or result.screenshot_path
        if getattr(result, "error", None):
            bucket["errors"].append(result.error)
        identity = _identity_of(result)
        for name, value in identity.items():
            if bucket["identity"].get(name) in (None, "") and value not in (None, ""):
                bucket["identity"][name] = value

    rows: List[Dict[str, Any]] = []
    for bucket in buckets.values():
        prices = [p for p in bucket["rounds"].values() if p is not None]
        distinct = {round(p, 2) for p in prices}
        row = dict(bucket)
        row["prices_by_round"] = {str(k): v for k, v in sorted(bucket["rounds"].items())}
        row["rounds_with_price"] = len(prices)
        row["price"] = min(prices) if prices else None
        row["price_stable"] = len(distinct) <= 1
        row["status"] = _dominant_status(bucket["statuses"])
        row["error"] = bucket["errors"][0] if bucket["errors"] else None
        row.pop("rounds", None)
        row.pop("statuses", None)
        row.pop("errors", None)
        rows.append(row)

    rows.sort(key=lambda r: (r["price"] is None, r["price"] if r["price"] is not None else 0, r["profile"]))
    analysis["rows"] = rows

    priced = [r for r in rows if r["price"] is not None]
    blocked = [r for r in rows if r["status"] in ("BLOCKED_CAPTCHA", "BOT_PROTECTION")]
    if blocked:
        analysis["warnings"].append(
            f"{len(blocked)} Test(s) wurden von der Website blockiert (CAPTCHA/Bot-Schutz) und "
            "sind nicht in den Vergleich eingegangen."
        )
    no_price = [r for r in rows if r["price"] is None and r["status"] not in ("BLOCKED_CAPTCHA", "BOT_PROTECTION")]
    if no_price:
        analysis["warnings"].append(
            f"Bei {len(no_price)} Test(s) konnte kein Preis zuverlässig ermittelt werden."
        )

    # --- identity grouping ------------------------------------------------
    groups = group_identical([(r["key"], r["identity"]) for r in priced])
    group_by_key = {member: group["id"] for group in groups for member in group["members"]}
    for row in rows:
        row["identity_group"] = group_by_key.get(row["key"])
    analysis["identity_groups"] = [
        {"id": g["id"], "members": g["members"], "identity": g["identity"]} for g in groups
    ]
    analysis["identity_differences"] = describe_group_differences(groups)
    comparable = len(groups) <= 1

    if not priced:
        analysis["verdict"] = "insufficient_data"
        analysis["headline"] = "Preis konnte nicht zuverlässig ermittelt werden."
        analysis["interpretation"].append(
            "Es liegen keine belastbaren Preise vor. Es wird bewusst kein Wert geschaetzt."
        )
        analysis["comparable"] = comparable
        return analysis

    cheapest = min(priced, key=lambda r: r["price"])
    most_expensive = max(priced, key=lambda r: r["price"])
    spread = round(most_expensive["price"] - cheapest["price"], 2)
    spread_pct = round(spread / most_expensive["price"] * 100, 2) if most_expensive["price"] else 0.0

    for row in rows:
        if row["price"] is None:
            row["diff_to_cheapest"] = None
            row["is_cheapest"] = False
            row["is_most_expensive"] = False
            continue
        row["diff_to_cheapest"] = round(row["price"] - cheapest["price"], 2)
        row["is_cheapest"] = abs(row["price"] - cheapest["price"]) <= TOLERANCE
        row["is_most_expensive"] = (
            spread > TOLERANCE and abs(row["price"] - most_expensive["price"]) <= TOLERANCE
        )

    analysis.update(
        {
            "cheapest": {
                "profile": cheapest["profile"],
                "profile_label": cheapest["profile_label"],
                "price": cheapest["price"],
                "device": cheapest["device"],
                "session_type": cheapest["session_type"],
                "cookie_mode": cheapest["cookie_mode"],
            },
            "most_expensive": {
                "profile": most_expensive["profile"],
                "profile_label": most_expensive["profile_label"],
                "price": most_expensive["price"],
                "device": most_expensive["device"],
                "session_type": most_expensive["session_type"],
            },
            "lowest_price": cheapest["price"],
            "highest_price": most_expensive["price"],
            "spread_abs": spread,
            "spread_pct": spread_pct,
            "savings_text": f"{_fmt(spread)} ({str(spread_pct).replace('.', ',')} %)",
            "comparable": comparable,
            "profiles_with_price": len(priced),
        }
    )

    # --- reproducibility --------------------------------------------------
    analysis["reproducibility"] = _reproducibility(rows, spread)

    # --- verdict + neutral wording ---------------------------------------
    if not comparable:
        analysis["verdict"] = "not_comparable"
        analysis["headline"] = "Angebote unterscheiden sich"
        analysis["interpretation"].append(
            "Die Preise können nicht direkt verglichen werden, da unterschiedliche "
            "Tarif-/Angebotsbedingungen erkannt wurden."
        )
        for entry in analysis["identity_differences"]:
            analysis["interpretation"].append(entry["summary"])
    elif spread <= TOLERANCE:
        analysis["verdict"] = "no_difference"
        analysis["headline"] = "Kein Preisunterschied festgestellt"
        analysis["interpretation"].append(
            "Bei diesem Test wurde unter den getesteten Browserprofilen kein "
            "Preisunterschied festgestellt."
        )
    else:
        analysis["verdict"] = "difference"
        analysis["headline"] = f"Preisunterschied von {_fmt(spread)} festgestellt"
        reproducible = analysis["reproducibility"]["status"] == "reproduced"
        if reproducible:
            analysis["interpretation"].append(
                "Bei identischen Reiseparametern wurde zwischen zwei Browser-Sessions ein "
                f"reproduzierbarer Preisunterschied von {_fmt(spread)} festgestellt."
            )
        else:
            analysis["interpretation"].append(
                "Bei identischen Reiseparametern wurde zwischen zwei Browser-Sessions ein "
                f"Preisunterschied von {_fmt(spread)} festgestellt. Eine Wiederholung des "
                "Tests wird empfohlen, um ihn zu bestätigen."
            )
        analysis["interpretation"].append(
            f"Das günstigste Ergebnis wurde mit dem Profil '{cheapest['profile_label']}' "
            f"({cheapest['device']}, Cookies: {cheapest['cookie_mode']}, Session: "
            f"{cheapest['session_type']}) erzielt."
        )
        analysis["cause_hypotheses"] = _cause_hypotheses(rows, cheapest, analysis["reproducibility"])
        analysis["interpretation"].append(
            "Die Ursache ist damit nicht bewiesen. Mögliche Erklärungen werden unter "
            "'Mögliche Ursachen' neutral aufgelistet."
        )

    # Der Reproduzierbarkeits-Hinweis wird separat ausgegeben und deshalb hier
    # nicht zusätzlich in die Interpretation aufgenommen.
    return analysis


def _dominant_status(statuses: List[str]) -> str:
    if not statuses:
        return "ERROR"
    for preferred in ("OK", "PARTIAL"):
        if preferred in statuses:
            return preferred
    return statuses[0]


def _reproducibility(rows: List[Dict[str, Any]], spread: float) -> Dict[str, Any]:
    rounds = max((r["rounds_with_price"] for r in rows), default=0)
    unstable = [r for r in rows if r["rounds_with_price"] > 1 and not r["price_stable"]]
    if rounds <= 1:
        return {
            "rounds": rounds,
            "status": "single",
            "text": (
                "Ergebnis basiert auf einem einzelnen Durchlauf pro Profil. Für eine "
                "belastbare Aussage sind Wiederholungen erforderlich."
                if spread > TOLERANCE
                else ""
            ),
        }
    if unstable:
        return {
            "rounds": rounds,
            "status": "dynamic",
            "unstable_profiles": [r["profile"] for r in unstable],
            "text": "Preis dynamisch / Ergebnis nicht eindeutig.",
        }
    if spread > TOLERANCE:
        return {
            "rounds": rounds,
            "status": "reproduced",
            "text": f"Preisunterschied {rounds}x reproduziert.",
        }
    return {
        "rounds": rounds,
        "status": "reproduced",
        "text": f"Gleiches Ergebnis in {rounds} Durchlaeufen.",
    }


def _cause_hypotheses(
    rows: List[Dict[str, Any]], cheapest: Dict[str, Any], reproducibility: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Explicitly separate the possible explanations -- no premature conclusion."""
    hypotheses: List[Dict[str, Any]] = []
    base_price = cheapest["price"]
    for row in rows:
        if row["price"] is None or abs(row["price"] - base_price) <= TOLERANCE:
            continue
        causes: List[str] = []
        if row["tariff"] and cheapest["profile"] != row["profile"]:
            reference_tariff = next((r["tariff"] for r in rows if r["profile"] == cheapest["profile"]), None)
            if reference_tariff and row["tariff"] != reference_tariff:
                causes.append("anderer Tarif")
        reference_cabin = next((r["cabin_category"] for r in rows if r["profile"] == cheapest["profile"]), None)
        if row["cabin_category"] and reference_cabin and row["cabin_category"] != reference_cabin:
            causes.append("andere Kabinenkategorie")
        if row["session_type"] == "returning":
            causes.append("Session-Effekt (gespeicherte Cookies/Storage)")
        if row["device"] == "mobile" and cheapest["device"] == "desktop":
            causes.append("Device-Effekt (mobiles Profil)")
        if row["cookie_mode"] != cheapest["cookie_mode"]:
            causes.append("andere Cookie-Variante")
        if row["referrer"] != "direct":
            causes.append(f"Einstiegspfad ({row['referrer']})")
        if row["proxy_name"]:
            causes.append(f"andere Ausgangs-IP ({row['proxy_name']})")
        if reproducibility["status"] == "dynamic":
            causes.append("zeitliche/dynamische Preisänderung")
        if not causes:
            causes.append("unbekannte Ursache")
        hypotheses.append(
            {
                "profile": row["profile"],
                "profile_label": row["profile_label"],
                "price": row["price"],
                "diff": row["diff_to_cheapest"],
                "possible_causes": causes,
                "confidence": "Hypothese - nicht bewiesen",
            }
        )
    return hypotheses
