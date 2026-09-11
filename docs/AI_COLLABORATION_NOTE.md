# AI collaboration note

**Shortlist · MUST Company 5-Day Remote AI OS Sprint · Ali Murtaza Bhutto**

This is a full account of where AI was used in building this system. It is written
plainly because a partial account would be worth less than none.

## 1. Tools used, and the role of each

| Tool | Role |
|---|---|
| **Claude (Anthropic), via Claude Code** | Wrote the large majority of the Python: the schemas, provider client, ingestion, screening, grounding check, reporting, CLI, and both evaluation harnesses. Also drafted the synthetic job posting, the eighteen test CVs, and the first draft of this documentation. |
| **`openai/gpt-oss-20b` via Groq** | The screening model at runtime, and the baseline model. This is the system's own dependency, not a build tool. |
| **`openai/gpt-oss-120b` via OpenRouter** | Configured fallback provider. Served every call in `eval-20260908-165453.json`, when it was primary; it was demoted after hitting its credit ceiling, documented as failure F3. |

## 2. What was delegated

- Implementation of every module, from the data contracts through to the CLI.
- The synthetic evaluation fixtures.
- First drafts of `README.md`, `RUNBOOK.md` and the case study.

## 3. How AI output was verified

Not by reading it and finding it plausible. Plausibility is what these models are
good at, which is exactly why it is a poor check.

1. **Every module was imported and executed as it was written.** Nothing was accepted untested. `grounding.py` was exercised against real strings immediately after being written, before any of it was wired together.
2. **The whole system was run end to end against the live API**, not mocked. Twelve candidates, real HTTP, real latency and token counts. The numbers in the case study are read out of `eval/results/eval-20260908-165453.json`, not estimated.
3. **The central guardrail is tested by trying to defeat it.** Eight fabricated, paraphrased, whitespace-mangled and empty quotes are fed straight into the verifier. A clean live run showing 100% grounding was treated as **unproven, not passing**, because it is equally consistent with a check that never fires. That distinction is the reason the offline test exists.
4. **The adversarial case is asserted negatively.** For the prompt-injection CV, the test does not merely check a low score; it asserts the planted string `exceeds all requirements` appears nowhere in the output.
5. **Model behaviour is bounded by code, not by the prompt.** The prompt instructs the model to quote verbatim. The code refuses to believe it. Anything the model claims but cannot evidence is downgraded automatically.

## 4. Results rejected or corrected

**Six documented failures, dated 2026-09-11. Three are in AI-written product code,
three are in AI-written measurement code, and the second group is the important one.**

**In the product:**

- **A null message body crashed the run with `AttributeError: 'NoneType' object has no attribute 'strip'`.** The provider returned HTTP 200, `finish_reason: "length"` and `content: null`, because reasoning tokens are charged against `max_tokens`. The generated code assumed content was always a string. Corrected with an explicit guard and a message that names the cause.
- **The fallback provider was configured to a model that does not exist.** `llama-3.3-70b-versatile` returned HTTP 404 on every attempt. It had never been exercised, so a value that was wrong from the start looked correct. Corrected against the live model list; the repaired fallback then served candidate B6 for real.
- **Raising `max_tokens` to fix the first failure triggered HTTP 402** on a near-exhausted account. Resolved by reordering providers in config rather than changing code.

**In the measurement instrument, and these were rejected outright:**

- **Markdown stripping inserted a space before punctuation**, producing `"environments , deployed"` against a CV reading `"environments, deployed"`. The baseline appeared to fabricate evidence. It had not; the instrument had.
- **Only double asterisks were stripped, not single ones.** Before the fix the baseline measured **69.4% verbatim with 11 claims apparently absent**; after, **94.7% with 2**. The uncorrected number would have been **25 points wrong in the direction that flattered the system I built**, and it nearly went into the case study.
- **"Too short to verify" was being counted as "absent from the CV".** A quote of `"some Python"` was recorded as fabricated when it appears in the CV verbatim.

**Earlier in the build:**

- **An early version built the review sheet from the model's response.** If the model returned seven assessments for eight criteria, the eighth silently vanished and read as a pass. Rewritten to iterate the criteria and mark anything unreturned as `unsupported` and needing a human.
- **Fuzzy quote matching was considered and rejected.** It would have raised the grounding rate cosmetically while destroying the guarantee. Normalisation stops at whitespace and case, which are extraction artefacts; a paraphrase fails by design.
- **The first evaluation asserted exact criterion counts and was brittle**, failing on provider variation rather than real regressions. Replaced with expected bands.

## 5. Decisions I owned

- **The domain: recruiting**, chosen from the brief's list because criteria-based shortlisting has a clean structure and because its dangerous failure, showing a recruiter evidence that was never in the CV, is measurable rather than a matter of taste.
- **Grounding as the spine.** The decision that shaped everything else. It turns "is the output any good" into a number a test can enforce.
- **Building the prompt-injection case in from the start**, because CVs carrying instructions aimed at screening software are a documented tactic and a recruiter cannot catch it unaided.
- **Refusing to auto-reject.** Trivial to add, deliberately left out. A system that removes people from a process on evidence it cannot fully verify should not exist.
- **Refusing unreadable CVs loudly** rather than scoring them zero, because a silent zero is indistinguishable from a real rejection.
- **Reporting the corrected baseline rather than the flattering one.** The honest 94.7% makes a far weaker case for this system than the buggy 69.4% would have. It is the number that goes in.
- **Not claiming the system beats a human.** The manual arm was never measured, so the claim is not made anywhere in the case study.
- **Hand-checking every flagged quote against the source before believing it.** This is what caught all three instrument bugs. No test caught them.

## 6. Honest summary

**AI wrote most of the code in this repository.** What is mine is the shape of the
problem, the decision to make verification a property of the code rather than a
property of the prompt, the adversarial cases, and the insistence that a green run
proves nothing until you have tried to make it go red.

The brief asks whether the candidate can explain and modify AI-generated code. The
place to test that is `grounding.py`: eighty lines, no dependencies, and the single
point on which every quality claim in this project rests.
