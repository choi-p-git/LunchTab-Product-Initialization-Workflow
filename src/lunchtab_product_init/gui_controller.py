from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from lunchtab_product_init.models import BuildInputs
from lunchtab_product_init.session_workflow import FinalReviewMetadata, ImportSession, SessionExportResult
from lunchtab_product_init.workflow import default_output_root

_UNCHANGED = object()


class AppPhase(Enum):
    EMPTY = "empty"
    READY_TO_PARSE = "ready_to_parse"
    PARSING = "parsing"
    CATEGORIZING = "categorizing"
    EDIT_REVIEW = "edit_review"
    POS_REVIEW = "pos_review"
    FINAL_REVIEW = "final_review"
    EXPORTING = "exporting"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass(frozen=True)
class AppState:
    product_template_path: Path | None = None
    recipe_list_path: Path | None = None
    odin_inventory_path: Path | None = None
    generic_inventory_path: Path | None = None
    output_root: Path = default_output_root()
    is_orderable: bool = False
    phase: AppPhase = AppPhase.EMPTY
    session: ImportSession | None = None
    result: SessionExportResult | None = None
    message: str = "Select ProductData template and recipe list to begin."

    @property
    def can_parse(self) -> bool:
        return (
            self.product_template_path is not None
            and self.recipe_list_path is not None
            and self.phase not in {AppPhase.PARSING, AppPhase.EXPORTING}
        )

    @property
    def can_leave_categories(self) -> bool:
        return self.session is not None and all(
            row.category or row.status == "needs_edit" for row in self.session.active_rows
        )

    @property
    def can_leave_edit_review(self) -> bool:
        return self.session is not None and self.session.can_leave_edit_review

    @property
    def can_leave_pos_review(self) -> bool:
        return self.session is not None and self.session.can_leave_pos_review

    @property
    def can_export(self) -> bool:
        return self.session is not None and self.session.can_export


@dataclass(frozen=True)
class CategoryActionSelection:
    row_ids: frozenset[str]
    using_highlighted: bool = False

    @property
    def needs_delete_confirmation(self) -> bool:
        return self.using_highlighted and bool(self.row_ids)


@dataclass(frozen=True)
class UndoEntry:
    session: ImportSession
    label: str


@dataclass(frozen=True)
class SourceFileAudit:
    label: str
    filename: str
    sha256: str

    @property
    def short_sha256(self) -> str:
        return self.sha256[:12]


def undo_button_text(entries: Iterable[UndoEntry]) -> str:
    entries = tuple(entries)
    if not entries:
        return "Undo"
    return f"Undo: {entries[-1].label}"


def source_file_audits(state: AppState) -> tuple[SourceFileAudit, ...]:
    paths = (
        ("Template", state.product_template_path),
        ("Recipe", state.recipe_list_path),
        ("Odin", state.odin_inventory_path),
        ("Generic Inventory", state.generic_inventory_path),
    )
    return tuple(
        SourceFileAudit(label=label, filename=path.name, sha256=_sha256(path))
        for label, path in paths
        if path is not None
    )


def final_review_audit_text(
    metadata: FinalReviewMetadata,
    *,
    is_orderable: bool,
    source_files: Iterable[SourceFileAudit] = (),
) -> str:
    category_counts = ", ".join(
        f"{category}: {count}" for category, count in metadata.category_counts
    ) or "(none)"
    export_status = "ready" if metadata.export_ready else f"{len(metadata.export_errors)} blocker(s)"
    source_text = "; ".join(
        f"{source.label}: {source.filename} ({source.short_sha256})" for source in source_files
    ) or "(none)"
    return (
        f"Rows: parsed {metadata.parsed_rows} | active {metadata.active_rows} | "
        f"deleted {metadata.deleted_rows} | edited {metadata.edited_rows} | "
        f"merged {metadata.merge_rows}\n"
        f"Validation: export {export_status} | duplicate barcodes {metadata.duplicate_barcodes} | "
        f"duplicate POS names {metadata.duplicate_pos_names}\n"
        f"Categories: {category_counts}\n"
        f"POS overrides: {metadata.pos_overrides} | "
        f"IsOrderable: {'true' if is_orderable else 'false'}\n"
        f"Sources: {source_text}"
    )


