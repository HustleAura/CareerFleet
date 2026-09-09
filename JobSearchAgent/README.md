# Job Search Agent

Company-specific, on-demand job collection for **Hyderabad and Bengaluru,
India**, with fresh collection on every search, resume matching in chat and a
three-column applied-jobs CSV. Only that CSV persists between sessions.
Python 3.9+ and its standard library are sufficient; no installation,
browser, API key or model subscription is needed by the collectors.

## Scope

| Company | Source | Role filter | Default |
|---|---|---|---|
| Rubrik | Public Greenhouse JSON | None | Enabled |
| Amazon | Public search JSON, all pages | SDE-II title variants | Enabled, terms review warning |
| D. E. Shaw India | JSON embedded in the careers HTML | None | Enabled, private personal use |
| Uber | Oracle search JSON plus public details | None | Enabled, terms review warning |
| Apple | JSON embedded in search/detail HTML | None | Blocked pending approved access |

Public/active-state validation, ID deduplication and exact country/city checks
apply to every company. No generic ATS adapter framework is used. Descriptions
are source data, never executable instructions.

Source spelling is preserved: `Bangalore` stays `Bangalore`, and `Bengaluru`
stays `Bengaluru`. Location comparisons treat both as the same city. Keep
`Bengaluru` in configuration because the portal clients use its verified search
value or corresponding location ID.

## Usage

Select **Job Search** and ask to find jobs or matches. The agent collects current
listings, skips your recorded applications and shows up to three evidence-backed
matches per company in chat. Tell it which jobs you applied to; it records those
and removes the temporary session files when you are done. Application updates
do not start another search. Explicit listings-only requests skip assessment.

The agent uses these commands from the CareerFleet workspace root:

```bash
python3 -B JobSearchAgent/scripts/match.py start
python3 -B JobSearchAgent/scripts/match.py start --company rubrik
python3 -B JobSearchAgent/scripts/match.py start --company amazon --company deshaw_india --company uber
python3 -B JobSearchAgent/scripts/scan.py --all --dry-run
python3 -B JobSearchAgent/scripts/scan.py --validate "<printed-temporary-run>"
```

Registrations are in
[the agent entrypoint](../.github/agents/Job%20Search.agent.md) and
[the skill](../.github/skills/job-search/SKILL.md).

`--company` is repeatable. No company argument means all five. `--dry-run`
makes network calls but writes no run artifacts; `-B` also suppresses Python
bytecode. Direct non-dry `scan.py` requires an explicit `--output-dir` inside
system temp and fails before fetching when omitted. `match.py start` manages
that path automatically and prints the owned root, run and matching session.
`--validate` is offline. No workspace runs/matches defaults or old scan reuse.

Exit codes for start/scan: **0** all requested sources complete (or outputs valid),
**2** at least one source partial, failed, disabled or blocked, **1** configuration,
validation or persistence error. With the default Apple access gate, all-company start
returns 2 even when the other four companies succeed. Read each receipt.

## Testing

Ask **"test job search agent"** or **"test job search for Rubrik"** to invoke
the [test-agents skill](../.github/skills/test-agents/SKILL.md). Its job-search
path runs production collectors into a unique system temporary directory,
checks city spellings and Amazon title rules, validates temporary results, reports
source coverage and failures, and removes test artifacts afterward. It does not
start a system-design interview or change the real applied tracker.

Ask **test matching** or **test applied tracker** for the matching/tracker path.
Tests use an explicit temporary CSV and fresh collection, verify exclusion and
cleanup ordering, and never add test jobs to real application history. Structural
checks and actual semantic assessment coverage are reported separately.

There is no standalone job unit-test file. The skill documents live verification
and small in-memory checks; unexercised failure paths are reported as untested,
not claimed as equivalent to the removed offline suite. Updating the skill does
not itself launch tests.

## Outputs

Session files exist only under one private system-temporary directory:

