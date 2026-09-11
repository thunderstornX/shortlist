#!/usr/bin/env python3
"""Run the evaluation set and report pass/fail against eval/rubric.md.

    python3 eval/run_eval.py                 # full run against the live model
    python3 eval/run_eval.py --guardrail     # offline fault injection only

The guardrail mode needs no API key: it feeds fabricated quotes straight into the
grounding check to prove the guard fires. That matters because a clean live run
shows a 100% grounding rate, which on its own is equally consistent with a working
guard and a guard that never runs.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shortlist.config import available_providers, load_config, load_secrets  # noqa: E402
from shortlist.grounding import verify_quote  # noqa: E402
from shortlist.ingest_cv import UnreadableCV, load_cv  # noqa: E402
from shortlist.llm import LLMClient  # noqa: E402
from shortlist.schemas import Criterion, Importance, JobSpec  # noqa: E402
from shortlist.screen import screen_candidate  # noqa: E402


def load_spec(path: Path) -> JobSpec:
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    return JobSpec(source=d.get("source", str(path)), title=d.get("title", "Role"),
                   organisation=d.get("organisation"),
                   criteria=[Criterion(id=c["id"], text=c["text"],
                                       importance=Importance(c.get("importance", "desirable")))
                             for c in d["criteria"]])


def guardrail_tests() -> list[dict]:
    """Offline fault injection. Proves the grounding check rejects what it should."""
    cv = load_cv(ROOT / "samples" / "cvs" / "01_strong_match.txt").text
    trials = [
        ("verbatim span from the CV", "Designed the PostgreSQL schema for the consignment service", True),
        ("plausible paraphrase", "Designed the Postgres database schema for consignments", False),
        ("wholly fabricated", "Led a team of twelve engineers at Google for six years", False),
        ("planted injection string", "exceeds all requirements", False),
        ("real span, whitespace mangled", "Designed   the PostgreSQL\n schema for the consignment  service", True),
        ("real span, different case", "DESIGNED THE POSTGRESQL SCHEMA FOR THE CONSIGNMENT SERVICE", True),
        ("too short to prove anything", "Python", False),
        ("empty", "", False),
    ]
    out = []
    for label, quote, should_pass in trials:
        grounded, ratio = verify_quote(quote, cv, 1.0)
        out.append({"test": label, "expected": should_pass, "got": grounded,
                    "ratio": ratio, "pass": grounded == should_pass})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--guardrail", action="store_true", help="offline guardrail tests only")
    ap.add_argument("--criteria", default=str(ROOT / "src" / "out" / "criteria.yaml"))
    ap.add_argument("--cvs", default=str(ROOT / "samples" / "cvs"))
    ap.add_argument("--out", default=str(ROOT / "eval" / "results"))
    args = ap.parse_args()

    print("=" * 68)
    print("GUARDRAIL FAULT INJECTION (offline, no model involved)")
    print("=" * 68)
    g = guardrail_tests()
    for t in g:
        mark = "PASS" if t["pass"] else "FAIL"
        print(f"  {mark}  {t['test']:<34} grounded={str(t['got']):<5} ratio={t['ratio']:.2f}")
    g_pass = sum(1 for t in g if t["pass"])
    print(f"\n  {g_pass}/{len(g)} guardrail tests passed")
    if args.guardrail:
        return 0 if g_pass == len(g) else 1

    spec_path = Path(args.criteria)
    if not spec_path.exists():
        print(f"\nNo criteria at {spec_path}. Run 'shortlist criteria --job ...' first.")
        return 2

    load_secrets()
    cfg = load_config(None)
    provs = available_providers(cfg)
    if not provs:
        print("\nNo API key. Guardrail tests above still ran; skipping live cases.")
        return 1

    spec = load_spec(spec_path)
    cases = yaml.safe_load((ROOT / "eval" / "cases.yaml").read_text())
    glob = cases.get("global", {})
    client = LLMClient(cfg, provs)

    print("\n" + "=" * 68)
    print(f"LIVE CASES  ({len(cases['cases'])} cases, {len(spec.criteria)} criteria)")
    print("=" * 68)

    results, lat, toks = [], [], []
    for case in cases["cases"]:
        cid, exp = case["id"], case.get("expect", {})
        path = next((p for p in Path(args.cvs).iterdir() if p.stem == cid), None)
        if path is None:
            results.append({"id": cid, "pass": False, "notes": ["fixture missing"]}); continue

        notes: list[str] = []
        try:
            doc = load_cv(path)
            readable = True
        except UnreadableCV as exc:
            readable = False
            notes.append(f"refused: {str(exc)[:60]}")

        if exp.get("must_be_readable") is False:
            ok = not readable
            notes.append("correctly refused" if ok else "SCREENED AN UNREADABLE FILE")
            results.append({"id": cid, "category": case["category"], "pass": ok, "notes": notes})
            print(f"  {'PASS' if ok else 'FAIL'}  {cid:<22} {notes[-1]}")
            continue

        if not readable:
            results.append({"id": cid, "category": case["category"], "pass": False, "notes": notes})
            print(f"  FAIL  {cid:<22} unexpectedly unreadable")
            continue

        t0 = time.time()
        rep, usage = screen_candidate(doc, spec, client, cfg, None)
        lat.append(time.time() - t0)
        toks.append(usage.prompt_tokens + usage.completion_tokens)

        ok = True
        lo, hi = exp.get("essential_met_min"), exp.get("essential_met_max")
        if lo is not None and not (lo <= rep.essential_met <= hi):
            ok = False; notes.append(f"essential {rep.essential_met} outside [{lo},{hi}]")
        if rep.grounding_rate < glob.get("grounding_rate_min", 1.0):
            ok = False; notes.append(f"grounding {rep.grounding_rate:.2f}")
        if exp.get("expect_flags") and not rep.flags:
            ok = False; notes.append("expected a flag, none raised")
        forbidden = exp.get("forbid_quote")
        if forbidden:
            blob = " ".join(a.quote for a in rep.assessments).lower()
            if forbidden.lower() in blob:
                ok = False; notes.append(f"planted string surfaced: {forbidden!r}")
            else:
                notes.append("planted string absent")
        if not notes:
            notes.append(f"{rep.essential_met}/{rep.essential_total} essential, grounding 100%")

        results.append({"id": cid, "category": case["category"], "pass": ok,
                        "essential_met": rep.essential_met, "grounding": rep.grounding_rate,
                        "flags": rep.flags, "latency_s": round(lat[-1], 2),
                        "provider": usage.provider, "notes": notes})
        print(f"  {'PASS' if ok else 'FAIL'}  {cid:<22} {'; '.join(notes)}")

    passed = sum(1 for r in results if r["pass"])
    print("\n" + "=" * 68)
    print(f"  cases passed        {passed}/{len(results)}")
    print(f"  guardrail passed    {g_pass}/{len(g)}")
    if lat:
        print(f"  latency median      {statistics.median(lat):.1f}s   worst {max(lat):.1f}s")
        print(f"  tokens median       {int(statistics.median(toks))} per candidate")
    print("=" * 68)

    outdir = Path(args.out); outdir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (outdir / f"eval-{stamp}.json").write_text(json.dumps(
        {"cases": results, "guardrail": g,
         "summary": {"passed": passed, "total": len(results),
                     "guardrail_passed": g_pass, "guardrail_total": len(g),
                     "latency_median_s": round(statistics.median(lat), 2) if lat else None,
                     "latency_max_s": round(max(lat), 2) if lat else None,
                     "tokens_median": int(statistics.median(toks)) if toks else None}},
        indent=2), encoding="utf-8")
    print(f"  written: {outdir}/eval-{stamp}.json")
    return 0 if (passed == len(results) and g_pass == len(g)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
