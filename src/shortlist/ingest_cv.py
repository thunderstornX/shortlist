"""Integration 2: read candidate CVs from PDF or text.

Extraction failure is the single most common real-world break in this workflow,
and it fails quietly: a scanned CV yields an empty string and the candidate
scores zero on every criterion while looking like a legitimate rejection. So an
unreadable CV raises rather than returning empty text.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MIN_USABLE_CHARS = 200


class UnreadableCV(RuntimeError):
    pass


@dataclass
class CVDocument:
    candidate_id: str
    source_file: str
    text: str
    pages: int = 0


def load_cv(path: str | Path) -> CVDocument:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"CV not found: {p}")

    if p.suffix.lower() == ".pdf":
        text, pages = _read_pdf(p)
    else:
        text, pages = p.read_text(encoding="utf-8", errors="replace"), 1

    stripped = text.strip()
    if len(stripped) < MIN_USABLE_CHARS:
        raise UnreadableCV(
            f"{p.name}: only {len(stripped)} characters of text extracted"
            f"{f' from {pages} page(s)' if pages else ''}. "
            "This is usually a scanned or image-only PDF. Run OCR on it, or supply "
            "a text version. It has NOT been screened and is not a rejection."
        )
    return CVDocument(candidate_id=p.stem, source_file=str(p), text=stripped, pages=pages)


def _read_pdf(p: Path) -> tuple[str, int]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise UnreadableCV("pypdf is not installed: pip install -r requirements.txt") from exc
    try:
        reader = PdfReader(str(p))
        pages = len(reader.pages)
        return "\n".join((pg.extract_text() or "") for pg in reader.pages), pages
    except Exception as exc:  # noqa: BLE001
        raise UnreadableCV(f"{p.name}: PDF could not be parsed ({type(exc).__name__}: {exc})") from exc


def load_folder(folder: str | Path) -> tuple[list[CVDocument], list[tuple[str, str]]]:
    """Load every CV in a folder. Returns (loaded, failures) so one bad file
    never aborts a batch, and every failure is reported rather than swallowed."""
    f = Path(folder)
    if not f.is_dir():
        raise NotADirectoryError(f"Not a folder: {f}")
    docs, failures = [], []
    for path in sorted(f.iterdir()):
        if path.suffix.lower() not in {".pdf", ".txt", ".md"}:
            continue
        try:
            docs.append(load_cv(path))
        except (UnreadableCV, FileNotFoundError) as exc:
            failures.append((path.name, str(exc)))
    return docs, failures
