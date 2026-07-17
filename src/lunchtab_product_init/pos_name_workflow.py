from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from lunchtab_product_init.io import read_csv, write_csv
from lunchtab_product_init.models import LUNCHTAB_TEMPLATE_HEADERS
from lunchtab_product_init.naming import MAX_POS_NAME_LENGTH, duplicate_values, generate_pos_name
from lunchtab_product_init.workflow import NAMING_AUDIT_NAME, default_output_root

POS_NAME_OUTPUT_NAME = "BaseProductPosName Processed.csv"


@dataclass(frozen=True)
class PosNameOutputPaths:
    processed_csv: Path
    naming_audit: Path
    summary: Path


@dataclass(frozen=True)
class PosNameSummary:
    total_rows: int
    ok_rows: int
    skipped_rows: int
    review_rows: int
    duplicate_pos_names: int
    output_paths: PosNameOutputPaths


@dataclass(frozen=True)
class PosNameBuildResult:
    run_dir: Path
    summary: PosNameSummary


def default_pos_name_output_root() -> Path:
    return default_output_root() / "BaseProductPosName Automation"


def validate_target_csv_header(headers: list[str]) -> None:
    expected = list(LUNCHTAB_TEMPLATE_HEADERS)
    if headers == expected:
        return
    missing = [header for header in expected if header not in headers]
    unexpected = [header for header in headers if header not in expected]
    if missing or unexpected:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unexpected:
            details.append("unexpected: " + ", ".join(unexpected))
        raise ValueError(
            "CSV header does not match the expected Lunchtab target header ("
            + "; ".join(details)
            + ")."
        )
    raise ValueError(
        "CSV header contains the expected columns, but the column order does not match."
    )


def run_pos_name_automation(
    input_path: Path, output_root: Path | None = None
) -> PosNameBuildResult:
    headers, rows = read_csv(input_path)
    validate_target_csv_header(headers)

    output_root = output_root or default_pos_name_output_root()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_dir = output_root / timestamp
    paths = PosNameOutputPaths(
        processed_csv=run_dir / POS_NAME_OUTPUT_NAME,
        naming_audit=run_dir / NAMING_AUDIT_NAME,
        summary=run_dir / "run-summary.md",
    )

    output_rows = []
    audit_rows = []
    final_names = []
    generated_results = []
    for row in rows:
        existing_pos_name = row.get("BaseProductPosName", "").strip()
        if existing_pos_name and len(existing_pos_name) <= MAX_POS_NAME_LENGTH:
            generated_results.append(None)
            final_names.append(existing_pos_name)
            continue
        name_result = generate_pos_name(row.get("BaseProductName", ""))
        generated_results.append(name_result)
        final_names.append(name_result.value)

    duplicate_names = duplicate_values(final_names)
    statuses = []
    for index, (row, name_result, final_name) in enumerate(
        zip(rows, generated_results, final_names, strict=True), start=2
    ):
        existing_pos_name = row.get("BaseProductPosName", "").strip()
        status = "skipped" if name_result is None else name_result.status
        reasons = ["existing POS name retained"] if name_result is None else []
        if name_result is not None and name_result.reason:
            reasons.append(name_result.reason)
        if name_result is not None and final_name in duplicate_names:
            status = "review"
            reasons.append("duplicate generated POS name")
        reason = "; ".join(sorted(set(reasons)))
        statuses.append(status)

        output_row = dict(row)
        output_row["BaseProductPosName"] = final_name
        output_rows.append(output_row)
        audit_rows.append(
            {
                "RowNumber": str(index),
                "BaseProductName": row.get("BaseProductName", ""),
                "ExistingBaseProductPosName": existing_pos_name,
                "GeneratedBaseProductPosName": "" if name_result is None else name_result.value,
                "Status": status,
                "Reason": reason,
                "NormalizedName": "" if name_result is None else name_result.normalized,
                "AbbreviationSteps": ""
                if name_result is None
                else " | ".join(name_result.abbreviation_steps),
            }
        )

    write_csv(paths.processed_csv, headers, output_rows)
    write_csv(
        paths.naming_audit,
        [
            "RowNumber",
            "BaseProductName",
            "ExistingBaseProductPosName",
            "GeneratedBaseProductPosName",
            "Status",
            "Reason",
            "NormalizedName",
            "AbbreviationSteps",
        ],
        audit_rows,
    )

    counts = Counter(statuses)
    summary = PosNameSummary(
        total_rows=len(rows),
        ok_rows=counts["ok"],
        skipped_rows=counts["skipped"],
        review_rows=counts["review"],
        duplicate_pos_names=len(duplicate_names),
        output_paths=paths,
    )
    _write_summary(paths.summary, summary, run_dir)
    return PosNameBuildResult(run_dir=run_dir, summary=summary)


def _write_summary(path: Path, summary: PosNameSummary, run_dir: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# BaseProductPosName Automation Summary",
                "",
                f"- Run folder: `{run_dir}`",
                f"- Total rows: {summary.total_rows}",
                f"- Ready rows: {summary.ok_rows}",
                f"- Skipped rows: {summary.skipped_rows}",
                f"- Review rows: {summary.review_rows}",
                f"- Duplicate generated POS names: {summary.duplicate_pos_names}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
