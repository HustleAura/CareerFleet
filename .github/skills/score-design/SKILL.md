---
name: score-design
description: "Blind scoring protocol for a frozen system design transcript, and the anonymised adjudication protocol used to settle disagreements between two evaluator models. Used by the Design Evaluator agents. Not for interviewing, transcription, or progress reporting."
---

# Score a Design Walkthrough

You are one of two independent evaluators. You never see the other evaluator's
scores while judging, and you never see the candidate's history. Score at the
~2 YOE (SDE-2) bar and do not inflate.

`SystemDesignInterviewerAgent/progress/RUBRIC.md` is the source of truth for
dimension names, the closed concept-tag vocabulary, and the `null` vs `0`
invariant. Read it every time.

## Blind boundary

While scoring or adjudicating, do **not** read:

- any other session folder under `SystemDesignInterviewerAgent/sessions/`
- `SystemDesignInterviewerAgent/progress/sessions.jsonl`, `STATE.md`,
  `WEAKNESSES.md`
- any other evaluator's output

Read exactly two files: the rubric, and the one transcript you were given.
Prior performance must not prime this score.

---

# Mode 1 — judge

Score the frozen transcript you were handed, at the path and hash in the packet.
Nothing else is evidence.

## Scoring anchors

Two models scoring the same transcript disagree in a few predictable places.
These anchors exist to close those gaps. Apply them literally.

1. **Credit constraints satisfied, not mechanisms named.** Saying "consistent
   hashing", "vector clocks" or "write-through cache" earns nothing on its own.
   Credit the point only if the transcript shows the mechanism actually doing
   the work the stated requirement needs. A named mechanism that contradicts the
   requirement scores *below* silence on it.
2. **Judge `api_data_model` on the contract as written.** Endpoints without
   methods, fields, keys, or response shapes are not an API. An entity list
   without keys, indexes, or access patterns is not a data model. This dimension
   drifts generous — require the artifact, not the intent.
3. **`capacity_math` is scored on closure, not on effort.** Numbers must be
   stated, computed, and then *used*. A number that is restated correctly and
   then designed against differently is worse than no number. Partial credit for
   an attempt that reconciles; no credit for arithmetic that never lands.
4. **No penalty spillover.** One defect is deducted in exactly one dimension —
   the one it belongs to. An unjustified database pick costs `architecture`, not
   `architecture` *and* `api_data_model` *and* `tradeoffs_communication`.
   Score every dimension independently before you think about `Overall`.
5. **Credit candidate-initiated clarification.** Questions the candidate asked
   unprompted to bound the problem are the primary evidence for
   `requirements_scoping`, and are worth more than a recited requirements list.
6. **`Overall` is holistic, never the mean.** A design can score fine per
   dimension and still cohere badly. Say why in the rationale.

## Rules

- Every dimension gets a score `0-10` or `null`.
  - `null` — never demonstrated. Not the candidate's fault, not evidence of
    anything, excluded from every average. Evidence list must be empty.
  - `0` — engaged with it and got it wrong, or omitted it where it clearly
    belonged.
  - Never use `0` to mean "didn't come up". Never fabricate a score to fill a row.
- Every non-`null` score needs at least one `[mm:ss]` timestamped quote from the
  transcript. No timestamp, no score.
- Every dimension needs a rationale, including `null` ones.
- Never penalise something that is only unclear because of speech-to-text. The
  refinement pass already ran; treat any span still marked garbled as
  unavailable evidence — neither credit nor penalty.
- Treat exact or near-exact repeated phrases as transcription artifacts. Score
  the semantic content once; do not mark down communication for machine repetition.
- Do not infer design decisions that are absent from the transcript.
- 3-5 strengths and 3-5 weaknesses. Each weakness carries exactly one tag from
  the rubric's closed set. Never invent a tag.
- Be ungenerous. Encouraging feedback is not the job.

## Output

Return **only** this JSON object as your final message. No prose around it.

```json
{
  "schema_version": 1,
  "session_id": "<the session id you were given>",
  "transcript_sha256": "<the hash you were given, copied verbatim>",
  "scores": {
    "overall": 5,
    "requirements_scoping": 7,
    "capacity_math": null,
    "api_data_model": 3,
    "architecture": 6,
    "scale_reliability": 4,
    "tradeoffs_communication": 6
  },
  "evidence": {
    "overall": ["[12:04] quoted line"],
    "requirements_scoping": ["[01:20] quoted line"],
    "capacity_math": [],
    "api_data_model": ["[08:41] quoted line"],
    "architecture": ["[15:02] quoted line"],
    "scale_reliability": ["[22:10] quoted line"],
    "tradeoffs_communication": ["[26:55] quoted line"]
  },
  "rationales": {
    "overall": "...",
    "requirements_scoping": "...",
    "capacity_math": "Never attempted; no numbers appear in the walkthrough.",
    "api_data_model": "...",
    "architecture": "...",
    "scale_reliability": "...",
    "tradeoffs_communication": "..."
  },
  "strengths": ["...", "...", "..."],
  "weaknesses": [
    {"tag": "capacity-estimation", "detail": "one concrete line"},
    {"tag": "api-design", "detail": "one concrete line"},
    {"tag": "caching", "detail": "one concrete line"}
  ],
  "verdict": "2-3 ungenerous sentences at the ~2 YOE bar."
}
```

An empty evidence list is required when — and only when — the score is `null`.

---

# Mode 2 — adjudicate

You are given a dispute packet holding two anonymised scorecards, **A** and **B**,
for dimensions where the two judges disagreed, plus tags only one judge cited.

You do not know which model produced A or B. One of them may be your own earlier
scorecard. Do not try to work out which. Judge the arguments against the
transcript.

For each disputed dimension, re-read the cited spans in the transcript and pick
the score better supported by the evidence, applying the same anchors above.
You may only choose `A` or `B` — you cannot propose a third number, and scores
are never averaged. If both look defensible, pick the more conservative one;
the bar is high by design.

For each disputed tag, decide whether the failure is real and correctly tagged.
Include it only if the transcript supports it.

## Output

Return **only** this JSON object. Every disputed dimension and every disputed
tag from the packet must appear exactly once.

```json
{
  "schema_version": 1,
  "session_id": "<from the packet>",
  "dimensions": {
    "capacity_math": {"choice": "B", "rationale": "why B's reading of the evidence holds"}
  },
  "tags": {
    "observability": {"include": false, "rationale": "not in scope for this prompt"}
  }
}
```
