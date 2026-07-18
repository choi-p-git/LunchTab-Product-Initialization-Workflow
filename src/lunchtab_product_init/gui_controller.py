from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from lunchtab_product_init.models import BuildInputs
from lunchtab_product_init.session_workflow import ImportSession, SessionExportResult
from lunchtab_product_init.workflow import default_output_root


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
    output_root: Path = default_output_root()
    is_orderable: bool = False
    phase: AppPhase = AppPhase.EMPTY
    session: ImportSession | None = None
    result: SessionExportResult | None = None
    message: str = "Select the three source files to begin."

    @property
    def can_parse(self) -> bool:
        return (
            self.product_template_path is not None
            and self.recipe_list_path is not None
            and self.odin_inventory_path is not None
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


class AppController:
    def __init__(self) -> None:
        self.state = AppState()

    def select_product_template(self, path: Path) -> AppState:
        return self._select(product_template_path=path)

    def select_recipe_list(self, path: Path) -> AppState:
        return self._select(recipe_list_path=path)

    def select_odin_inventory(self, path: Path) -> AppState:
        return self._select(odin_inventory_path=path)

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
            or self.state.odin_inventory_path is None
        ):
            raise RuntimeError("All three source files must be selected before parsing.")
        return BuildInputs(
            product_template_path=self.state.product_template_path,  # type: ignore[arg-type]
            recipe_list_path=self.state.recipe_list_path,  # type: ignore[arg-type]
            odin_inventory_path=self.state.odin_inventory_path,  # type: ignore[arg-type]
            output_root=self.state.output_root,
            is_orderable=self.state.is_orderable,
        )

    def begin_parse(self) -> AppState:
        if not self.state.can_parse:
            raise RuntimeError("All three source files must be selected before parsing.")
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
        product_template_path: Path | None = None,
        recipe_list_path: Path | None = None,
        odin_inventory_path: Path | None = None,
    ) -> AppState:
        values = {
            "product_template_path": product_template_path or self.state.product_template_path,
            "recipe_list_path": recipe_list_path or self.state.recipe_list_path,
            "odin_inventory_path": odin_inventory_path or self.state.odin_inventory_path,
            "session": None,
            "result": None,
        }
        ready = all(
            values[key] is not None
            for key in ("product_template_path", "recipe_list_path", "odin_inventory_path")
        )
        values["phase"] = AppPhase.READY_TO_PARSE if ready else AppPhase.EMPTY
        values["message"] = (
            "Parse sources to begin the guided workflow."
            if ready
            else "Select the three source files to begin."
        )
        self.state = replace(self.state, **values)
        return self.state

    def _require_session(self) -> None:
        if self.state.session is None:
            raise RuntimeError("Parse source files before continuing.")