```text
<system-temp>/careerfleet-jobs-<unique-id>/
  .careerfleet-session.json
  collection/<timestamp>-<id>/
    report.md
    <company>/{receipt,inventory,listings,unresolved}.json
  matching/<timestamp>-<id>/
    manifest.json
    candidates.json
    evidence.json
    assessments.json
    batch-*.json
    selections.json
    shortlist.md
    receipt.json
```

Directories are private and files are created with owner-only permissions.
These reports are scratch files for validation and chat presentation, not saved
deliverables. Failed start removes its own root. Keep the root while application
follow-up is pending, verify confirmed CSV updates, then use cleanup to delete
the root. No resume, interview or MCP files are modified. Global feeds and
internal job payloads are not saved.

- `inventory.json`: all public, city-scoped records retrieved, including
  excluded Amazon titles and any expired records. Source field conflicts are
  retained as warnings.
- `listings.json`: the displayable subset. Only Amazon applies title filtering.
  Expired or unknown-expiry postings are withheld; exploratory postings remain
  included and labelled. Missing descriptions remain visible with a partial status.
- `unresolved.json`: public postings with insufficient/conflicting location
  evidence, such as Apple India-wide pipeline jobs or Rubrik remote-India jobs.
- `receipt.json`: source page counts, unique IDs, city counts, title exclusions,
  missing descriptions, timestamps, completeness flags and errors.
- `report.md`: all displayable jobs with links, plus per-company status and
  unresolved locations. There is no top-N truncation or fit ranking.

A valid empty feed is different from a failed fetch. Counts changing during
pagination, repeated posting IDs, missing structured data, or incomplete
descriptions cannot silently become a successful empty result. A complete
receipt is a point-in-time source inventory, not a guarantee that every employer
is still hiring or that jobs remained unchanged throughout a paginated scan.

## Amazon Filter

The client fetches the complete two-city inventory before locally selecting
SDE II / SDE 2, Software Development Engineer II, Software Dev Engineer II,
and Software Engineer II variants. Matching is case-insensitive with token
boundaries and optional punctuation/team suffixes. SDE III, SDET, support-only
and scientist titles do not qualify. Explicit mixed-level titles are flagged
as unresolved. No experience-year or compensation inference is used.

## Access Conditions

Technical accessibility is not blanket permission for recurring extraction.
Check applicable terms before repeated use and keep employer content private.
There is no scheduler or automatic retry loop between runs.

- Rubrik uses the documented Greenhouse GET API, not corporate-page scraping.
- D. E. Shaw's terms permit personal non-commercial copies subject to other
  restrictions and robots.txt; the disclosures page also contains broader
  reproduction language. This is not legal clearance to republish data.
- Amazon's linked conditions could not be fully reviewed during verification;
  Uber's recruitment-specific access conditions remain unconfirmed. Both emit
  visible warnings for each on-demand run. Disable them in configuration if
  your intended access is not permitted.
- Apple's website terms restrict automated extraction. The parser is implemented
  and tested, but normal scans make **no Apple network requests**. Only after
  obtaining an applicable permission or sanctioned access basis should the user
  set Apple's `enabled` to `true`, `access` to `approved`, and a nonempty
  `approval_reference` in [search_config.json](search_config.json). Configuration
  records that basis; it does not confer permission. The agent must not create
  approvals itself.

GET requests are host-restricted, use a declared User-Agent, have timeouts and
bounded retries, and honor bounded Retry-After delays. Authentication failures,
challenges and foreign-host redirects are not bypassed. There are no application
POSTs, cookies, credential collection, stealth browsers or proxies.

## Applied Tracker

[applied_jobs.csv](applied_jobs.csv) is the only persistent runtime job-search data:

```csv
company,jobid,title
```

