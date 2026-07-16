from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def friendly_error(error: object) -> str:
    return str(error) or type(error).__name__


def open_path(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)
