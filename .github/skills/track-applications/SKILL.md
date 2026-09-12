---
name: track-applications
description: "Use for 'I applied to', 'mark as applied', 'add these applied jobs to the tracker', or 'show applied jobs'. Record only user-confirmed applications in the company,jobid,title CSV. No new job fetching, tailoring or applications; verify rows before deleting the current session's temporary artifacts."
---

# Track Applied Jobs

The persistent source of truth is `JobSearchAgent/applied_jobs.csv`. Its exact
header is `company,jobid,title`. No dates, URLs, status, location or other fields.
Read the CSV every time; never rely on cross-session chat memory for application
history. All commands run from the workspace root. No subagents or network calls.

1. Add rows only when the user explicitly confirms applying and identifies the
   jobs to record. Recommendations, a tailored resume or opening a link do not
   imply an application. If 'save this' is ambiguous, clarify applied status.
   Resolve all three fields from current-session listings/displayed results or
   explicit user details. Use original source `id` as `jobid`, not a guessed req
   or title-derived ID. Company keys: amazon, rubrik, uber, apple, deshaw_india.
   For Apple, retain the original location-specific posting ID, not position_id.
   Existing rows remain unchanged when recording additional applications.
   Map obvious company display names to these keys. If a title/reference is
   ambiguous, ask which job ID; don't fetch a new scan during recording.
2. Read and validate history:

   ```bash
   python3 -B JobSearchAgent/scripts/applications.py list
   ```

   Missing/corrupt history is not an empty tracker. Ask whether a missing file
   should be restored or explicitly initialized; never silently reset history.
   Setup-only initialization is `applications.py init`, which never overwrites.
3. Record each confirmed job through the helper, preserving exact text and string
   IDs. Use safely quoted arguments or call the Python API with literal data;
   never interpolate untrusted title text into executable shell code.

   ```bash
   python3 -B JobSearchAgent/scripts/applications.py add --company "<company>" --jobid "<id>" --title "<title>"
   python3 -B JobSearchAgent/scripts/applications.py validate
   python3 -B JobSearchAgent/scripts/applications.py list
   ```

   Same company/jobid is a no-op; report already recorded and preserve the original
   row even if the displayed title changed. Same title/different ID and same ID at
   different companies are distinct. Do not invent cross-ID repost detection.
   Tests must place `--tracker "<test-csv>"` before the subcommand; never write
   test applications into the real tracker. No automatic deletion/reset of rows.
4. Read back the actual rows and summarize added/already-recorded entries. If
   any write or verification fails, keep session files for retry and state which
   rows succeeded. Do not tell the user a failed record was saved.
5. When these updates are complete and the user is done with this session's
   recommendations, remove the exact root printed by match.py start:

   ```bash
   python3 -B JobSearchAgent/scripts/match.py cleanup "<root>" --recorded "<company>:<id>"
   ```

   Repeat --recorded for every confirmed job being handled before cleanup. The
   helper checks they exist in the tracker before deleting the root. Keep the
   root while the user explicitly says more application updates are pending.
   If there is no active root, just record the jobs; don't invent a cleanup path.
   Cancellation without pending recordings may use cleanup without --recorded.
   Never delete the tracker, source code, resume, interview data or arbitrary
   temp paths. If cleanup fails, report the remaining root. No report backups.

The next search/matching request fetches fresh listings and skips tracked pairs.
Application updates and tracker inspection never trigger that search themselves.