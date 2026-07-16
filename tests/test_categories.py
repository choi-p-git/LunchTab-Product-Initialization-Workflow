from __future__ import annotations

from pathlib import Path

import pytest

from lunchtab_product_init.categories import (
    category_profile_to_dict,
    default_category_profile,
    format_product_categories,
    infer_categories,
    load_category_profile,
    save_category_profile,
)
from lunchtab_product_init.models import ProductCandidate


def test_format_product_categories_deduplicates_and_adds_semicolons() -> None:
    assert format_product_categories(("Packaged Snacks", "Packaged Snacks")) == "Packaged Snacks;"


def test_default_profile_maps_prepared_department_to_category_with_policy_metadata() -> None:
    result = infer_categories(
        ProductCandidate(
            source="recipe+odin",
            source_key="row-1",
            item_name="Chicken Alfredo",
            price="5.00",
            barcode="ABC",
            category="Entrees",
        ),
        default_category_profile(),
    )
    assert result.status == "ok"
    assert result.confidence_band == "high"
    assert result.categories == ("Entrees",)
    assert result.restriction_policies == ("exempt",)
    assert result.matched_rules == ("dept-entrees",)


def test_default_profile_maps_packaged_phrase_to_category_with_policy_metadata() -> None:
    result = infer_categories(
        ProductCandidate(
            source="recipe",
            source_key="row-2",
            item_name="BBQ Chips",
            price="1.50",
            barcode="DEF",
            category="",
        ),
        default_category_profile(),
    )
    assert result.status == "ok"
    assert result.categories == ("Packaged Snacks",)
    assert result.restriction_policies == ("non_exempt",)


def test_default_profile_routes_snack_department_suggestion_to_review() -> None:
    result = infer_categories(
        ProductCandidate(
            source="recipe+odin",
            source_key="row-4",
            item_name="Assorted Snack",
            price="1.50",
            barcode="JKL",
            category="Snacks",
        ),
        default_category_profile(),
    )
    assert result.status == "review"
    assert result.categories == ("Packaged Snacks",)
    assert result.reason == "category confidence is not high enough"


def test_default_profile_routes_unknown_category_to_review() -> None:
    result = infer_categories(
        ProductCandidate(
            source="recipe",
            source_key="row-3",
            item_name="Mystery Item",
            price="1.00",
            barcode="GHI",
            category="",
        ),
        default_category_profile(),
    )
    assert result.status == "review"
    assert result.reason == "no category rule matched"


def test_category_profile_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    profile = default_category_profile()
    save_category_profile(profile, path)
    loaded = load_category_profile(path)
    assert category_profile_to_dict(loaded) == category_profile_to_dict(profile)


def test_invalid_profile_rejects_unknown_rule_category(tmp_path: Path) -> None:
    profile = category_profile_to_dict(default_category_profile())
    rules = profile["rules"]
    assert isinstance(rules, list)
    rules[0]["categories"] = ["Missing Category"]
    path = tmp_path / "bad-profile.json"
    path.write_text(__import__("json").dumps(profile), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown categories"):
        load_category_profile(path)
