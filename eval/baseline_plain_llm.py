#!/usr/bin/env python3
"""Baseline arm: what a recruiter gets from pasting a posting and a CV into a chatbot.

The brief allows the baseline to be "the manual process or simple ChatGPT use".
This measures the second. It is deliberately naive: one prompt, free text out, no
schema, no verification. Exactly what someone does today.

The same grounding check the product uses is then applied to whatever the baseline
quoted, which is the whole point: plain use produces confident evidence nobody
checks. Same model and provider as the product, so the comparison isolates the
system, not the model.

    python3 eval/baseline_plain_llm.py
"""
from __future__ import annotations

import json
import re
import statistics
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shortlist.config import available_providers, load_config, load_secrets  # noqa: E402
from shortlist.grounding import verify_quote  # noqa: E402
from shortlist.ingest_cv import load_folder  # noqa: E402
from shortlist.llm import LLMClient  # noqa: E402

# What a recruiter actually types. No schema, no rules, no verification.
PROMPT = """Here is a job posting and a candidate's CV.

Which of the job's requirements does this candidate meet? For each requirement say
whether they meet it and quote the part of the CV that shows it.

JOB POSTING:
{posting}

CV:
{cv}
"""

# The baseline answers in markdown, so quoted evidence comes back wrapped in smart
# quotes with bold markers injected inside, fragments joined by ellipses, and
# typographic hyphens substituted for plain ones. All of that is stripped before
# checking, because the fair question is whether the SUBSTANCE is in the CV, not
# whether the model formatted it. What survives stripping and still fails is a real
# miss.
QUOTE = re.compile(r'[\u201c"]([^\u201d"]{12,400})[\u201d"]')


def clean_quote(q: str) -> list[str]:
    """Strip markdown and split ellipsis-joined fragments into separate claims."""
    # Strip single as well as double asterisks. The first version only handled
    # "**" and left stray "*" inside quotes, which broke verbatim matching and
    # inflated the apparent failure rate. Third instrument bug found by hand-
    # checking flagged quotes; the lesson is that the measuring tool needs the
    # same scepticism as the thing being measured.
    q = re.sub(r"\*+|__|`|<br\s*/?>", " ", q)
    q = q.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
    parts = re.split(r"\s*(?:\u2026|\.\.\.)\s*", q)
    out = []
    for s in parts:
        s = re.sub(r"\s+", " ", s)
        # Stripping "**" left a space before punctuation ("environments , deployed"),
        # which failed verbatim matching and made the baseline look worse than it is.
        # Caught 2026-09-11 by re-checking a flagged quote by hand. The instrument
        # must not manufacture the failures it reports.
        s = re.sub(r"\s+([,.;:!?])", r"\1", s)
        s = s.strip(" .,;:")
        if len(s) >= 12:
            out.append(s)
    return out


