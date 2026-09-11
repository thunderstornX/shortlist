"""Command line interface. Two commands, in the order a recruiter uses them.

    shortlist criteria --job <url|file>          approve the criteria first
    shortlist screen   --criteria out/criteria.yaml --cvs samples/cvs

Splitting them is the human approval point: nothing is screened against criteria
a person has not seen.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import yaml

from .config import ConfigError, ROOT, available_providers, load_config, load_secrets
from .ingest_cv import load_folder
from .ingest_job import extract_criteria, fetch_posting
from .llm import AllProvidersFailed, LLMClient
from .logging_setup import RunLog
from .report import write_candidate_sheet, write_criteria_sheet, write_ranking
from .schemas import Criterion, Importance, JobSpec
from .screen import screen_candidate


def _client_and_cfg(args):
    load_secrets()
    cfg = load_config(args.config)
    provs = available_providers(cfg)
    if not provs:
        raise ConfigError(
            "No API key found. Copy .env.example to .env and add one key.\n"
            "Free options: openrouter.ai/keys or console.groq.com/keys"
        )
    return LLMClient(cfg, provs), cfg


def _run_id() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def cmd_criteria(args) -> int:
    client, cfg = _client_and_cfg(args)
    out = Path(cfg.get("output", {}).get("directory", "out"))
    log = RunLog(_run_id(), ROOT / "logs", cfg.get("privacy", {}).get("log_cv_text", False))

    print(f"Reading posting: {args.job}")
    text = fetch_posting(args.job)
    log.event("posting_fetched", source=args.job, chars=len(text))

    spec, usage = extract_criteria(text, args.job, client)
    log.event("criteria_extracted", count=len(spec.criteria), provider=usage.provider,
              latency_s=usage.latency_s)

    out.mkdir(parents=True, exist_ok=True)
    (out / "criteria.yaml").write_text(
        yaml.safe_dump(
            {"source": spec.source, "title": spec.title, "organisation": spec.organisation,
             "criteria": [{"id": c.id, "text": c.text, "importance": c.importance.value}
                          for c in spec.criteria]},
            sort_keys=False, allow_unicode=True),
        encoding="utf-8")
    sheet = write_criteria_sheet(spec, out)

    ess = len(spec.essential())
    print(f"\n{len(spec.criteria)} criteria found: {ess} essential, {len(spec.criteria)-ess} desirable")
    print(f"  {sheet}   <- read this")
    print(f"  {out/'criteria.yaml'}   <- edit this if anything is wrong")
    print(f"\nWhen the criteria look right:\n  shortlist screen --criteria {out/'criteria.yaml'} --cvs <folder>")
    return 0


def _load_spec(path: Path) -> JobSpec:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return JobSpec(
        source=data.get("source", str(path)),
        title=data.get("title", "Untitled role"),
        organisation=data.get("organisation"),
        criteria=[Criterion(id=c["id"], text=c["text"],
                            importance=Importance(c.get("importance", "desirable")))
                  for c in data["criteria"]],
    )


def cmd_screen(args) -> int:
    client, cfg = _client_and_cfg(args)
    out = Path(cfg.get("output", {}).get("directory", "out"))
    log = RunLog(_run_id(), ROOT / "logs", cfg.get("privacy", {}).get("log_cv_text", False))

    spec = _load_spec(Path(args.criteria))
    docs, failures = load_folder(args.cvs)

    if failures:
        print(f"\n{len(failures)} file(s) could not be read and were NOT screened:")
        for name, err in failures:
            print(f"  - {name}: {err.splitlines()[0]}")
            log.event("cv_unreadable", file=name, error=err[:200])
        print("  These are not rejections. Fix or supply text versions, then re-run.\n")

    if not docs:
        print("No readable CVs. Nothing to do.")
        return 1

    print(f"Screening {len(docs)} candidate(s) against {len(spec.criteria)} criteria "
          f"({len(spec.essential())} essential)\n")

    reports = []
    for i, doc in enumerate(docs, 1):
        print(f"[{i}/{len(docs)}] {doc.candidate_id} ... ", end="", flush=True)
        try:
            rep, usage = screen_candidate(doc, spec, client, cfg, log)
        except AllProvidersFailed as exc:
            print(f"FAILED\n    {exc}")
            log.event("candidate_failed", candidate=doc.candidate_id, error=str(exc)[:300])
            continue
        reports.append(rep)
        write_candidate_sheet(rep, spec, out)
        note = f"{rep.essential_met}/{rep.essential_total} essential"
        if rep.grounding_rate < 1.0:
            note += f", evidence verified {rep.grounding_rate:.0%}"
        if rep.flags:
            note += f", {len(rep.flags)} flag(s)"
        print(f"{note}  [{usage.provider}, {usage.latency_s:.1f}s]")

    if not reports:
        print("\nEvery candidate failed. Check your API key and network.")
        return 1

    ranking = write_ranking(reports, out)
    print(f"\nWritten to {out}/")
    print(f"  ranking.csv          shortlist, best first")
    print(f"  <candidate>.md       one review sheet each, with evidence")
    print(f"  logs/                full audit trail of this run")
    needing = sum(1 for r in reports if any(a.needs_human for a in r.assessments) or r.flags)
    if needing:
        print(f"\n{needing} of {len(reports)} candidate(s) need a person to look before deciding.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="shortlist",
        description="Screen candidates against a job's criteria, with evidence checked against the CV.")
    ap.add_argument("--config", default=None, help="path to config.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("criteria", help="step 1: pull criteria out of a job posting for approval")
    c.add_argument("--job", required=True, help="job posting URL or local file")
    c.set_defaults(func=cmd_criteria)

    s = sub.add_parser("screen", help="step 2: screen a folder of CVs against approved criteria")
    s.add_argument("--criteria", required=True, help="out/criteria.yaml, after you have checked it")
    s.add_argument("--cvs", required=True, help="folder of CVs (.pdf, .txt, .md)")
    s.set_defaults(func=cmd_screen)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, FileNotFoundError, NotADirectoryError, ValueError) as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