def select_category_action_rows(
    checked_row_ids: Iterable[str],
    highlighted_row_ids: Iterable[str],
) -> CategoryActionSelection:
    checked = frozenset(str(row_id) for row_id in checked_row_ids if str(row_id))
    if checked:
        return CategoryActionSelection(checked, using_highlighted=False)
    highlighted = frozenset(str(row_id) for row_id in highlighted_row_ids if str(row_id))
    return CategoryActionSelection(highlighted, using_highlighted=bool(highlighted))


def toggle_category_row_selection(selected_row_ids: Iterable[str], row_id: str) -> frozenset[str]:
    selected = set(str(selected_row_id) for selected_row_id in selected_row_ids if str(selected_row_id))
    row_id = str(row_id)
    if not row_id:
        return frozenset(selected)
    if row_id in selected:
        selected.remove(row_id)
    else:
        selected.add(row_id)
    return frozenset(selected)


def select_shown_category_rows(
    selected_row_ids: Iterable[str],
    shown_row_ids: Iterable[str],
) -> frozenset[str]:
    selected = set(str(row_id) for row_id in selected_row_ids if str(row_id))
    selected.update(str(row_id) for row_id in shown_row_ids if str(row_id))
    return frozenset(selected)


def deselect_shown_category_rows(
    selected_row_ids: Iterable[str],
    shown_row_ids: Iterable[str],
) -> frozenset[str]:
    shown = {str(row_id) for row_id in shown_row_ids if str(row_id)}
    return frozenset(str(row_id) for row_id in selected_row_ids if str(row_id) and str(row_id) not in shown)


def next_displayed_pos_row_id(
    previous_row_id: str,
    previous_displayed_row_ids: Iterable[str],
    current_displayed_row_ids: Iterable[str],
) -> str | None:
    displayed = [str(row_id) for row_id in current_displayed_row_ids if str(row_id)]
    if not displayed:
        return None
    previous_displayed = [str(row_id) for row_id in previous_displayed_row_ids if str(row_id)]
    previous_row_id = str(previous_row_id)
    if previous_row_id in displayed:
        start_index = displayed.index(previous_row_id) + 1
        return displayed[start_index] if start_index < len(displayed) else displayed[-1]
    old_index = previous_displayed.index(previous_row_id) if previous_row_id in previous_displayed else -1
    return next(
        (
            row_id
            for row_id in previous_displayed[old_index + 1 :]
            if row_id in displayed
        ),
        displayed[min(max(old_index, 0), len(displayed) - 1)],
    )