def main() -> int:
    load_secrets()
    cfg = load_config(None)
    provs = available_providers(cfg)
    if not provs:
        print("No API key. Add one to .env first.")
        return 1

    posting = (ROOT / "samples" / "job_posting.txt").read_text(encoding="utf-8")
    docs, failures = load_folder(ROOT / "samples" / "baseline_cvs")
    for name, err in failures:
        print(f"  unreadable: {name}")

    # Free text out, so the JSON response_format the product uses is turned off.
    client = LLMClient(cfg, provs)
    import shortlist.llm as L
    original = L.LLMClient._call

    def plain_call(self, prov, system, user):
        import httpx
        from shortlist.config import api_key_for
        r = httpx.post(
            L.ENDPOINTS[prov["name"]],
            headers={"Authorization": f"Bearer {api_key_for(prov['name'])}",
                     "Content-Type": "application/json"},
            json={"model": prov["model"],
                  "messages": [{"role": "user", "content": user}],
                  "temperature": 0.0, "max_tokens": 4000},
            timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:150]}")
        j = r.json()
        msg = j["choices"][0]["message"]
        if not msg.get("content"):
            # HTTP 200 with a null body. The reasoning trace consumed the budget.
            raise RuntimeError(
                f"empty content, finish_reason={j['choices'][0].get('finish_reason')}, "
                f"provider={j.get('provider')}")
        return j

    print("=" * 70)
    print("BASELINE: plain chatbot use, no system, no verification")
    print(f"model: {provs[0]['model']} via {provs[0]['name']}   candidates: {len(docs)}")
    print("=" * 70)

    rows, lats, toks = [], [], []
    for doc in docs:
        user = PROMPT.format(posting=posting, cv=doc.text)
        # A person hitting a dropped connection simply sends it again, so the
        # measurement loop does too. Only the successful attempt is timed.
        body, lat = None, 0.0
        for attempt in range(4):
            try:
                t0 = time.time()
                body = plain_call(client, provs[0], "", user)
                lat = time.time() - t0
                break
            except Exception as exc:  # noqa: BLE001
                print(f"  {doc.candidate_id}: attempt {attempt+1} failed ({type(exc).__name__}), retrying")
                time.sleep(3 * (attempt + 1))
        if body is None:
            print(f"  {doc.candidate_id}: gave up after 4 attempts")
            continue
        text = body["choices"][0]["message"]["content"]
        u = body.get("usage") or {}
        tok = u.get("prompt_tokens", 0) + u.get("completion_tokens", 0)

        raw = QUOTE.findall(text)
        quotes = [f for q in raw for f in clean_quote(q)]
        checked = [(q, *verify_quote(q, doc.text, 1.0)) for q in quotes]
        grounded = sum(1 for _, ok, _ in checked if ok)
        # Separate "altered but recognisable" from "not in the CV at all".
        # A fragment under 12 characters is rejected by the verifier as too short
        # to prove anything, which is NOT the same as being absent from the CV.
        # Conflating the two would overstate the baseline's failure rate.
        short = [(q, r) for q, ok, r in checked if not ok and len(q) < 12]
        near = [(q, r) for q, ok, r in checked if not ok and len(q) >= 12 and r >= 0.80]
        absent = [(q, r) for q, ok, r in checked if not ok and len(q) >= 12 and r < 0.80]
        ungrounded = near + absent + short

        lats.append(lat); toks.append(tok)
        rows.append({"candidate": doc.candidate_id, "latency_s": round(lat, 2),
                     "tokens": tok, "quotes_offered": len(quotes),
                     "quotes_grounded": grounded,
                     "quotes_ungrounded": len(ungrounded),
                     "quotes_altered": len(near), "quotes_absent": len(absent),
                     "quotes_too_short_to_check": len(short),
                     "altered_examples": [{"quote": q[:140], "best_match": r} for q, r in near[:3]],
                     "absent_examples": [{"quote": q[:140], "best_match": r} for q, r in absent[:3]],
                     "raw_output_chars": len(text)})
        rate = f"{grounded}/{len(quotes)}" if quotes else "0/0"
        note = ""
        if near:
            note += f"  {len(near)} altered"
        if absent:
            note += f"  {len(absent)} ABSENT"
        print(f"  {doc.candidate_id:<6} {lat:6.1f}s  {tok:>5} tok  verbatim {rate}{note}")

    if not rows:
        print("-" * 70)
        print("  No candidate completed. Nothing to report; this is not a result.")
        return 1

    tq = sum(r["quotes_offered"] for r in rows)
    tg = sum(r["quotes_grounded"] for r in rows)
    print("-" * 70)
    print(f"  latency median {statistics.median(lats):.1f}s   total {sum(lats):.0f}s for {len(rows)} candidates")
    print(f"  tokens  median {int(statistics.median(toks))}   total {sum(toks)}")
    ta = sum(r["quotes_altered"] for r in rows)
    tb = sum(r["quotes_absent"] for r in rows)
    print(f"  EVIDENCE CLAIMS {tq}   VERBATIM IN THE CV {tg}  ({tg/tq*100 if tq else 0:.1f}%)")
    ts = sum(r.get("quotes_too_short_to_check", 0) for r in rows)
    print(f"  ALTERED but recognisable {ta}   NOT IN THE CV AT ALL {tb}   too short to check {ts}")
    print(f"  A recruiter checking by copy and paste would fail to find {tq-tg} of {tq}.")
    print("=" * 70)

    out = ROOT / "eval" / "results"; out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = out / f"baseline-plain-llm-{stamp}.json"
    path.write_text(json.dumps({
        "arm": "plain chatbot use",
        "model": provs[0]["model"], "provider": provs[0]["name"],
        "candidates": rows,
        "summary": {"n": len(rows),
                    "latency_median_s": round(statistics.median(lats), 2),
                    "latency_total_s": round(sum(lats), 1),
                    "tokens_median": int(statistics.median(toks)),
                    "tokens_total": sum(toks),
                    "quotes_offered": tq, "quotes_grounded": tg,
                    "quotes_altered": sum(r["quotes_altered"] for r in rows),
                    "quotes_absent": sum(r["quotes_absent"] for r in rows),
                    "quotes_too_short_to_check": sum(r.get("quotes_too_short_to_check", 0) for r in rows),
                    "quotes_ungrounded": tq - tg,
                    "grounding_rate": round(tg / tq, 4) if tq else None}},
        indent=2), encoding="utf-8")
    print(f"  written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
