from __future__ import annotations

from pathlib import Path

from lunchtab_product_init.pos_name_controller import (
    PosNameAppController,
    PosNameAppPhase,
)


def test_pos_name_controller_ready_after_csv_selected() -> None:
    controller = PosNameAppController()
    state = controller.select_input_csv(Path("ProductData.csv"))
    assert state.phase == PosNameAppPhase.READY
    assert state.can_process


def test_pos_name_controller_requires_csv_before_processing() -> None:
    controller = PosNameAppController()
    try:
        controller.begin_process()
    except RuntimeError as error:
        assert "Select a Lunchtab target CSV" in str(error)
    else:
        raise AssertionError("begin_process should reject missing input")
