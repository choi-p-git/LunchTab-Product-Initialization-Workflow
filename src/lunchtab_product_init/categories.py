from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from lunchtab_product_init.models import (
    CategoryCatalogEntry,
    CategoryProfile,
    CategoryResult,
    CategoryRule,
    ProductCandidate,
)
from lunchtab_product_init.naming import normalize_text

CATEGORY_PROFILE_SCHEMA_VERSION = 1
HIGH_CONFIDENCE_THRESHOLD = 90


def default_category_profile() -> CategoryProfile:
    catalog = (
        CategoryCatalogEntry("Entrees", "food"),
        CategoryCatalogEntry("Beverages", "food"),
        CategoryCatalogEntry("Snacks", "food"),
        CategoryCatalogEntry("Desserts/Snacks", "food"),
        CategoryCatalogEntry("Breakfast", "food"),
        CategoryCatalogEntry("Salads and Sides", "food"),
        CategoryCatalogEntry("Sandwiches", "food"),
        CategoryCatalogEntry("Soups and Ladles", "food"),
        CategoryCatalogEntry("Transit", "food"),
        CategoryCatalogEntry(
            "Restrictable Packaged",
            "policy",
            "restrictable",
            notes="Packaged items restricted when funds are insufficient.",
        ),
        CategoryCatalogEntry(
            "Exempt Prepared",
            "policy",
            "exempt",
            notes="Plated, trayed, or prepared items exempt from insufficient-funds policy.",
        ),
    )
    rules = (
        CategoryRule("dept-entrees", "source_category", "Entrees", ("Entrees", "Exempt Prepared"), 95, 100),
        CategoryRule("dept-breakfast", "source_category", "Breakfast", ("Breakfast", "Exempt Prepared"), 95, 100),
        CategoryRule(
            "dept-salads-sides",
            "source_category",
            "Salads and Sides",
            ("Salads and Sides", "Exempt Prepared"),
            95,
            100,
        ),
        CategoryRule(
            "dept-sandwiches",
            "source_category",
            "Sandwiches",
            ("Sandwiches", "Exempt Prepared"),
            95,
            100,
        ),
        CategoryRule(
            "dept-soups",
            "source_category",
            "Soups and Ladles",
            ("Soups and Ladles", "Exempt Prepared"),
            95,
            100,
        ),
        CategoryRule("dept-beverages", "source_category", "Beverages", ("Beverages",), 95, 100),
        CategoryRule("dept-transit", "source_category", "Transit", ("Transit",), 95, 100),
        CategoryRule(
            "dept-desserts",
            "source_category",
            "Desserts/Snacks",
            ("Desserts/Snacks", "Exempt Prepared"),
            92,
            100,
        ),
        CategoryRule(
            "dept-snacks",
            "source_category",
            "Snacks",
            ("Snacks", "Restrictable Packaged"),
            92,
            100,
        ),
        CategoryRule("phrase-chips", "phrase", "chips", ("Snacks", "Restrictable Packaged"), 90, 400),
        CategoryRule("phrase-candy", "phrase", "candy", ("Snacks", "Restrictable Packaged"), 90, 400),
        CategoryRule("phrase-cookie", "phrase", "cookie", ("Desserts/Snacks", "Exempt Prepared"), 90, 400),
        CategoryRule("phrase-cookies", "phrase", "cookies", ("Desserts/Snacks", "Exempt Prepared"), 90, 400),
        CategoryRule("phrase-entree", "phrase", "entree", ("Entrees", "Exempt Prepared"), 88, 400),
        CategoryRule("phrase-wrap", "phrase", "wrap", ("Sandwiches", "Exempt Prepared"), 88, 400),
        CategoryRule("phrase-sandwich", "phrase", "sandwich", ("Sandwiches", "Exempt Prepared"), 88, 400),
        CategoryRule("phrase-soup", "phrase", "soup", ("Soups and Ladles", "Exempt Prepared"), 88, 400),
        CategoryRule("phrase-yogurt", "phrase", "yogurt", ("Breakfast", "Exempt Prepared"), 84, 400),
        CategoryRule("phrase-drink", "phrase", "drink", ("Beverages",), 84, 400),
        CategoryRule("phrase-milk", "phrase", "milk", ("Beverages",), 84, 400),
    )
    return CategoryProfile(
        schema_version=CATEGORY_PROFILE_SCHEMA_VERSION,
        name="Current Venue Starter Category Profile",
        catalog=catalog,
        rules=rules,
    )


def load_category_profile(path: Path | None) -> CategoryProfile:
    if path is None:
        return default_category_profile()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return category_profile_from_dict(payload)


def save_category_profile(profile: CategoryProfile, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(category_profile_to_dict(profile), indent=2), encoding="utf-8")


def category_profile_to_dict(profile: CategoryProfile) -> dict[str, object]:
    return {
        "schema_version": profile.schema_version,
        "name": profile.name,
        "catalog": [asdict(entry) for entry in profile.catalog],
        "rules": [
            {
                **asdict(rule),
                "categories": list(rule.categories),
            }
            for rule in profile.rules
        ],
    }


