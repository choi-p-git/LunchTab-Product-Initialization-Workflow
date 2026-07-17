from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from lunchtab_product_init.pos_name_workflow import (
    PosNameBuildResult,
    default_pos_name_output_root,
)


class PosNameAppPhase(Enum):
    EMPTY = "empty"
    READY = "ready"
    PROCESSING = "processing"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass(frozen=True)
class PosNameAppState:
    input_csv_path: Path | None = None
    output_root: Path = default_pos_name_output_root()
    phase: PosNameAppPhase = PosNameAppPhase.EMPTY
    result: PosNameBuildResult | None = None
    message: str = "Select a Lunchtab target CSV to begin."

    @property
    def can_process(self) -> bool:
        return self.input_csv_path is not None and self.phase != PosNameAppPhase.PROCESSING


class PosNameAppController:
    def __init__(self) -> None:
        self.state = PosNameAppState()

    def select_input_csv(self, path: Path) -> PosNameAppState:
        self.state = replace(
            self.state,
            input_csv_path=path,
            phase=PosNameAppPhase.READY,
            result=None,
            message="Run BaseProductPosName automation.",
        )
        return self.state

    def select_output_root(self, path: Path) -> PosNameAppState:
        self.state = replace(self.state, output_root=path, result=None)
        return self.state

    def begin_process(self) -> PosNameAppState:
        if not self.state.can_process:
            raise RuntimeError("Select a Lunchtab target CSV before processing.")
        self.state = replace(
            self.state,
            phase=PosNameAppPhase.PROCESSING,
            result=None,
            message="Generating BaseProductPosName values...",
        )
        return self.state

    def process_succeeded(self, result: PosNameBuildResult) -> PosNameAppState:
        self.state = replace(
            self.state,
            phase=PosNameAppPhase.COMPLETE,
            result=result,
            message="BaseProductPosName automation complete.",
        )
        return self.state

    def failed(self, message: str) -> PosNameAppState:
        self.state = replace(self.state, phase=PosNameAppPhase.ERROR, message=message)
        return self.state
