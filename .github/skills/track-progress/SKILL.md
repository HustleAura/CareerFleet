---
name: track-progress
description: "Use in two situations. WRITE: after a system design session has been finalized and the user has accepted the evaluation, record it into SystemDesignInterviewerAgent/progress/. READ: when the user asks how they are doing — trigger phrases: 'how am I doing', 'progress report', 'show my progress', 'what are my weaknesses', 'am I improving', 'my scores so far'. Reads and maintains SystemDesignInterviewerAgent/progress/STATE.md, WEAKNESSES.md, sessions.jsonl and the session folders under SystemDesignInterviewerAgent/sessions/."
---

# Track Progress

Persistent memory for the design interview loop. Two modes — pick one.

`RUBRIC.md` is the source of truth for dimension names, concept tags, and
difficulty rungs. Read it before writing anything. Never invent a tag.

Each session's card and audit bundle live in
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

# WRITE mode — record a finalized session

Only after the user has seen and accepted the evaluation, and the session has
been finalized. Never record a session that is still being clarified.

The card, `sessions.jsonl` and the `STATE.md` matrix are **generated**, not
written by hand — averages and attempt counts are arithmetic, and hand-computing
them is how a ledger drifts. Only `WEAKNESSES.md` needs judgement.

## 1. Generate the card and the audit bundle

```bash
python3 SystemDesignInterviewerAgent/scripts/evaluate_session.py finalize "<session-id>"
```

Writes `SystemDesignInterviewerAgent/sessions/<session-id>/card.md` and
`evaluation.json` from the canonical
scores, then deletes `.work/`. The card is immutable and is never edited — it is
regenerable from `evaluation.json`, and `validate` fails if the two ever diverge.
A correction goes in a new session, never in an old card.

## 2. Append to the ledger and rebuild the matrix

```bash
python3 SystemDesignInterviewerAgent/scripts/evaluate_session.py record "<session-id>"
```

Appends one line to `SystemDesignInterviewerAgent/progress/sessions.jsonl` and
rewrites `SystemDesignInterviewerAgent/progress/STATE.md`
in full — sessions completed, last 5 overall, and all 35 matrix cells recomputed
from the ledger, so the file self-heals if a cell ever drifted. `null` entries
are excluded from both numerator and `n`; a cell with no scored sessions stays
`null`, never `0` and never blank.

Both commands refuse to run twice. If either reports the session is already
recorded, stop — do not force it.

## 3. Update `SystemDesignInterviewerAgent/progress/WEAKNESSES.md` by hand

This is the only progress file you write yourself, because deduping a failure
mode is a judgement call. The command prints the canonical tags to apply.

For each tag:

- **Tag already has a row** — increment `hits`, set `last seen` to this date,
  append the session ID to `Sessions`. Only open a second row under the same
  tag if the failure mode is genuinely distinct from the existing one.
- **New tag** — add a row: `hits` 1, `first seen` and `last seen` both today,
  status `open`.
- **Tag not flagged this session, but the concept was clearly exercised** —
  consider `open` → `improving`, or `improving` → `resolved` after two
  consecutive clean sessions. If the concept never came up, change nothing.
- **A `resolved` row reappears** — flip back to `open`, move it from the
  **Resolved** table to **Active**, and keep incrementing.

Never delete a row. Remove the `_none recorded yet_` placeholder on first write.

## 4. Verify

```bash
python3 SystemDesignInterviewerAgent/scripts/evaluate_session.py validate "<session-id>"
```

Confirms any retained transcript or recording still hashes to what was scored,
that the card matches `evaluation.json`, and that no `.work/` state was left
behind. Missing media is treated as deliberately pruned.

## Non-goals

The memory is **write-only for now**: it records, but nothing reads it back to
change how sessions run. Do not use this history to pick the next problem,
adjust difficulty, calibrate scores, or steer questioning. Every session is
scored on its own merits, as if it were the first.

Repeated attempts at the same problem are deliberate practice, not regression.
Never penalise them. This restriction lifts only when the user asks for it.
