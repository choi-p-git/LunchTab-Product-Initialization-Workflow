from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from lunchtab_product_init.models import BuildResult
from lunchtab_product_init.workflow import default_output_root


class AppPhase(Enum):
    EMPTY = "empty"
    READY = "ready"
    PROCESSING = "processing"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass(frozen=True)
class AppState:
    product_template_path: Path | None = None
    recipe_list_path: Path | None = None
    odin_inventory_path: Path | None = None
    output_root: Path = default_output_root()
    phase: AppPhase = AppPhase.EMPTY
    result: BuildResult | None = None
    message: str = "Select the three source files to begin."

    @property
    def can_build(self) -> bool:
        return (
            self.product_template_path is not None
            and self.recipe_list_path is not None
            and self.odin_inventory_path is not None
            and self.phase != AppPhase.PROCESSING
        )


class AppController:
    def __init__(self) -> None:
        self.state = AppState()

    def select_product_template(self, path: Path) -> AppState:
        return self._change(product_template_path=path)

    def select_recipe_list(self, path: Path) -> AppState:
        return self._change(recipe_list_path=path)

    def select_odin_inventory(self, path: Path) -> AppState:
        return self._change(odin_inventory_path=path)

    def select_output_root(self, path: Path) -> AppState:
        self.state = replace(self.state, output_root=path)
        return self.state

    def begin_build(self) -> AppState:
        if not self.state.can_build:
            raise RuntimeError("All three source files must be selected before building.")
        self.state = replace(
            self.state,
            phase=AppPhase.PROCESSING,
            result=None,
            message="Building product import and audit artifacts...",
        )
        return self.state

    def build_succeeded(self, result: BuildResult) -> AppState:
        self.state = replace(
            self.state,
            phase=AppPhase.COMPLETE,
            result=result,
            message="Product import build complete.",
        )
        return self.state

    def failed(self, message: str) -> AppState:
        self.state = replace(self.state, phase=AppPhase.ERROR, message=message)
        return self.state

    def _change(
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
            "result": None,
        }
        ready = all(
            values[key] is not None
            for key in ("product_template_path", "recipe_list_path", "odin_inventory_path")
        )
        values["phase"] = AppPhase.READY if ready else AppPhase.EMPTY
        values["message"] = "Build the product import." if ready else "Select the three source files to begin."
        self.state = replace(self.state, **values)
        return self.state
