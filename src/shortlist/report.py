"""Outputs a recruiter reads: one review sheet per candidate, one ranked CSV."""
from __future__ import annotations

import csv
from pathlib import Path

from .schemas import CandidateReport, Importance, JobSpec

SYMBOL = {"met": "MET", "partial": "PARTIAL", "not_met": "NOT MET", "unsupported": "NEEDS CHECK"}


def write_candidate_sheet(rep: CandidateReport, spec: JobSpec, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    by_id = {c.id: c for c in spec.criteria}
    L: list[str] = []
    L.append(f"# {rep.candidate_id}")
    L.append("")
    L.append(f"**Role:** {spec.title}" + (f", {spec.organisation}" if spec.organisation else ""))
    L.append(f"**Essential criteria met:** {rep.essential_met} of {rep.essential_total}")
    L.append(f"**Desirable criteria met:** {rep.desirable_met} of {rep.desirable_total}")
    L.append(f"**Evidence verified against the CV:** {rep.grounding_rate:.0%}")
    L.append("")
    L.append(f"## Recommended next action\n\n**{rep.next_action}**")
    L.append("")
    if rep.flags:
        L.append("## Flags for a person to look at\n")
        L.extend(f"- {f}" for f in rep.flags)
        L.append("")
    L.append("## Criterion by criterion\n")
    for a in rep.assessments:
        crit = by_id.get(a.criterion_id)
        label = crit.text if crit else a.criterion_id
        imp = "essential" if crit and crit.importance == Importance.ESSENTIAL else "desirable"
        L.append(f"### {a.criterion_id} ({imp}): {label}")
        L.append("")
        L.append(f"**{SYMBOL.get(a.verdict, a.verdict)}**"
                 + (f" · confidence {a.confidence:.2f}" if a.confidence else "")
                 + ("  · **needs a human**" if a.needs_human else ""))
        L.append("")
        if a.quote:
            verified = "verified in the CV" if a.grounded else "NOT found in the CV"
            L.append(f"> {a.quote}")
            L.append("")
            L.append(f"*Evidence {verified}.*")
            L.append("")
        if a.reasoning:
            L.append(a.reasoning)
            L.append("")
    L.append("---")
    L.append("")
    L.append("Every quote above is checked against the CV text automatically. Anything marked "
             "NOT found or NEEDS CHECK was not verifiable and must be confirmed by a person "
             "before it is used in a decision.")
    path = out_dir / f"{rep.candidate_id}.md"
    path.write_text("\n".join(L), encoding="utf-8")
    return path


def write_ranking(reports: list[CandidateReport], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "ranking.csv"
    rows = sorted(reports, key=lambda r: (-r.score(), r.candidate_id))
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["rank", "candidate", "score", "essential_met", "essential_total",
                    "desirable_met", "grounding_rate", "needs_human", "flags", "next_action"])
        for i, r in enumerate(rows, 1):
            w.writerow([i, r.candidate_id, f"{r.score():.4f}", r.essential_met, r.essential_total,
                        r.desirable_met, f"{r.grounding_rate:.4f}",
                        sum(1 for a in r.assessments if a.needs_human),
                        "; ".join(r.flags), r.next_action])
    return path


def write_criteria_sheet(spec: JobSpec, out_dir: Path) -> Path:
    """Written before screening so the recruiter approves the criteria first."""
    out_dir.mkdir(parents=True, exist_ok=True)
    L = [f"# Criteria for review: {spec.title}", "",
         f"Source: {spec.source}", "",
         "Check these before screening. Everything downstream depends on them.",
         "Edit the text, change essential/desirable, or delete a row, then re-run with",
         "`--criteria out/criteria.yaml`.", ""]
    for imp in (Importance.ESSENTIAL, Importance.DESIRABLE):
        rows = [c for c in spec.criteria if c.importance == imp]
        if not rows:
            continue
        L.append(f"## {imp.value.title()}\n")
        L.extend(f"- **{c.id}** {c.text}" for c in rows)
        L.append("")
    path = out_dir / "criteria.md"
    path.write_text("\n".join(L), encoding="utf-8")
    return path
