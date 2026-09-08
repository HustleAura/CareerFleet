---
name: test-agents
description: "Use for 'test agents', 'Run CareerFleet agent tests', or 'test the evaluation pipeline'. Evaluate the latest design recording end to end using skills, label outputs as tests, and remove test artifacts afterward without changing real progress."
---

# Live Evaluation Test

Run a real end-to-end system-design evaluation of the latest recording. The
current interviewer performs every step itself using the selected model and
the existing skills. No subagents, offline suite, fixtures, mock judgments,
model pins, or persisted workflow states. This tests the design pipeline, not
resume tailoring. Creating or editing this skill does not itself start a test.

## Isolate and Label

1. Select the newest supported media file by modification time from
	`SystemDesignInterviewerAgent/recordings/`, as `transcribe.py` does by default.
	Report the selected filename. If no recording exists, report the blocker;
	do not substitute an old transcript. Treat the original media as read-only.
2. Create a unique temporary directory with `mktemp -d` and a `test-careerfleet-`
	prefix. Keep its exact absolute path in the conversation for cleanup, not in
	a state file. Use a unique `test-<recording-stem>-<timestamp>` evaluation ID.
	Prefix user-visible headings with `TEST` and all generated transcript,
	submission, and session names with `test-`.
3. Under that directory create `SystemDesignInterviewerAgent/scripts/`,
	`transcripts/`, `sessions/`, and `progress/`. Copy only the production
	`scripts/progress.py`, `progress/RUBRIC.md`, and `progress/SESSION_FORMAT.md`
	into matching locations. Initialize an empty `progress/sessions.jsonl`, a
	minimal `progress/STATE.md` headed `# Test Progress`, and a
	`progress/WEAKNESSES.md` with empty Active and Resolved tables using the
	production columns. Do not copy real scores, weakness history, or sessions.

The following skills still define behavior. For this test only, redirect all
generated transcripts, accepted evaluations, cards, and progress writes to the
temporary project. Read production skills, rubric, and scripts as needed, but
never run the production progress helper against a test submission. Its copied
script derives its project root from its own location, keeping writes isolated.

## Exercise the Whole Workflow

1. Load `.github/skills/transcribe-session/SKILL.md`. Run the production wrapper
	from the real workspace root with the selected recording's absolute path and
	an explicit temporary output path:

	```bash
	bash SystemDesignInterviewerAgent/scripts/transcribe.sh "<original-recording>" --out "<test-root>/SystemDesignInterviewerAgent/transcripts/<test-id>.raw.txt"
	```

	Use the existing ASR environment and models. Do not reuse an earlier
	transcript: this test must exercise transcription. Read and show the raw
	text. Report missing tools honestly; never fabricate successful transcription.
2. Infer the problem from the transcript and reuse known difficulty; ask if it
	is missing. Use the recording date for the attempt. Keep `test-` in the ID,
	not the inferred problem name or rubric vocabulary.
3. Load `.github/skills/refine-evidence/SKILL.md`. Inspect all text, present
	exact timestamped questions, and wait for actual user answers. A test request
	does not authorize invented clarifications. If clean, state that explicitly;
	do not manufacture a question to claim coverage. Preserve raw test text and
	write any corrected final text only within the temporary transcripts folder.
4. Load `.github/skills/score-design/SKILL.md`. Score the final clarified text,
	retaining unavailable/repetition notes and excluding later design additions.
	Present all seven scores with evidence and rationale, strengths, tagged
	weaknesses, and verdict under a `TEST Evaluation` heading.
5. Ask for explicit acceptance of the test evaluation before recording it.
	Wait normally while clarification or acceptance is pending; do not call an
	incomplete run successful or remove files still needed for that conversation.
6. After acceptance, load `.github/skills/track-progress/SKILL.md` in WRITE mode
	with all output paths redirected to the temporary project. Serialize the
	accepted result outside its session folder but inside the test root. Use
	temporary-project-relative raw/final transcript paths; omit the optional
	recording_path rather than copying the recording or using an escaping path.
	Note the original source filename and test-only purpose in evidence notes.
7. Run the copied helper with absolute paths:

	```bash
	python3 "<test-root>/SystemDesignInterviewerAgent/scripts/progress.py" record "<test-root>/<test-id>-evaluation.json"
	python3 "<test-root>/SystemDesignInterviewerAgent/scripts/progress.py" validate "<test-root>/SystemDesignInterviewerAgent/sessions/<test-id>/evaluation.json"
	```

	Reconcile the temporary weakness ledger using the skill. Check the card,
	one ledger row, all matrix cells, null handling, and weakness entries. Repeat
	recording the identical submission and reconciliation once: it must not add
	another attempt or weakness hit. Validate again. This is real output checking,
	not fabricated expected scores or an automated unit-test suite.

## Report and Clean Up

Before deleting outputs, summarize the selected recording, test scores, stages
actually exercised, clarification outcome, acceptance, progress validation,
and repeat-record result in chat. State any unexercised branch, such as no
correction being necessary. Successful commands alone do not prove judgment
quality. Never claim PASS if required steps were skipped or failed.

After completion, cancellation, or a terminal failure, remove the exact temporary
directory created for this run, including submissions, transcripts, cards,
copied scripts, and temporary progress. First verify it is the run-owned
`test-careerfleet-*` directory under the system temporary location, not a
workspace, recording, or user-supplied directory. Do not use broad test-name
globs or delete any original media, production transcript, real progress,
preexisting temporary directory, environment, or model. Confirm the directory
no longer exists and report cleanup in chat. Keep no on-disk test report.

If interrupted before cleanup, use the exact directory already identified in
the conversation on resumption; do not guess paths. If cleanup fails, report
the remaining path and blocker rather than claiming all artifacts were removed.