---
name: score-design
description: "Use after transcript refinement and user clarification to score the final design walkthrough against the rubric. The interviewer evaluates directly and presents evidence before asking for acceptance."
---

# Score the Final Transcript

Perform this skill yourself using the selected model. Read the complete final
clarified transcript and `SystemDesignInterviewerAgent/progress/RUBRIC.md`.
Confirm required clarification is complete before scoring. This is a single
same-context judgment, not blind or independently replicated evaluation.

Do not read other session evaluations, `sessions.jsonl`, `STATE.md`, or
`WEAKNESSES.md` to calibrate scores. Use only the candidate's final transcript
as design evidence, with clarification/exclusion notes identifying unavailable
material. Do not score explanations or improvements added after recording.

## Anchors

1. Credit constraints satisfied, not mechanisms named. A mechanism that
   contradicts its requirement does not earn credit for being mentioned.
2. Judge `api_data_model` on actual methods, fields, keys, response shapes and
   access patterns. Intent and entity lists are not complete contracts.
3. Judge `capacity_math` on closure: quantities must be computed and used in
   the design. Reward reconciled reasoning, not effort that never lands.
4. Avoid penalty spillover. Assign a defect to its owning dimension, not every
   related dimension. Judge each dimension on its own evidence.
5. Credit candidate-initiated clarification more than reciting requirements.
6. `overall` is holistic at the ~2 YOE (SDE-2) bar, never a numeric average.
   Explain whether the design coheres. Be candid; do not inflate scores.

## Output

Give all seven dimensions, scores, evidence and rationales using the stable keys:
`overall`, `requirements_scoping`, `capacity_math`, `api_data_model`,
`architecture`, `scale_reliability`, `tradeoffs_communication`.

- Each score is an integer 0-10 or `null`.
- `null` means not demonstrated and is excluded from averages. Its evidence
  list is empty. Never fill an unmentioned topic with zero.
- `0` means wrong engagement or an omission where clearly required by the rubric.
- Every non-null score needs a verbatim `[mm:ss] quote` from that timestamp's
  final transcript segment. Ignore whitespace only when matching. Do not
  paraphrase, silently correct, or splice segments. No valid evidence, no score.
- Every dimension needs a rationale, including null ones.
- Unavailable speech earns neither credit nor penalty. Score machine repetition
  semantically once; do not penalize delivery for ASR loops.
- Include 3-5 strengths and 3-5 concrete weaknesses, each weakness with one tag
  from the rubric's closed vocabulary. Never invent weaknesses just to fill a
  quota; flag insufficient evidence and discuss it instead of fabricating scores.
- Finish with a concise verdict and the most important improvement to practice.

Present the complete evaluation to the user in readable Markdown. No worker
envelope or JSON response protocol is needed. Check quoted evidence against
the final text before presenting; formatting mistakes can be corrected normally.

Ask for explicit acceptance of the result before recording progress. If the
user disputes a score, examine the cited evidence and explain or revise the
judgment, then obtain acceptance of the revised result. Keep candidate corrections
to actual speech separate from new design ideas.

After acceptance, use `.github/skills/track-progress/SKILL.md` to serialize the
final evaluation in the simple format described by
`SystemDesignInterviewerAgent/progress/SESSION_FORMAT.md`. JSON here is only
final-output storage for progress, not evaluation orchestration.