class AppController:
    def __init__(self) -> None:
        self.state = AppState()

    def select_product_template(self, path: Path) -> AppState:
        return self._select(product_template_path=path)

    def select_recipe_list(self, path: Path) -> AppState:
        return self._select(recipe_list_path=path)

    def select_odin_inventory(self, path: Path) -> AppState:
        return self._select(odin_inventory_path=path, generic_inventory_path=None)

    def select_generic_inventory(self, path: Path) -> AppState:
        return self._select(odin_inventory_path=None, generic_inventory_path=path)

    def select_output_root(self, path: Path) -> AppState:
        self.state = replace(self.state, output_root=path, result=None)
        return self.state

    def set_is_orderable(self, value: bool) -> AppState:
        self.state = replace(self.state, is_orderable=value, result=None)
        return self.state

    def build_inputs(self) -> BuildInputs:
        if (
            self.state.product_template_path is None
            or self.state.recipe_list_path is None
        ):
            raise RuntimeError("ProductData template and recipe list must be selected before parsing.")
        return BuildInputs(
            product_template_path=self.state.product_template_path,  # type: ignore[arg-type]
            recipe_list_path=self.state.recipe_list_path,  # type: ignore[arg-type]
            output_root=self.state.output_root,
            odin_inventory_path=self.state.odin_inventory_path,
            generic_inventory_path=self.state.generic_inventory_path,
            is_orderable=self.state.is_orderable,
        )

    def begin_parse(self) -> AppState:
        if not self.state.can_parse:
            raise RuntimeError("ProductData template and recipe list must be selected before parsing.")
        self.state = replace(
            self.state,
            phase=AppPhase.PARSING,
            session=None,
            result=None,
            message="Parsing source files and building the working set...",
        )
        return self.state

    def parse_succeeded(self, session: ImportSession) -> AppState:
        self.state = replace(
            self.state,
            phase=AppPhase.CATEGORIZING,
            session=session,
            result=None,
            message="Assign categories, delete unneeded rows, or mark rows for edit review.",
        )
        return self.state

    def set_session(
        self,
        session: ImportSession,
        *,
        phase: AppPhase | None = None,
        message: str | None = None,
    ) -> AppState:
        values = {"session": session, "result": None}
        if phase is not None:
            values["phase"] = phase
        if message is not None:
            values["message"] = message
        self.state = replace(self.state, **values)
        return self.state

    def go_to_edit_review(self) -> AppState:
        self._require_session()
        self.state = replace(
            self.state,
            phase=AppPhase.EDIT_REVIEW,
            message="Review queued rows, complete edits, and delete unneeded rows.",
        )
        return self.state

    def go_to_pos_review(self) -> AppState:
        self._require_session()
        self.state = replace(
            self.state,
            phase=AppPhase.POS_REVIEW,
            message="Review and approve BaseProductPosName values.",
        )
        return self.state

    def go_to_final_review(self) -> AppState:
        self._require_session()
        self.state = replace(
            self.state,
            phase=AppPhase.FINAL_REVIEW,
            message="Review the final upload data and export when ready.",
        )
        return self.state

    def begin_export(self) -> AppState:
        if not self.state.can_export:
            raise RuntimeError("All active rows must be complete before export.")
        self.state = replace(self.state, phase=AppPhase.EXPORTING, message="Writing export files...")
        return self.state

    def export_succeeded(self, result: SessionExportResult) -> AppState:
        self.state = replace(
            self.state,
            phase=AppPhase.COMPLETE,
            result=result,
            message="Product import export complete.",
        )
        return self.state

    def failed(self, message: str) -> AppState:
        self.state = replace(self.state, phase=AppPhase.ERROR, message=message)
        return self.state

    def _select(
        self,
        *,
        product_template_path: Path | None | object = _UNCHANGED,
        recipe_list_path: Path | None | object = _UNCHANGED,
        odin_inventory_path: Path | None | object = _UNCHANGED,
        generic_inventory_path: Path | None | object = _UNCHANGED,
    ) -> AppState:
        product_template = (
            self.state.product_template_path
            if product_template_path is _UNCHANGED
            else product_template_path
        )
        recipe_list = self.state.recipe_list_path if recipe_list_path is _UNCHANGED else recipe_list_path
        odin_inventory = (
            self.state.odin_inventory_path
            if odin_inventory_path is _UNCHANGED
            else odin_inventory_path
        )
        generic_inventory = (
            self.state.generic_inventory_path
            if generic_inventory_path is _UNCHANGED
            else generic_inventory_path
        )
        values = {
            "product_template_path": product_template,
            "recipe_list_path": recipe_list,
            "odin_inventory_path": odin_inventory,
            "generic_inventory_path": generic_inventory,
            "session": None,
            "result": None,
        }
        ready = all(
            values[key] is not None
            for key in ("product_template_path", "recipe_list_path")
        )
        values["phase"] = AppPhase.READY_TO_PARSE if ready else AppPhase.EMPTY
        values["message"] = (
            "Parse sources to begin the guided workflow."
            if ready
            else "Select ProductData template and recipe list to begin."
        )
        self.state = replace(self.state, **values)
        return self.state

    def _require_session(self) -> None:
        if self.state.session is None:
            raise RuntimeError("Parse source files before continuing.")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
