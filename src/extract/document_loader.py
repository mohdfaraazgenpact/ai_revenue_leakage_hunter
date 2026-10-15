"""Load contracts into page-tagged text, segment clauses, and verify citation quotes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

CLAUSE_START = re.compile(r"(?m)^(\d{1,2}\.\d{1,2}|A\.\d{1,2}|AM\d+\.\d+|SL\d+\.\d+)\s+")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


@dataclass
class Page:
    page: int
    text: str


@dataclass
class ClauseChunk:
    clause_id: str
    page: int
    text: str


def normalize(text: str) -> str:
    """Collapse whitespace and unify quote/dash characters for robust matching."""
    return re.sub(r"\s+", " ", text.translate(_QUOTES)).strip().lower()


def load_document(path: Path) -> list[Page]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            return [Page(i, p.extract_text() or "") for i, p in enumerate(pdf.pages, start=1)]
    if suffix == ".docx":
        import docx

        d = docx.Document(str(path))
        # DOCX has no fixed pagination; treat the whole document as page 1.
        return [Page(1, "\n".join(p.text for p in d.paragraphs))]
    if suffix in (".txt", ".md"):
        return [Page(1, path.read_text(encoding="utf-8"))]
    raise ValueError(f"Unsupported contract format: {path.suffix}")


def full_text(pages: list[Page], with_markers: bool = True) -> str:
    if not with_markers:
        return "\n".join(p.text for p in pages)
    return "\n".join(f"[[PAGE {p.page}]]\n{p.text}" for p in pages)


def segment_clauses(pages: list[Page]) -> list[ClauseChunk]:
    """Split page text into numbered clauses (1.2, 13.4, A.3, AM1.1, SL1.1)."""
    chunks: list[ClauseChunk] = []
    for p in pages:
        matches = list(CLAUSE_START.finditer(p.text))
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(p.text)
            body = p.text[m.end() : end]
            # stop at the next ALL-CAPS heading line, if any
            body = re.split(r"\n(?=[A-Z0-9 .\-()]{8,}\n)", body)[0]
            chunks.append(ClauseChunk(m.group(1), p.page, re.sub(r"\s+", " ", body).strip()))
    return chunks


def verify_quote(
    quote: str | None, pages: list[Page], page: int | None = None
) -> tuple[bool, int | None]:
    """Return (found, page_found). A quote must appear verbatim (whitespace/case-insensitive)."""
    if not quote or len(quote.strip()) < 4:
        return False, None
    nq = normalize(quote)
    if page is not None:
        for p in pages:
            if p.page == page and nq in normalize(p.text):
                return True, page
    for p in pages:
        if nq in normalize(p.text):
            return True, p.page
    # quote spanning a page break
    joined = normalize(" ".join(p.text for p in pages))
    if nq in joined:
        return True, page
    return False, None
