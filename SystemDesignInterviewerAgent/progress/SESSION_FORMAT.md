# Accepted Evaluation Format

The interviewer manages transcription, refinement, clarification, judgment,
and acceptance in the conversation. Only accepted results are stored here:

```text
sessions/<session-id>/evaluation.json   accepted evaluation
sessions/<session-id>/card.md           generated readable evaluation
progress/sessions.jsonl                one summary per accepted evaluation
progress/STATE.md                      generated proficiency matrix
progress/WEAKNESSES.md                 agent-maintained weakness history
```

Raw and corrected transcripts stay under `transcripts/`; recordings stay under
`recordings/`. They are not copied into the final evaluation directory. No
workflow states, round packets, worker outputs, cryptographic bindings, or
approval objects are stored. The agent is responsible for actual user acceptance.

## Evaluation Object

Use exactly these fields, plus optional `recording_path`:

```json
{
  "session_id": "<recording stem plus evaluation timestamp>",
  "date": "2026-09-06",
  "problem": "Key-value store",
  "difficulty": "basic",
  "standard_version": "single-agent-v1",
  "raw_transcript_path": "transcripts/<raw>.txt",
  "transcript_path": "transcripts/<final>.txt",
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
    "overall": ["[12:04] exact excerpt"],
    "requirements_scoping": ["[01:20] exact excerpt"],
    "capacity_math": [],
    "api_data_model": ["[08:41] exact excerpt"],
    "architecture": ["[15:02] exact excerpt"],
    "scale_reliability": ["[22:10] exact excerpt"],
    "tradeoffs_communication": ["[26:55] exact excerpt"]
  },
  "rationales": {
    "overall": "Explain coherence at the interview bar.",
    "requirements_scoping": "Explain the evidence.",
    "capacity_math": "Not demonstrated.",
    "api_data_model": "Explain the evidence.",
    "architecture": "Explain the evidence.",
    "scale_reliability": "Explain the evidence.",
    "tradeoffs_communication": "Explain the evidence."
  },
  "strengths": ["Specific strength", "Specific strength", "Specific strength"],
  "weaknesses": [
    {"tag": "api-design", "detail": "Specific failure mode"},
    {"tag": "caching", "detail": "Specific failure mode"},
    {"tag": "replication-consistency", "detail": "Specific failure mode"}
  ],
  "verdict": "Concise evidence-grounded assessment.",
  "notes": ["Actual clarification answers and excluded or unavailable spans, if any."]
}
```

Replace illustrative scores and quotes with actual accepted findings. The date
is the attempt/recording date. Paths are relative to `SystemDesignInterviewerAgent/`;
raw and final paths may be identical when no correction was needed. `notes` may
be empty. `standard_version` identifies the evaluation method, not a model name.
Older progress rows retain their method. Overall is holistic; all seven
dimensions always exist. Null scores require empty evidence; non-null scores
require exact timestamped excerpts. RUBRIC.md defines difficulties and tags.

## Record and Validate

After explicit user acceptance, create a JSON submission outside the final
session directory (for example `/tmp/<id>-evaluation.json`), then run from the
workspace root:

```bash
python3 SystemDesignInterviewerAgent/scripts/progress.py record "/tmp/<id>-evaluation.json"
python3 SystemDesignInterviewerAgent/scripts/progress.py validate "SystemDesignInterviewerAgent/sessions/<id>/evaluation.json"
```

`record` validates and saves the final evaluation, derives the card, appends a
ledger row once, and recomputes aggregates. Then reconcile WEAKNESSES.md using
the track-progress skill. Same-ID identical resubmissions repair derived output
without duplicating attempts; differing data for an existing ID is rejected.
Use a new ID for a genuinely new accepted evaluation, never edit a recorded
evaluation or card. A repeated evaluation is another evaluation, not evidence
of improvement merely because its score changed.

`validate` checks evaluation structure and agreement with the card, ledger, and
matrix. Retained final transcripts are checked for cited excerpts. A missing
transcript is permitted for historical validation and identical recorded retries,
but a new ledger entry requires the final transcript. Without hashes this is not
tamper detection, proof of user acceptance, or proof the conversational gates ran.
Do not prune evidence until its evaluation has been recorded successfully.

Writes replace individual files atomically; run recording commands serially.
An interrupted write can be completed with the same submission. No resumable
evaluation pipeline or migration of old workflow artifacts is provided.
