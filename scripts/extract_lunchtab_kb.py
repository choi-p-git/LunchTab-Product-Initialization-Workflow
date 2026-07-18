from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "Lunch Tab Knowledge Base"
OUTPUT_DIR = ROOT / "docs" / "lunchtab-knowledge-base"


def main() -> None:
    if not SOURCE_DIR.is_dir():
        raise SystemExit(f"Knowledge-base PDF folder not found: {SOURCE_DIR}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pages_by_file = []
    for pdf_path in sorted(SOURCE_DIR.glob("*.pdf"), key=lambda path: path.name.casefold()):
        title = _title_from_pdf_name(pdf_path.name)
        text, page_count = _extract_pdf_text(pdf_path)
        output_path = OUTPUT_DIR / f"{_slug(title)}.md"
        output_path.write_text(
            _article_markdown(title, pdf_path.name, page_count, text),
            encoding="utf-8",
        )
        pages_by_file.append((title, pdf_path.name, output_path.name, page_count))
    (OUTPUT_DIR / "README.md").write_text(_index_markdown(pages_by_file), encoding="utf-8")
    print(f"Extracted {len(pages_by_file)} PDF(s) to {OUTPUT_DIR}")


def _extract_pdf_text(path: Path) -> tuple[str, int]:
    reader = PdfReader(str(path))
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        text = _clean_text(page.extract_text() or "")
        if text:
            pages.append(f"## Page {index}\n\n{text}")
    return "\n\n".join(pages).strip(), len(reader.pages)


def _article_markdown(title: str, source_name: str, page_count: int, text: str) -> str:
    extracted_at = datetime.now().isoformat(timespec="seconds")
    body = text or "_No extractable text found. Review the source PDF manually._"
    return (
        f"# {title}\n\n"
        f"- Source PDF: `{source_name}`\n"
        f"- Page count: {page_count}\n"
        f"- Extracted at: {extracted_at}\n\n"
        f"{body}\n"
    )


def _index_markdown(pages_by_file: list[tuple[str, str, str, int]]) -> str:
    extracted_at = datetime.now().isoformat(timespec="seconds")
    lines = [
        "# Lunchtab Knowledge Base Extract",
        "",
        "This folder contains Markdown text extracted from the local ignored PDF folder",
        "`Lunch Tab Knowledge Base/`. Use this extracted text for repository analysis before",
        "consulting broader assumptions about Lunchtab behavior.",
        "",
        f"- Extracted at: {extracted_at}",
        f"- Articles extracted: {len(pages_by_file)}",
        "",
        "## Reference Workflow",
        "",
        "1. Search this folder first with `rg` for Lunchtab product, barcode, category, POS,",
        "   import, and admin behavior.",
        "2. Open the matching Markdown article and cite the source PDF name plus section/page.",
        "3. If extracted text is unclear, manually review the source PDF in",
        "   `Lunch Tab Knowledge Base/`.",
        "4. Refresh this folder after source PDFs change by running:",
        "",
        "```powershell",
        "uv run python scripts\\extract_lunchtab_kb.py",
        "```",
        "",
        "## Articles",
        "",
    ]
    for title, source_name, output_name, page_count in pages_by_file:
        lines.append(f"- [{title}]({output_name}) - `{source_name}`, {page_count} page(s)")
    return "\n".join(lines) + "\n"


def _title_from_pdf_name(name: str) -> str:
    title = name.removesuffix(".pdf").replace(" _ Lunchtab Admin Help Center", "")
    return " ".join(title.split())


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "article"


def _clean_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in value.splitlines()]
    paragraphs = []
    current = []
    for line in lines:
        if not line:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        current.append(line)
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)


if __name__ == "__main__":
    main()
