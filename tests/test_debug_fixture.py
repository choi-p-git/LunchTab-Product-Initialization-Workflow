from __future__ import annotations

import json
import shutil
from pathlib import Path

from lunchtab_product_init.debug_fixture import (
    DEBUG_OUTPUT_DIR,
    DebugFixtureError,
    build_debug_stage,
    build_profile_edit_session,
    default_debug_output_root,
    default_fixture_paths,
    validate_debug_fixture,
)


def test_default_debug_fixture_validates() -> None:
    paths = validate_debug_fixture()

    assert paths.manifest.exists()
    assert paths.final_import.exists()
    assert paths.session_audit.exists()


def test_debug_fixture_validation_rejects_hash_mismatch(tmp_path: Path) -> None:
    source = default_fixture_paths().fixture_dir
    target = tmp_path / "fixture"
    shutil.copytree(source, target)
    paths = default_fixture_paths(target)
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    manifest["files"][0]["sha256"] = "0" * 64
    paths.manifest.write_text(json.dumps(manifest), encoding="utf-8")

    try:
        validate_debug_fixture(paths)
    except DebugFixtureError as error:
        assert "hash mismatch" in str(error)
    else:  # pragma: no cover - assertion clarity
        raise AssertionError("Expected fixture validation to reject hash mismatch.")


def test_debug_stage_presets_build_expected_session_states() -> None:
    step1 = build_debug_stage("step1").session
    step2 = build_debug_stage("step2").session
    step3 = build_debug_stage("step3").session
    step4 = build_debug_stage("step4").session

    assert len(step1.rows) == 1152
    assert all(row.status == "active" for row in step1.rows)
    assert any(row.status == "needs_edit" for row in step2.rows)
    assert any("debug inferred deleted row review" in row.review_reason for row in step2.rows)
    assert step3.can_leave_edit_review
    assert any(row.pos_name for row in step3.active_rows)
    assert step4.can_export
    assert len(step4.active_rows) == 454
    assert len(step4.deleted_rows) == 698


def test_debug_stage_six_exports_under_debug_output(tmp_path: Path) -> None:
    result = build_debug_stage("step6", output_root=tmp_path)

    assert result.result is not None
    assert result.result.run_dir.parent == tmp_path
    assert result.result.summary.output_paths.final_import.exists()
    assert result.session.can_export


def test_profile_edit_session_uses_profile_preferences() -> None:
    session = build_profile_edit_session(row_limit=5)

    assert session.active_rows
    assert session.pos_preferences.abbreviation_options
    assert all(row.pos_name for row in session.active_rows)


def test_default_debug_output_root_is_isolated_from_normal_output() -> None:
    assert default_debug_output_root() == DEBUG_OUTPUT_DIR
    assert default_debug_output_root().name == "debug-output"
