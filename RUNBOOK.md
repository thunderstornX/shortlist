# Operator runbook

For whoever keeps this running. Assumes command-line comfort, not familiarity with
this codebase.

## Architecture in one pass

```
job posting (URL or file)
  └─ ingest_job.fetch_posting        HTTP or file read, HTML stripped locally
       └─ ingest_job.extract_criteria   model call -> JobSpec
            └─ HUMAN APPROVES out/criteria.yaml        <-- gate 1
                 └─ ingest_cv.load_folder              per-file, failures collected
                      └─ screen.screen_candidate       model call, one per candidate
                           └─ grounding.verify_quote   every quote checked vs CV
                                └─ report.*            review sheets + ranking.csv
                                     └─ HUMAN DECIDES  <-- gate 2
```

Module boundaries are deliberate: ingestion knows nothing about models, screening
knows nothing about file formats, grounding knows nothing about either and is pure
string comparison, which is why it can be tested offline with no API key.

## Files that matter

| Path | Purpose |
|---|---|
| `config/config.yaml` | Behaviour. No secrets. Safe to commit if you wish. |
| `.env` | API keys only. Never committed, `.gitignore`d. |
| `src/shortlist/grounding.py` | The evidence check. Change nothing here without running the guardrail tests. |
| `logs/<run-id>.jsonl` | One JSON object per event. Full audit trail. |
| `eval/cases.yaml` | The 12-case test set and expectations. |
| `out/` | Generated. Safe to delete. |

## Routine operations

**Check the system still works, without spending anything:**

```bash
python3 eval/run_eval.py --guardrail
```

Offline, no API key needed, ~1 second. All 8 must pass. **Run this after any change
to `grounding.py`, extraction, or the screening prompt.**

**Full evaluation against the live model:**

```bash
python3 eval/run_eval.py
```

Roughly 12 model calls, about five minutes, writes `eval/results/eval-<stamp>.json`.

**Change model or provider:** edit `model.providers` in `config/config.yaml`. They
are tried top to bottom; the first with a key present and a healthy response wins.
After changing, re-run the full evaluation: model changes move verdict bands.

## Errors and what they mean

| Message | Cause | Fix |
|---|---|---|
| `No config at .../config.yaml` | First run | `cp config/config.example.yaml config/config.yaml` |
| `No API key found` | `.env` missing or empty | `cp .env.example .env`, add one key |
| `only N characters of text extracted` | Scanned or image-only CV | OCR it, or get a text version. **Not a rejection.** |
| `Posting text is only N characters` | Page is JavaScript-rendered | Save the posting as `.txt` and pass that |
| `has no essential criteria, so candidates cannot be ranked` | Posting marks nothing as required. Measured on real postings, this is common | `out/criteria.yaml` **is still written**; open it, mark the genuinely required rows `essential`, re-run |
| `Every provider failed after retries` | Network, quota, or bad key | Check the `errors` list printed with it; each entry names the provider and the HTTP status |
| `Wall-clock deadline of Ns exceeded` | A provider stalled | Socket timeouts apply per read, not to total elapsed, so this is a separate ceiling. Raise `reliability.deadline_seconds` or switch provider. |
| `criterion looks like several requirements` | One criterion bundles two testable things | Split it in `out/criteria.yaml` |

## Reliability behaviour

- **Retries:** `reliability.max_retries` attempts per provider, linear backoff.
- **Fallback:** exhausting one provider moves to the next. `fell_back` is recorded per call.
- **Deadline:** total wall clock per candidate, enforced independently of socket timeouts.
- **Batch isolation:** one unreadable or failing CV never aborts the run. Failures are collected and printed together at the end.
- **Missing assessment:** if the model omits a criterion, it becomes `unsupported` and `needs_human`, never a silent pass.

## Known limitations

0. **Free-tier throughput is the binding constraint, not the code.** Groq's free tier allows roughly 7,900 tokens per minute, and a screening costs about 2,000, so sustained throughput is **three to four candidates per minute**. A 40-candidate batch is a 10 to 15 minute job. Firing faster returns HTTP 429, which the client now waits out rather than failing, so batches get slower rather than breaking. Measured 2026-09-11 against real resumes.
1. **Worst-case latency is far above median.** Measured 25.0s median against 139.6s worst on the 12-case set. Slowest candidates are the longest CVs. There is no streaming or parallelism; 40 candidates is a coffee break, not a second.
2. **Desirable criteria are more gameable than essential ones.** Observed directly: the keyword-stuffing test case scored 1 of 4 essential but 4 of 4 desirable, because desirables are often bare tool names that a keyword list satisfies. Treat desirable counts as weak signal.
3. **Grounding proves a sentence exists, not that it is true.** A candidate who writes a false claim gets a verified quote for it. This checks the system against the CV, never the CV against reality.
4. **Injection detection is pattern-based and will miss rewordings.** Every pattern now requires an instruction rather than a topic, after a real CV was flagged for the phrase "system prompt" because the candidate's published work audits LLM system prompts. **A term on its own can never trigger a flag; only a term inside a command can.** Six regression tests in `eval/run_eval.py --guardrail` hold that line in both directions. It only ever raises a flag for a human; it never changes a verdict.
5. **One language pair tested.** A Spanish CV against an English posting worked. Nothing else was tried.
6. **No deduplication.** The same person under two filenames is screened twice.

## Changing the screening prompt

`screen.SYSTEM` is ordered by importance, and rule 1 (verbatim quotes) carries the
whole design. If you reorder or soften it, the grounding rate is the metric that
will move. Re-run the full evaluation and compare against the last
`eval/results/*.json` before shipping.
