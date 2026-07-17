from __future__ import annotations

import csv
from pathlib import Path

from lunchtab_product_init.models import LUNCHTAB_TEMPLATE_HEADERS
from lunchtab_product_init.pos_name_workflow import run_pos_name_automation


def write_target_csv(
    path: Path, rows: list[dict[str, str]], headers: list[str] | None = None
) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=headers or list(LUNCHTAB_TEMPLATE_HEADERS))
        writer.writeheader()
        writer.writerows(rows)


def test_run_pos_name_automation_writes_processed_csv_and_audit(tmp_path: Path) -> None:
    source = tmp_path / "ProductData.csv"
    write_target_csv(
        source,
        [
            {
                "Handle": "Assorted Cold Cereals",
                "BaseProductName": "Assorted Cold Cereals",
                "BaseProductPosName": "",
            }
        ],
    )

    result = run_pos_name_automation(source, tmp_path / "out")

    assert result.summary.total_rows == 1
    assert result.summary.ok_rows == 1
    assert result.summary.review_rows == 0
    with result.summary.output_paths.processed_csv.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["BaseProductPosName"] == "AsstColdCereals"
    with result.summary.output_paths.naming_audit.open(encoding="utf-8-sig", newline="") as file:
        audit_rows = list(csv.DictReader(file))
    assert audit_rows[0]["GeneratedBaseProductPosName"] == "AsstColdCereals"
    assert audit_rows[0]["Status"] == "ok"


def test_run_pos_name_automation_rejects_non_target_header(tmp_path: Path) -> None:
    source = tmp_path / "NotProductData.csv"
    write_target_csv(source, [], ["Handle", "BaseProductName"])

    try:
        run_pos_name_automation(source, tmp_path / "out")
    except ValueError as error:
        assert "CSV header does not match" in str(error)
        assert "BaseProductPosName" in str(error)
    else:
        raise AssertionError("run_pos_name_automation should reject an unexpected header")


def test_run_pos_name_automation_flags_duplicate_generated_names(tmp_path: Path) -> None:
    source = tmp_path / "ProductData.csv"
    write_target_csv(
        source,
        [
            {"Handle": "One", "BaseProductName": "Assorted Cold Cereals"},
            {"Handle": "Two", "BaseProductName": "Assorted Cold Cereals"},
        ],
    )

    result = run_pos_name_automation(source, tmp_path / "out")

    assert result.summary.ok_rows == 0
    assert result.summary.review_rows == 2
    assert result.summary.duplicate_pos_names == 1
    with result.summary.output_paths.naming_audit.open(encoding="utf-8-sig", newline="") as file:
        audit_rows = list(csv.DictReader(file))
    assert {row["Status"] for row in audit_rows} == {"review"}
    assert all("duplicate generated POS name" in row["Reason"] for row in audit_rows)


def test_run_pos_name_automation_skips_valid_existing_pos_name(tmp_path: Path) -> None:
    source = tmp_path / "ProductData.csv"
    write_target_csv(
        source,
        [
            {
                "Handle": "Existing",
                "BaseProductName": "Assorted Cold Cereals",
                "BaseProductPosName": "ExistingName",
            }
        ],
    )

    result = run_pos_name_automation(source, tmp_path / "out")

    assert result.summary.ok_rows == 0
    assert result.summary.skipped_rows == 1
    assert result.summary.review_rows == 0
    with result.summary.output_paths.processed_csv.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["BaseProductPosName"] == "ExistingName"
    with result.summary.output_paths.naming_audit.open(encoding="utf-8-sig", newline="") as file:
        audit_rows = list(csv.DictReader(file))
    assert audit_rows[0]["GeneratedBaseProductPosName"] == ""
    assert audit_rows[0]["Status"] == "skipped"
    assert audit_rows[0]["Reason"] == "existing POS name retained"


def test_run_pos_name_automation_regenerates_over_limit_existing_pos_name(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ProductData.csv"
    write_target_csv(
        source,
        [
            {
                "Handle": "Long",
                "BaseProductName": "Assorted Cold Cereals",
                "BaseProductPosName": "WayTooLongExistingName",
            }
        ],
    )

    result = run_pos_name_automation(source, tmp_path / "out")

    assert result.summary.ok_rows == 1
    assert result.summary.skipped_rows == 0
    with result.summary.output_paths.processed_csv.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["BaseProductPosName"] == "AsstColdCereals"


def test_run_pos_name_automation_flags_generated_collision_with_skipped_name(
    tmp_path: Path,
) -> None:
    source = tmp_path / "ProductData.csv"
    write_target_csv(
        source,
        [
            {
                "Handle": "Existing",
                "BaseProductName": "Existing Product",
                "BaseProductPosName": "AsstColdCereals",
            },
            {
                "Handle": "Generated",
                "BaseProductName": "Assorted Cold Cereals",
                "BaseProductPosName": "",
            },
        ],
    )

    result = run_pos_name_automation(source, tmp_path / "out")

    assert result.summary.skipped_rows == 1
    assert result.summary.review_rows == 1
    assert result.summary.duplicate_pos_names == 1
    with result.summary.output_paths.naming_audit.open(encoding="utf-8-sig", newline="") as file:
        audit_rows = list(csv.DictReader(file))
    assert audit_rows[0]["Status"] == "skipped"
    assert audit_rows[1]["Status"] == "review"
    assert "duplicate generated POS name" in audit_rows[1]["Reason"]