def category_profile_from_dict(payload: dict[str, object]) -> CategoryProfile:
    schema_version = int(payload.get("schema_version", 0))
    if schema_version != CATEGORY_PROFILE_SCHEMA_VERSION:
        raise ValueError(
            "Unsupported category profile schema version: "
            f"{schema_version}; expected {CATEGORY_PROFILE_SCHEMA_VERSION}"
        )
    catalog = tuple(
        CategoryCatalogEntry(
            name=str(entry["name"]).strip(),
            role=entry.get("role", "food"),  # type: ignore[arg-type]
            spending_policy=entry.get("spending_policy", "none"),  # type: ignore[arg-type]
            enabled=bool(entry.get("enabled", True)),
            notes=str(entry.get("notes", "")),
        )
        for entry in payload.get("catalog", [])  # type: ignore[union-attr]
    )
    rules = tuple(
        CategoryRule(
            rule_id=str(rule["rule_id"]).strip(),
            rule_type=rule["rule_type"],  # type: ignore[arg-type]
            pattern=str(rule["pattern"]).strip(),
            categories=tuple(str(category).strip() for category in rule.get("categories", [])),
            confidence=int(rule["confidence"]),
            priority=int(rule["priority"]),
            enabled=bool(rule.get("enabled", True)),
            notes=str(rule.get("notes", "")),
        )
        for rule in payload.get("rules", [])  # type: ignore[union-attr]
    )
    profile = CategoryProfile(
        schema_version=schema_version,
        name=str(payload.get("name", "Category Profile")).strip(),
        catalog=catalog,
        rules=rules,
    )
    validate_category_profile(profile)
    return profile


def validate_category_profile(profile: CategoryProfile) -> None:
    if not profile.catalog:
        raise ValueError("Category profile must define at least one category.")
    names = [entry.name for entry in profile.catalog if entry.enabled]
    if len(names) != len(set(names)):
        raise ValueError("Category profile has duplicate enabled category names.")
    valid = set(names)
    for rule in profile.rules:
        if not rule.enabled:
            continue
        if not rule.rule_id:
            raise ValueError("Category rule is missing rule_id.")
        if not rule.categories:
            raise ValueError(f"Category rule {rule.rule_id} has no target categories.")
        unknown = sorted(set(rule.categories) - valid)
        if unknown:
            raise ValueError(
                f"Category rule {rule.rule_id} references unknown categories: {', '.join(unknown)}"
            )
        if not 0 <= rule.confidence <= 100:
            raise ValueError(f"Category rule {rule.rule_id} has invalid confidence.")


def format_product_categories(categories: tuple[str, ...]) -> str:
    cleaned = []
    seen = set()
    for category in categories:
        value = " ".join(str(category or "").split())
        if value and value not in seen:
            cleaned.append(value)
            seen.add(value)
    return "".join(f"{category};" for category in cleaned)


def infer_categories(candidate: ProductCandidate, profile: CategoryProfile) -> CategoryResult:
    validate_category_profile(profile)
    enabled_categories = {entry.name for entry in profile.catalog if entry.enabled}
    matches: list[tuple[int, int, str, CategoryRule]] = []
    normalized_name = normalize_text(candidate.item_name)
    normalized_source_category = normalize_text(candidate.category)
    barcode = candidate.barcode.strip()

    for rule in profile.rules:
        if not rule.enabled:
            continue
        if not set(rule.categories).issubset(enabled_categories):
            continue
        if _rule_matches(rule, barcode, normalized_name, normalized_source_category):
            matches.append((rule.priority, -rule.confidence, rule.rule_id, rule))

    if not matches:
        return CategoryResult(
            categories=(),
            status="review",
            confidence=0,
            confidence_band="low",
            reason="no category rule matched",
            matched_rules=(),
            source_evidence=_source_evidence(candidate),
        )

    matches.sort()
    priority = matches[0][0]
    selected = [rule for match_priority, _, _, rule in matches if match_priority == priority]
    categories: list[str] = []
    for rule in selected:
        for category in rule.categories:
            if category not in categories:
                categories.append(category)
    confidence = min(rule.confidence for rule in selected)
    band = confidence_band(confidence)
    status = "ok" if band == "high" else "review"
    reason = "" if status == "ok" else "category confidence is not high enough"
    return CategoryResult(
        categories=tuple(categories),
        status=status,
        confidence=confidence,
        confidence_band=band,
        reason=reason,
        matched_rules=tuple(rule.rule_id for rule in selected),
        source_evidence=_source_evidence(candidate),
    )


def confidence_band(confidence: int) -> str:
    if confidence >= HIGH_CONFIDENCE_THRESHOLD:
        return "high"
    if confidence >= 70:
        return "medium"
    return "low"


def _rule_matches(
    rule: CategoryRule,
    barcode: str,
    normalized_name: str,
    normalized_source_category: str,
) -> bool:
    normalized_pattern = normalize_text(rule.pattern)
    if rule.rule_type == "barcode":
        return bool(barcode and rule.pattern.strip() == barcode)
    if rule.rule_type == "item_name":
        return bool(normalized_pattern and normalized_pattern == normalized_name)
    if rule.rule_type == "source_category":
        return bool(normalized_pattern and normalized_pattern == normalized_source_category)
    if rule.rule_type == "phrase":
        return bool(normalized_pattern and normalized_pattern in normalized_name)
    if rule.rule_type == "token":
        return bool(normalized_pattern and normalized_pattern in normalized_name.split())
    raise ValueError(f"Unsupported category rule type: {rule.rule_type}")


def _source_evidence(candidate: ProductCandidate) -> tuple[str, ...]:
    evidence = [
        f"source={candidate.source}",
        f"source_key={candidate.source_key}",
        f"item_name={candidate.item_name}",
    ]
    if candidate.category:
        evidence.append(f"source_category={candidate.category}")
    if candidate.barcode:
        evidence.append(f"barcode={candidate.barcode}")
    return tuple(evidence)
