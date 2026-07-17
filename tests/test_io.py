from __future__ import annotations

from pathlib import Path

from lunchtab_product_init.io import read_csv


def test_read_csv_accepts_windows_1252_exports(tmp_path: Path) -> None:
    path = tmp_path / "ProductData.csv"
    path.write_bytes(b"Handle,BaseProductName\nx,Juice\xae Box\n")

    headers, rows = read_csv(path)

    assert headers == ["Handle", "BaseProductName"]
    assert rows[0]["BaseProductName"] == "Juice\u00ae Box"


def test_read_csv_accepts_utf_16_exports(tmp_path: Path) -> None:
    path = tmp_path / "ProductData.csv"
    path.write_bytes("Handle,BaseProductName\nx,Assorted Cold Cereals\n".encode("utf-16"))

    headers, rows = read_csv(path)

    assert headers == ["Handle", "BaseProductName"]
    assert rows[0]["BaseProductName"] == "Assorted Cold Cereals"


def test_read_csv_accepts_iso_8859_1_exports(tmp_path: Path) -> None:
    path = tmp_path / "ProductData.csv"
    path.write_bytes(b"Handle,BaseProductName\nx,Caf\xe9 Milk\n")

    headers, rows = read_csv(path)

    assert headers == ["Handle", "BaseProductName"]
    assert rows[0]["BaseProductName"] == "Caf\u00e9 Milk"
