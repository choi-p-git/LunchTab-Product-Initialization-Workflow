from __future__ import annotations

from lunchtab_product_init.naming import generate_pos_name, normalize_text


def test_normalize_text_removes_punctuation_and_case() -> None:
    assert normalize_text("  Chicken & Cheese!  ") == "chicken cheese"


def test_generate_pos_name_uses_abbreviation_under_limit() -> None:
    result = generate_pos_name("Assorted Cold Cereals")
    assert result.status == "ok"
    assert len(result.value) <= 15
    assert result.value == "AsstColdCereals"


def test_generate_pos_name_flags_duplicate() -> None:
    result = generate_pos_name("Assorted Cold Cereals", {"AsstColdCereals"})
    assert result.status == "review"
