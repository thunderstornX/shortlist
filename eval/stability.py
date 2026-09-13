#!/usr/bin/env python3
"""Does the system give the same answer twice?

A screening tool that changes its mind between runs cannot be trusted whatever its
accuracy, and a single green run says nothing about that. This repeats the same
screening N times at temperature 0 and measures how often every run agrees.

Reported per (candidate, criterion) pair rather than per candidate, because a
candidate can land on the same total by different routes and that is not stability.

    python3 eval/stability.py --runs 4

Pacing note: free-tier providers cap tokens per minute, so the client's rate-limit
backoff will pause between calls. A four-run pass takes roughly ten minutes.
"""
from __future__ import annotations

import argparse, json, statistics, sys, time
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shortlist.config import available_providers, load_config, load_secrets
from shortlist.ingest_cv import load_folder
from shortlist.llm import AllProvidersFailed, LLMClient
from shortlist.schemas import Criterion, Importance, JobSpec
from shortlist.screen import screen_candidate


def load_spec(path: Path) -> JobSpec:
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    return JobSpec(source=d.get("source", str(path)), title=d.get("title", "Role"),
                   organisation=d.get("organisation"),
                   criteria=[Criterion(id=c["id"], text=c["text"],
                                       importance=Importance(c.get("importance", "desirable")))
                             for c in d["criteria"]])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=4)
    ap.add_argument("--criteria", default=str(ROOT / "src" / "out" / "criteria.yaml"))
    ap.add_argument("--cvs", default=str(ROOT / "samples" / "baseline_cvs"))
    ap.add_argument("--pace", type=float, default=16.0)
    args = ap.parse_args()

    load_secrets()
    cfg = load_config(None)
    provs = available_providers(cfg)
    if not provs:
        print("No API key."); return 1
    client = LLMClient(cfg, provs)

    spec = load_spec(Path(args.criteria))
    docs, failures = load_folder(args.cvs)
    for name, err in failures:
        print(f"  unreadable, excluded: {name}")

    print("=" * 72)
    print(f"STABILITY   {args.runs} runs x {len(docs)} candidates x "
          f"{len(spec.criteria)} criteria   temperature "
          f"{cfg['model'].get('temperature')}")
    print("=" * 72)

    # verdicts[candidate][criterion] = [verdict per run]
    verdicts: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    ess: dict[str, list[int]] = defaultdict(list)
    grounding: list[float] = []
    providers_used: Counter = Counter()
    failed = 0

    for run in range(1, args.runs + 1):
        print(f"\n  run {run}/{args.runs}")
        for doc in docs:
            time.sleep(args.pace)
            try:
                rep, usage = screen_candidate(doc, spec, client, cfg, None)
            except AllProvidersFailed as exc:
                failed += 1
                print(f"    {doc.candidate_id:<6} FAILED  {str(exc)[:70]}")
                continue
            for a in rep.assessments:
                verdicts[doc.candidate_id][a.criterion_id].append(a.verdict)
            ess[doc.candidate_id].append(rep.essential_met)
            grounding.append(rep.grounding_rate)
            providers_used[usage.provider] += 1
            print(f"    {doc.candidate_id:<6} {rep.essential_met}/{rep.essential_total} essential "
                  f"grounding {rep.grounding_rate:.2f}  [{usage.provider} {usage.latency_s:.1f}s]",
                  flush=True)

    # agreement per (candidate, criterion), counting only pairs seen in every run
    agree = total = 0
    unstable = []
    for cand, crits in verdicts.items():
        for cid, vs in crits.items():
            if len(vs) < args.runs:
                continue
            total += 1
            if len(set(vs)) == 1:
                agree += 1
            else:
                unstable.append((cand, cid, vs))

    print("\n" + "=" * 72)
    print("RESULTS")
    print(f"  candidate/criterion pairs compared across all {args.runs} runs: {total}")
    if total:
        print(f"  IDENTICAL VERDICT IN EVERY RUN: {agree}/{total} = {agree/total:.1%}")
    stable_counts = sum(1 for v in ess.values() if len(set(v)) == 1 and len(v) == args.runs)
    print(f"  essential_met identical in every run: {stable_counts}/{len(ess)} candidates")
    for cand, v in sorted(ess.items()):
        mark = "stable" if len(set(v)) == 1 else "VARIES"
        print(f"    {cand:<6} {v}  {mark}")
    if grounding:
        print(f"  grounding rate: min {min(grounding):.2f}  mean {statistics.mean(grounding):.2f}")
    print(f"  screenings failed outright: {failed}")
    print(f"  providers used: {dict(providers_used)}")

    if unstable:
        print(f"\n  UNSTABLE PAIRS ({len(unstable)}):")
        for cand, cid, vs in unstable[:12]:
            print(f"    {cand} {cid}: {vs}")
    print("=" * 72)

    out = ROOT / "eval" / "results" / f"stability-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "runs": args.runs, "candidates": len(docs), "criteria": len(spec.criteria),
        "pairs_compared": total, "pairs_identical": agree,
        "agreement": round(agree / total, 4) if total else None,
        "essential_met_per_candidate": {k: v for k, v in ess.items()},
        "grounding_min": min(grounding) if grounding else None,
        "grounding_mean": round(statistics.mean(grounding), 4) if grounding else None,
        "failed": failed, "providers": dict(providers_used),
        "unstable": [{"candidate": c, "criterion": i, "verdicts": v} for c, i, v in unstable],
    }, indent=2))
    print(f"  written: {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
