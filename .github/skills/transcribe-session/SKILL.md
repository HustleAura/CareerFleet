---
name: transcribe-session
description: "Use when the user has recorded a system design walkthrough video and wants it transcribed and/or evaluated. Trigger phrases: 'transcribe my recording', 'evaluate my video', 'I finished my walkthrough', 'score my design session', 'here's my recording'. Starts the session workflow that transcribes, refines and freezes the transcript before any scoring."
---

# Transcribe a Design Session

Turn a recorded walkthrough into the frozen transcript that the evaluator panel
scores. **Never skip to scoring.**

Everything durable for a session lives in one folder,
`SystemDesignInterviewerAgent/sessions/<session-id>/`, and
`SystemDesignInterviewerAgent/scripts/evaluate_session.py` owns every write to
it. Do not create or move files there by hand. The recording stays in
`SystemDesignInterviewerAgent/recordings/` and the transcript in
`SystemDesignInterviewerAgent/transcripts/` — both are working material,
gitignored, and pruned by the user.

All paths below are relative to the workspace root, and every command is run
from the workspace root.

## 1. Create the session

The session ID follows the existing convention: the recording stem plus a
timestamp, e.g. `2026-09-06 21-30-07_2026-09-06_2222`.

```bash
python3 SystemDesignInterviewerAgent/scripts/evaluate_session.py init "<session-id>" \
  --problem "<name>" --difficulty <basic|easy|medium|hard|architect> \
  --recording "SystemDesignInterviewerAgent/recordings/<file>"
```

The recording is hashed where it sits. It is never moved, copied or committed.

## 2. Transcribe

```bash
python3 SystemDesignInterviewerAgent/scripts/evaluate_session.py transcribe "<session-id>"
```

Writes `SystemDesignInterviewerAgent/transcripts/<session-id>.txt` with `[mm:ss]`
line prefixes.
The first run downloads ~3GB of whisper.cpp weights; a 30-minute recording takes
several minutes.

If there is no recording, import existing text instead:
`transcribe "<session-id>" --from-file <path>`.

## 3. Show the raw transcript

Read it and show it to the user. Do not evaluate yet.

## 4. Refinement pass

Dispatch **both** `Transcript Refiner (GPT)` and `Transcript Refiner (Opus)` on
`SystemDesignInterviewerAgent/transcripts/<session-id>.txt`. They follow
`.github/skills/refine-evidence/SKILL.md` and
return JSON. Two refiners run because a corruption one model reads past is
usually caught by the other.

Save each result under
`SystemDesignInterviewerAgent/sessions/<session-id>/.work/` and import it:

```bash
python3 SystemDesignInterviewerAgent/scripts/evaluate_session.py import "<session-id>" \
  --kind refinement --model opus \
  --file "SystemDesignInterviewerAgent/sessions/<session-id>/.work/refine-opus.json"
```

Merge both lists, drop duplicates, and ask the candidate every question in **one
batched list** — not one at a time. If both refiners report `clean`, say so and
move on.

## 5. Freeze

Fold the answers into a corrected copy and freeze it:

```bash
python3 SystemDesignInterviewerAgent/scripts/evaluate_session.py freeze "<session-id>" \
  --corrected "SystemDesignInterviewerAgent/sessions/<session-id>/.work/corrected.txt" \
  --clarifications "SystemDesignInterviewerAgent/sessions/<session-id>/.work/clarifications.json"
```

The frozen transcript and its hash are now immutable. Both evaluators are pinned
to that exact hash, so neither can score a different text. Corrections land in
`SystemDesignInterviewerAgent/transcripts/<session-id>.frozen.txt`, leaving the
verbatim ASR record intact
beside it. With no corrections the original file is frozen in place.

Hand off to the `Design Evaluator` agents next.

### Guardrail

Clarification is **not** a second attempt at the design. Only ask about content
already present in the transcript. If the user introduces a design decision that
was not in the recording, acknowledge it, pass it to `freeze --excluded`, and
say plainly that it was not part of the original walkthrough. Score what was
recorded.
