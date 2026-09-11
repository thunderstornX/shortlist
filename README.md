# Shortlist

**Screen job applicants against a role's criteria, with evidence you can check.**

For every candidate you get one review sheet: each requirement of the job marked
met, partial or not met, and next to it **the exact sentence from that person's CV
that supports it**. If the system cannot find a real sentence to back a claim, it
says so and asks you to look, rather than guessing.

You do not need to be a developer to use it.

---

## What it is for

You have a job posting and a folder of CVs. You need to know who to interview, and
you need to be able to say why. Doing that by hand is slow, and by candidate thirty
you are not applying the same standard you applied to candidate one.

Shortlist reads the posting, agrees the criteria with you, then works through every
CV applying those same criteria in the same order, and shows its evidence.

**It does not decide anything.** It produces evidence and a recommendation. The
decision is yours, and anything it is unsure about is handed to you explicitly.

## Setup, three steps

You need Python 3.10 or newer.

**1. Install**

```bash
pip install -r requirements.txt
```

**2. Add one API key**

```bash
cp .env.example .env
```

Open `.env` and paste in one key. A free key from
[openrouter.ai/keys](https://openrouter.ai/keys) or
[console.groq.com/keys](https://console.groq.com/keys) is enough.

**3. Copy the settings file**

```bash
cp config/config.example.yaml config/config.yaml
```

Done. Nothing else to configure.

## Using it

### Step 1: agree the criteria

```bash
cd src
python3 -m shortlist.cli criteria --job ../samples/job_posting.txt
```

You can pass a web address instead of a file:

```bash
python3 -m shortlist.cli criteria --job https://example.com/jobs/1234
```

This writes **`out/criteria.md`**. **Read it.** It lists what the system understood
to be the essential and desirable requirements.

If anything is wrong, edit **`out/criteria.yaml`**: change the wording, move a row
between essential and desirable, or delete it. Everything that follows is judged
against this list, so a mistake here quietly affects every candidate.

### Step 2: screen the candidates

Put the CVs in a folder (PDF, TXT or MD), then:

```bash
python3 -m shortlist.cli screen --criteria out/criteria.yaml --cvs ../samples/cvs
```

You get, in `out/`:

- **`ranking.csv`** open in Excel. Best first, with how many essential criteria each person met.
- **`<name>.md`** one review sheet per candidate, with the quoted evidence.

## Reading a review sheet

Each requirement shows one of four results.

| What it says | What it means |
|---|---|
| **MET** | The CV contains a sentence that supports this, and that sentence was found in the CV. |
| **PARTIAL** | Related or lesser experience than asked for. Worth your eye. |
| **NOT MET** | Nothing in the CV supports it. |
| **NEEDS CHECK** | The system made a claim it could not back with a real sentence from the CV. **Never act on this without reading the CV yourself.** |

Every quote is checked automatically against the CV text. A quote the system could
not find is marked *NOT found in the CV*.

## Where you must get involved

Three points, by design.

1. **Approving the criteria**, before any screening happens.
2. **Anything marked NEEDS CHECK**, or where the system's confidence was low.
3. **Any candidate carrying a flag.** The most important flag is when a CV contains
   text written to influence the screening software rather than to describe a career.
   That happens, and it is a decision for a person.

## What it will not do

- It will not reject anyone. It recommends; you decide.
- It will not read a scanned or photographed CV. Those have no text to extract, so
  the system **refuses to screen them and tells you the filename**. That is not a
  rejection. Run OCR or ask for a text version.
- It will not judge anything the CV does not say. If someone's experience is real
  but unwritten, no tool can see it.
- It does not look anyone up online. Only the CV you supply.

## Privacy

CVs are sent to whichever model provider you configured, and to nobody else. The
run logs record what happened, not what was in the CV: email addresses and phone
numbers are stripped, and the CV text itself is never written to the log unless you
switch that on in `config.yaml`. Your API key lives only in `.env`, which is never
committed.

## If something goes wrong

See **`RUNBOOK.md`**, which lists the errors you might see and what each one means.
