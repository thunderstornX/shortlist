"""Verify that a quoted piece of evidence really appears in the candidate's CV.

This is the load-bearing guardrail. A screening model will happily produce a
fluent, plausible, entirely invented quote, and a recruiter reading the output
has no way to tell. So the system does not trust the quote: it checks it.

Matching normalises whitespace and case, because PDF extraction introduces line
breaks and inconsistent spacing that are not meaningful differences. It does not
normalise anything else, so a paraphrase fails, which is the intent.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

_WS = re.compile(r"\s+")
# PDF extraction breaks a hyphenated word across a line and leaves "high- throughput".
# That is a layout artefact, not a different word, and it is the same class of
# difference as the whitespace handled below. Found on a real CV where a correctly
# quoted "High-throughput" failed to match the extracted text at 0.94.
_SPLIT_HYPHEN = re.compile(r"(\w)-\s+(\w)")


def normalise(text: str) -> str:
    text = _SPLIT_HYPHEN.sub(r"\1-\2", text)
    return _WS.sub(" ", text).strip().lower()


def verify_quote(quote: str, source: str, min_ratio: float = 1.0) -> tuple[bool, float]:
    """Return (grounded, ratio).

    ratio == 1.0 means the quote is an exact substring of the source once
    whitespace and case are normalised. Below that it is the best partial
    similarity found, which is reported so a human can see how far off it was.
    """
    q, s = normalise(quote), normalise(source)
    if not q:
        return False, 0.0
    if len(q) < 12:
        # Very short spans match by accident and prove nothing.
        return False, 0.0
    if q in s:
        return True, 1.0
    if min_ratio >= 1.0:
        return False, _best_ratio(q, s)
    ratio = _best_ratio(q, s)
    return ratio >= min_ratio, ratio


def _best_ratio(q: str, s: str) -> float:
    """Best similarity between the quote and any same-length window of the source."""
    if not s:
        return 0.0
    matcher = SequenceMatcher(None, q, s, autojunk=False)
    block = matcher.find_longest_match(0, len(q), 0, len(s))
    if block.size == 0:
        return 0.0
    return round(block.size / len(q), 4)


def detect_injection(text: str) -> list[str]:
    """Flag CV content that is trying to instruct the screener rather than describe a career.

    Embedding hidden instructions in a CV is a real and documented tactic against
    automated screening, so it is treated as a first-class input-validation
    concern rather than a curiosity. Detection is deliberately conservative and
    only ever raises a flag for a human; it never changes a verdict by itself.
    """
    patterns = [
        r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
        r"disregard\s+(the\s+)?(above|previous|prior)",
        r"you\s+are\s+(now\s+)?(an?\s+)?(ai|assistant|system|recruiter)",
        r"(mark|rate|score)\s+(this\s+)?(candidate|applicant)\s+(as\s+)?(highly|excellent|met|qualified)",
        r"system\s*prompt",
        r"</?(system|instruction)s?>",
        r"do\s+not\s+(mention|reveal|disclose)\s+this",
    ]
    found: list[str] = []
    low = text.lower()
    for pat in patterns:
        m = re.search(pat, low)
        if m:
            found.append(m.group(0)[:80])
    return found
