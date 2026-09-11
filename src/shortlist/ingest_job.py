"""Integration 1: turn a job posting into an approved list of criteria.

A posting arrives as a live URL or a text file. The text is extracted locally,
then a model proposes structured criteria. The recruiter approves or edits them
before any candidate is screened, because everything downstream inherits these
and a wrong criterion silently corrupts every result.
"""
from __future__ import annotations

import re
from pathlib import Path

import httpx

from .schemas import Criterion, Importance, JobSpec

SYSTEM = """You extract hiring criteria from job postings.

Return JSON only, shaped exactly:
{"title": str, "organisation": str or null, "criteria":
  [{"id": "C1", "text": str, "importance": "essential" | "desirable"}]}

Rules:
- Use the employer's own wording. Do not invent, generalise or soften.
- One requirement per criterion. Split anything joined by "and" that is
  genuinely two testable things.
- "essential" only where the posting marks it required/essential/must.
  Everything else is "desirable".
- Ignore benefits, salary, equal-opportunity statements and how-to-apply text.
- 4 to 15 criteria. If the posting states none, return an empty list."""

_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_HTML = re.compile(r"<[^>]+>")


def fetch_posting(source: str, timeout: int = 30) -> str:
    """Accept a URL or a local path. Returns plain text."""
    if source.startswith(("http://", "https://")):
        resp = httpx.get(
            source,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Shortlist/0.3)"},
        )
        resp.raise_for_status()
        return html_to_text(resp.text)
    p = Path(source)
    if not p.exists():
        raise FileNotFoundError(f"Job posting not found: {source}")
    text = p.read_text(encoding="utf-8", errors="replace")
    return html_to_text(text) if p.suffix.lower() in {".html", ".htm"} else text


def html_to_text(html: str) -> str:
    try:
        from selectolax.parser import HTMLParser

        tree = HTMLParser(html)
        for tag in tree.css("script, style, nav, footer, header"):
            tag.decompose()
        body = tree.body
        text = body.text(separator="\n") if body else tree.text(separator="\n")
    except ImportError:
        text = _HTML.sub(" ", _TAG.sub(" ", html))
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def extract_criteria(text: str, source: str, client) -> tuple[JobSpec, object]:
    if len(text.strip()) < 120:
        raise ValueError(
            f"Posting text is only {len(text.strip())} characters. "
            "The fetch probably failed or the page is JavaScript-rendered. "
            "Save the posting as a .txt file and pass that instead."
        )
    data, usage = client.complete_json(SYSTEM, text[:18000])
    criteria = [
        Criterion(
            id=c.get("id") or f"C{i+1}",
            text=c["text"],
            importance=Importance(c.get("importance", "desirable")),
        )
        for i, c in enumerate(data.get("criteria", []))
        if c.get("text")
    ]
    spec = JobSpec(
        source=source,
        title=data.get("title") or "Untitled role",
        organisation=data.get("organisation"),
        criteria=criteria,
    )
    return spec, usage
