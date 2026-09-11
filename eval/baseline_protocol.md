# Protocol for the unmeasured baseline arm

Two baselines are possible for this system. One was measured and one was not.

**Measured:** plain chatbot use, one prompt with the posting and the CV pasted in,
free text back, nothing verified. Run it with `eval/baseline_plain_llm.py`. Results
are in `eval/results/`.

**Not measured:** a person doing the same work by hand, timed. This document is the
procedure for that arm, recorded so the gap is reproducible rather than merely
acknowledged.

## Why it was not run

A manual baseline is only valid if the person performing it has not already seen the
system's output for the same candidates. By the time the comparison was designed,
that condition no longer held for the twelve CVs in `samples/cvs/`. The six in
`samples/baseline_cvs/` were written afterwards specifically to preserve it, and were
used for the automated comparison instead.

## Procedure, if run

Use `samples/baseline_cvs/` (B1 to B6). Do not read any system output for those six
first.

1. From `samples/job_posting.txt`, write out the essential and desirable criteria by
   hand. Record the time taken.
2. For each CV, start a timer and produce what the system produces: for every
   criterion a verdict of met, partial or not met, **and the sentence from the CV
   that supports it**. Record minutes per candidate.
3. Record, per candidate, whether a supporting quote was written for every "met"
   verdict or whether some rested on impression.
4. After all six, write down the criteria from memory without re-reading them, and
   compare against step 1. Any divergence is criteria drift, which is the failure
   the system is built to remove.
5. Only then run the system over the same folder:

```bash
cd src
python3 -m shortlist.cli screen --criteria out/criteria.yaml --cvs ../samples/baseline_cvs
```

## Metrics to record

| Candidate | Minutes | Essential met | Criteria evidenced with a quote |
|---|---|---|---|
| B1 | | | |
| B2 | | | |
| B3 | | | |
| B4 | | | |
| B5 | | | |
| B6 | | | |

Plus: median minutes per candidate, and whether the criteria written in step 4
matched those in step 1.

## What it would settle

The automated comparison in the case study shows the system checks evidence that
plain chatbot use does not. It says nothing about speed or consistency relative to a
human, and no such claim is made anywhere in this repository. This protocol is what
would support one.
