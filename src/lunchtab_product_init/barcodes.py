from __future__ import annotations

from collections import Counter


def parse_barcodes(value: str) -> tuple[str, ...]:
    cleaned = []
    seen = set()
    for barcode in str(value or "").split(","):
        normalized = "".join(barcode.split())
        if normalized and normalized.casefold() not in seen:
            cleaned.append(normalized)
            seen.add(normalized.casefold())
    return tuple(cleaned)


def format_barcodes(values) -> str:
    return ",".join(parse_barcodes(",".join(str(value or "") for value in values)))


def duplicate_barcodes(values) -> set[str]:
    counts = Counter(
        barcode.casefold()
        for value in values
        for barcode in parse_barcodes(value)
    )
    return {barcode for barcode, count in counts.items() if count > 1}
