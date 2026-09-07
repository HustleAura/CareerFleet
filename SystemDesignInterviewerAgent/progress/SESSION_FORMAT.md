# Session Format

A scored session is two files. Everything else it touches is working material
that lives outside the session folder and can be deleted at any time.

```
sessions/<session-id>/
  evaluation.json       full structured audit bundle
  card.md               generated from evaluation.json
  .work/                in-flight state, gitignored, deleted at finalize

recordings/<stem>.<ext>                 the video, gitignored
transcripts/<session-id>.txt            verbatim ASR output, gitignored
transcripts/<session-id>.frozen.txt     only when refinement changed something
```

The recording and transcript are referenced from `evaluation.json` by path and
SHA-256, never copied into the session folder. Prune them whenever you like:
`validate` treats a missing file as pruned and only complains when a file is
still present but its bytes have changed.

A transcript that the refinement pass did not change is frozen in place, so
there is never a second copy of identical text.

The session ID is the recording stem plus a timestamp, e.g.
`2026-09-06 21-30-07_2026-09-06_2222`. It is the primary key everywhere.

## Ownership

`scripts/evaluate_session.py` performs every write to a session folder,
`sessions.jsonl` and `STATE.md`. Nothing else may write them — not the
orchestrator, not a skill, not by hand. Averages, attempt numbers and the 7×5
matrix are arithmetic, and arithmetic belongs in code.

`progress/WEAKNESSES.md` is the one exception: deduping a failure mode is a
judgement call, so it stays hand-written.

## Lifecycle

```
created → transcribed → frozen → judged → adjudicating → resolved → finalized
                                             ↓
                                        needs_review (blocks finalize)
```

| Command | Effect |
|---|---|
| `init` | create the folder, hash the recording where it sits |
| `transcribe` | write `transcripts/<session-id>.txt` |
| `import --kind refinement` | store a refiner's findings |
| `freeze` | pin the transcript hash that both judges must score |
| `import --kind judgment` | validate and store a blind scorecard |
| `disputes` | emit the anonymised adjudication packet |
| `import --kind adjudication` | validate and store an adjudicator's decisions |
| `resolve` | compute the canonical result |
| `finalize` | write `evaluation.json` + `card.md`, delete `.work/` |
| `record` | append to `sessions.jsonl`, rewrite `STATE.md` |
| `validate` | re-check hashes and card/bundle agreement |
| `status` | inspection |

A finalized session is immutable. `load_state` refuses to reopen it and
`finalize` cannot run twice. Corrections go in a new session.

## Why two models

A single evaluator's scores drift with the model behind it, and the drift is not
a constant offset you can subtract out — it is case-specific and runs in both
directions, so it cannot be corrected after the fact.

So both models score the same frozen transcript independently, and disagreements
are settled by argument rather than by whichever model happened to be running.

- **Frozen input.** Each scorecard carries the transcript hash it scored.
  `import` rejects any scorecard pinned to a different hash, so the two
  evaluators provably read identical text.
- **Blind.** Neither judge sees the other's output, the rubric aside.
- **Anonymised adjudication.** Disputed dimensions are packaged as `A` and `B`
  with model identity stripped. The A/B assignment is derived from the transcript
  hash, so it is reproducible but carries no signal about who wrote which.
  An adjudicator may be re-reading its own scorecard and cannot tell.
- **Never averaged.** An adjudicator picks `A` or `B`. Both adjudicators must
  land on the same letter or the session goes to `needs_review` and finalization
  is blocked until a human settles it.
- **Narrative follows the numbers.** Strengths and verdict come from whichever
  judge the canonical scores overrode least, so the prose never contradicts the
  table beside it.

Only the canonical result reaches `progress/`. Both raw scorecards, the dispute
packet, the A/B map and every adjudication stay in `evaluation.json` under
`audit`, so any score can be traced back to the argument that produced it.

## Determinism

Routing, resolution, the matrix and the card are deterministic. **Model
judgements are not** — the same model on the same transcript may not return the
same scores twice. Before trusting a cross-model gate, measure the single-model
noise floor by scoring one case twice with one model. A gate tighter than that
floor is measuring noise.

## Standard versions

`standard_version` is stamped into every bundle so a later change to the scoring
process is visible in the record rather than silently mixed into the averages.
Every scored session is currently `v2` — the two-model panel with adjudication
described above.

Transcripts in `transcripts/` with no matching folder under `sessions/` are
unscored archive material. Score one by running the normal lifecycle over it
with `transcribe --from-file`.
