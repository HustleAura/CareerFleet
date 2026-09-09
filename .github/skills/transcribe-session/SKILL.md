---
name: transcribe-session
description: "Use when the user asks to transcribe a recording, evaluate a video, or score a recorded design walkthrough. Obtain and show raw text, then continue to refinement before any scoring."
---

# Transcribe a Design Walkthrough

The current System Design Interviewer performs this skill itself. Run commands
from the workspace root. No session initialization or worker dispatch is needed.

1. Identify the requested recording under
   `SystemDesignInterviewerAgent/recordings/`. If multiple files are plausible,
   clarify which recordings were requested. Reuse the corresponding existing raw
   transcript when available and appropriate; do not assume unrelated timestamps
   identify the same recording. Preserve existing raw text.
2. For a new transcription, run the existing wrapper with an explicit path:

   ```bash
   bash SystemDesignInterviewerAgent/scripts/transcribe.sh "SystemDesignInterviewerAgent/recordings/<file>"
   ```

   The wrapper uses the project virtual environment, ffmpeg, whisper.cpp, and
   local models. Report missing prerequisites honestly. Do not substitute invented
   text. The script prints the new timestamped transcript path.
3. Read the complete raw transcript and show it via a clickable link with its
   opening excerpt. Offer the full text in chat when requested. Existing text
   without a recording can be used directly; no import or copy command is needed.
4. Identify the problem from the text when possible. Reuse the user's difficulty;
   ask only if missing. Use the recording stem plus an evaluation timestamp for
   a new evaluation ID, and the recording's date for the attempt date.
5. Continue with `.github/skills/refine-evidence/SKILL.md`. Never score raw text
   before checking transcription quality and resolving required clarifications.

Recordings and transcripts are working material, not workflow state. Keep them
available through scoring and initial progress recording. Do not delete them
unless the user requests cleanup.
