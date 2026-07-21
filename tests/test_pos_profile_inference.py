from __future__ import annotations

import csv
from pathlib import Path

from lunchtab_product_init.io import write_csv
from lunchtab_product_init.models import LUNCHTAB_TEMPLATE_HEADERS
from lunchtab_product_init.pos_profile_inference import (
    infer_pos_profile_from_final_import,
    main as infer_main,
)
from lunchtab_product_init.session_workflow import (
    ImportSession,
    PosNamePreferenceProfile,
    learn_pos_preferences,
    load_venue_profile,
    save_venue_profile,
)


def test_infers_pos_profile_from_final_import_csv(tmp_path: Path) -> None:
    final_import = _final_import_csv(
        tmp_path,
        [
            _final_row("Chicken Caesar Salad", "Chick Cae Sal"),
            _final_row("Bacon, Egg, and Cheese Bagel", "BEC Bagel"),
            _final_row("Sausage Egg and Cheese English Muffin", "SEC Muff"),
        ],
    )

    result = infer_pos_profile_from_final_import(final_import, output_root=tmp_path / "out")

    profile = load_venue_profile(result.summary.output_paths.proposed_profile)
    assert profile.pos_preferences.abbreviation_options["chicken"][0].value == "Chick"
    assert profile.pos_preferences.abbreviation_options["caesar"][0].value == "Cae"
    assert profile.pos_preferences.acronym_patterns[0].suffix_tokens == ("egg", "cheese")
    assert result.summary.inferred_rows == 3
    assert result.summary.skipped_rows == 0
    assert result.summary.output_paths.inference_audit.exists()
    assert result.summary.output_paths.proposed_profile_audit.exists()


def test_inference_merges_existing_profile_and_preserves_categories(tmp_path: Path) -> None:
    existing_preferences = learn_pos_preferences(
        PosNamePreferenceProfile(abbreviations={}), "Buffalo Ranch Chicken Sandwich", "Buff Rch Chk"
    )
    existing_profile = tmp_path / "venue-profile.json"
    save_venue_profile(
        ImportSession(
            headers=list(LUNCHTAB_TEMPLATE_HEADERS),
            rows=(),
            category_names=("Breakfast", "Salads"),
            pos_preferences=existing_preferences,
        ),
        existing_profile,
        name="Test Venue",
    )
    final_import = _final_import_csv(
        tmp_path,
        [_final_row("Chicken Caesar Salad", "Chick Cae Sal")],
    )

    result = infer_pos_profile_from_final_import(
        final_import,
        existing_profile_path=existing_profile,
        output_root=tmp_path / "out",
    )

    profile = load_venue_profile(result.summary.output_paths.proposed_profile)
    assert profile.name == "Test Venue - POS Preference Proposal"
    assert profile.category_names == ("Breakfast", "Salads")
    assert profile.pos_preferences.abbreviation_options["buffalo"][0].value == "Buff"
    assert profile.pos_preferences.abbreviation_options["chicken"][0].value == "Chick"
    audit_rows = _read_csv(result.summary.output_paths.inference_audit)
    assert any(row["Action"] == "existing only" for row in audit_rows)
    assert any(row["Action"] == "new inferred rule" for row in audit_rows)


def test_inference_skips_missing_or_invalid_pos_names(tmp_path: Path) -> None:
    final_import = _final_import_csv(
        tmp_path,
        [
            _final_row("Valid Item", "Valid"),
            _final_row("Missing Pos", ""),
            _final_row("Too Long", "This Name Is Too Long"),
        ],
    )

    result = infer_pos_profile_from_final_import(final_import, output_root=tmp_path / "out")

    audit_rows = _read_csv(result.summary.output_paths.inference_audit)
    assert result.summary.inferred_rows == 1
    assert result.summary.skipped_rows == 2
    assert [row["SkipReason"] for row in audit_rows if row["Skipped"] == "true"] == [
        "missing name or POS name",
        "POS name over 15 characters",
    ]


def test_pos_profile_inference_cli_smoke(capsys) -> None:
    assert infer_main(["--smoke-test"]) == 0
    assert "lt-pos-profile-infer smoke ok" in capsys.readouterr().out


def _final_import_csv(tmp_path: Path, rows: list[dict[str, str]]) -> Path:
    path = tmp_path / "Lunchtab Product Import.csv"
    write_csv(path, LUNCHTAB_TEMPLATE_HEADERS, rows)
    return path


def _final_row(name: str, pos_name: str) -> dict[str, str]:
    row = dict.fromkeys(LUNCHTAB_TEMPLATE_HEADERS, "")
    row["BaseProductName"] = name
    row["BaseProductPosName"] = pos_name
    row["Price"] = "1.00"
    row["Barcodes"] = "ABC"
    row["ProductCategories"] = "Test;"
    return row


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))