It starts empty. Tell the agent which jobs you applied to and want recorded.
The [track-applications skill](../.github/skills/track-applications/SKILL.md)
resolves their exact IDs/titles and verifies the written rows. No dates, URLs,
statuses or other columns are stored. Company keys are amazon, rubrik, uber,
apple and deshaw_india. Job IDs remain strings; the title is informational.

Same company + jobid means already applied, even when its title changes. Repeated
recording is a no-op, not another row or a silent title update. Different IDs with
identical titles remain distinct. A repost using a different ID is not recognized
as the old application. No applications are inferred from recommendations or PDFs.

```bash
python3 -B JobSearchAgent/scripts/applications.py init
python3 -B JobSearchAgent/scripts/applications.py list
python3 -B JobSearchAgent/scripts/applications.py add --company "<company>" --jobid "<id>" --title "<title>"
python3 -B JobSearchAgent/scripts/applications.py validate
```

`init` is setup-only and never overwrites history. If the file goes missing later,
restore it or explicitly confirm an empty replacement; matching fails rather than
assuming you applied nowhere. The CSV is local, owner-private and gitignored,
so Git does not back it up or synchronize it. `--tracker <temp-csv>` goes before
the applications.py subcommand for tests. Safe atomic writes preserve previous
history on handled failures; cleanup must wait if a confirmed update failed.

## Match And Finish

The [match-jobs skill](../.github/skills/match-jobs/SKILL.md) reads all untracked
JDs from the fresh request in bounded batches against the full current resume.
Python validates evidence and ranks judgments; it does not perform semantic
assessment or call a hosted model. See the [matching policy](MATCHING_POLICY.md)
and [assessment schema](templates/matches.schema.json).

```bash
python3 -B JobSearchAgent/scripts/match.py validate "<session>" --batch "<session>/batch-001.json"
python3 -B JobSearchAgent/scripts/match.py validate "<session>" --complete
python3 -B JobSearchAgent/scripts/match.py finalize "<session>"
python3 -B JobSearchAgent/scripts/match.py validate "<session>" --complete
```

start already prepares candidates, excluding exact tracked pairs. Lower-level
prepare requires this request's temporary `--run`, an explicit temporary
`--output-dir` and optional `--tracker`; no workspace or historical-run input.
Every remaining candidate needs a disposition before finalization. Source totals,
applied exclusions and assessment counts remain separate. Missing/partial/blocked
sources stay visible; Apple blocked does not mean zero openings. A partial result
stays PROVISIONAL. Empty descriptions/invalid expiry need review; exploratory
postings are separate. No extra non-Amazon title/level/years prefilter.

Select **up to three per company**, never pad. Label defensible stretches and
unmet minima. Prioritize relevant AI engineering among credible fits; neither
AI keywords nor skills lists establish undocumented production experience.
Indices are heuristics, not hiring odds or ATS scores. Quotes alone cannot prove
semantic fit: selected recommendations need a direct evidence audit. Re-read the
tracker at finalization and audit any replacement selections before display.

Temporary finals are validated before display, never overwritten or maintained
as history. After application updates, no old report revalidation is needed.
Read the resulting recommendations into chat with direct employer links, then
record user-confirmed applications and clean up when finished:

```bash
python3 -B JobSearchAgent/scripts/match.py cleanup "<printed-root>" --recorded "<company>:<id>"
```

Repeat `--recorded` for each confirmation. Cleanup checks those pairs exist in the
tracker, verifies the owned system-temp root, and deletes only that root, never
the tracker. With no pending confirmations, omit `--recorded`. Keep the root while
the user is still applying or a recording failed. No scan/report backups. An abrupt
editor shutdown cannot guarantee cleanup: recover only the exact printed root,
not arbitrary temp directories. A new search always starts a fresh collection.

No automatic tailoring/applications, employer contact, compensation/level inference,
resume fact changes, collector rebuild or access-setting changes.

See [docs/portal-contracts.md](docs/portal-contracts.md) for the verified endpoint
contracts and the implementation phases.