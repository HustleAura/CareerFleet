---
name: track-progress
description: "Use after explicit acceptance to save a design evaluation and update all progress tracking. Also use for 'how am I doing', 'progress report', 'show my progress', 'what are my weaknesses', 'am I improving', or 'my scores so far'."
---

# Track Progress

Persistent memory for the design interview loop. Two modes — pick one.

`RUBRIC.md` is the source of truth for dimension names, concept tags, and
difficulty rungs. Read it before writing anything. Never invent a tag.

Each accepted evaluation and its generated card live in
`SystemDesignInterviewerAgent/sessions/<session-id>/`.
`SystemDesignInterviewerAgent/progress/` holds only the cross-session
aggregates. All paths below are relative to the workspace root, and every
command is run from the workspace root.

## The null invariant

Applies everywhere in this skill, in both modes.

- `null` — not demonstrated. Excluded from every average and denominator.
- `0` — attempted and failed.

Never write `0` for something that didn't come up. Never omit a row to mean
`null` — every row always exists, `null` is a value.

---

# READ mode — progress report

Read **only** `SystemDesignInterviewerAgent/progress/STATE.md` and
`SystemDesignInterviewerAgent/progress/WEAKNESSES.md`.

Do not glob `SystemDesignInterviewerAgent/sessions/` and do not read
`sessions.jsonl`. Those are Tier 3 —
open a session card only if the user names a specific session. This is what
keeps reports cheap as sessions pile up.

Report, in this order:

1. **Where things stand** — sessions completed and the last 5 overall scores.
   If there are no sessions, say so plainly and stop.
2. **Read the matrix down a column** — for each rung actually attempted, name
   the strongest and weakest dimension at that rung. Say "not yet attempted"
   for a `null` cell; never silently skip one. An empty `architect` column is
   information.
3. **Read the matrix across a row** — where a dimension has scores at more than
   one rung, say whether it holds up as difficulty rises. A dimension that is
   `7 (3)` at easy and `3 (1)` at medium is the single most useful thing the
   matrix can tell them.
4. **Watch the `n`** — a cell at `8.0 (1)` is one lucky session, not a skill.
   Say so. Never treat a low-`n` cell as established.
5. **Top open weaknesses** — from `WEAKNESSES.md`, with hit counts. A weakness
   at 3 hits is a different conversation than one at 1. The matrix says how
   good; the ledger says at what specifically. Use both.
6. **Next focus** — one concrete recommendation, derived live. Name the concept
   and why.

Derive anything else you need rather than expecting a stored field. Averaging
across a row is fine for a comment; never write a blended cross-rung number
back into the file.

Do not propose a specific problem to attempt. That is deliberately out of scope
for now.

---

# WRITE mode — record an accepted evaluation

Only after the user has seen and explicitly accepted the evaluation. The
interviewer handles this gate in the conversation; no approval payload or
workflow command is required. Never record while clarification is pending.

The card, `sessions.jsonl` and the `STATE.md` matrix are **generated**, not
written by hand — averages and attempt counts are arithmetic, and hand-computing
them is how a ledger drifts. Only `WEAKNESSES.md` needs judgement.

## 1. Save the accepted evaluation and rebuild progress

Serialize the exact accepted result using
`SystemDesignInterviewerAgent/progress/SESSION_FORMAT.md` into a scratch JSON
file outside the final session directory. Include actual clarification answers,
unavailable/repetition spans and excluded additions in its evidence notes. Use
the attempt date, supplied difficulty and problem, not today's date by default.
Do not invent scores, acceptance, or candidate statements.

```bash
python3 SystemDesignInterviewerAgent/scripts/progress.py record "/tmp/<id>-evaluation.json"
```

Saves `sessions/<id>/evaluation.json`, derives `card.md`, appends one line to
`SystemDesignInterviewerAgent/progress/sessions.jsonl` and
rewrites `SystemDesignInterviewerAgent/progress/STATE.md`
in full — sessions completed, last 5 overall, and all 35 matrix cells recomputed
from the ledger, so the file self-heals if a cell ever drifted. `null` entries
are excluded from both numerator and `n`; a cell with no scored sessions stays
`null`, never `0` and never blank.

Identical retries do not duplicate ledger entries or attempt counts and can
repair derived outputs. Conflicting same-ID evaluations are rejected. Correct
formatting errors normally; never change the accepted judgment to satisfy a
validator. Do not hand-edit generated output. A new accepted evaluation uses
a new ID; preserve prior evaluations and evaluation-method labels.

## 2. Update `SystemDesignInterviewerAgent/progress/WEAKNESSES.md` by hand

This is the only progress file you write yourself, because deduping a failure
mode is a judgement call. The command prints the canonical tags to apply.

For each tag:

- **Session already applied to this row** — leave hits and history unchanged.
   Reconcile missing rows only; do not replay transitions on an identical retry.
- **Tag already has a row** — increment `hits`, set `last seen` to this date,
  append the session ID to `Sessions`. Only open a second row under the same
  tag if the failure mode is genuinely distinct from the existing one.
- **New tag** — add a row: `hits` 1, `first seen` and `last seen` both the attempt date,
  status `open`.
- **Tag not flagged this session, but the concept was clearly exercised** —
  consider `open` → `improving`, or `improving` → `resolved` after two
  consecutive clean sessions. If the concept never came up, change nothing.
- **A `resolved` row reappears** — flip back to `open`, move it from the
  **Resolved** table to **Active**, and keep incrementing.

Never delete a row. Remove the `_none recorded yet_` placeholder on first write.

For clean exercises, record the session ID in the row's history/notes when
changing status, so rerunning cannot count the same evidence twice. Reconcile
backdated evaluations chronologically; never move last-seen dates backwards.

## 3. Verify

```bash
python3 SystemDesignInterviewerAgent/scripts/progress.py validate "SystemDesignInterviewerAgent/sessions/<id>/evaluation.json"
```

Confirms the evaluation's scores and tags, cited excerpts when final text is
retained, and agreement with the generated card, ledger and matrix. Missing
historical media is allowed. This does not prove that conversational gates ran.

## Non-goals

The memory is **write-only for now**: it records, but nothing reads it back to
change how sessions run. Do not use this history to pick the next problem,
adjust difficulty, calibrate scores, or steer questioning. Every session is
scored on its own merits, as if it were the first.

Repeated attempts at the same problem are deliberate practice, not regression.
Never penalise them. This restriction lifts only when the user asks for it.
