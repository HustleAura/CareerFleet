# Weakness Ledger

Recurring failure modes, deduped by concept tag from `RUBRIC.md`.

Rows are **never deleted** — flip `status` instead. The history is the point.

- `hits` — how many sessions this has been flagged in
- `status` — `open` · `improving` · `resolved`
  - `improving` — exercised again and noticeably better, but not clean
  - `resolved` — exercised and *not* flagged in 2 consecutive sessions
  - A resolved weakness that reappears goes back to `open` and keeps counting

Dedupe on the tag first. Only open a second row under the same tag if the
failure mode is genuinely distinct.

The **Active** table below holds `open` and `improving` rows. Once a row hits
`resolved`, move it verbatim to **Resolved** at the bottom — it stays on record.
If it reappears, move it back up, flip to `open`, and keep incrementing `hits`.

## Active

| Tag | Failure mode | Hits | First seen | Last seen | Sessions | Status |
|---|---|---|---|---|---|---|

_none recorded yet_

## Resolved

Kept for history. A row here that reappears goes back to **Active** as `open`,
hit count intact.

| Tag | Failure mode | Hits | First seen | Last seen | Sessions | Status |
|---|---|---|---|---|---|---|

_none recorded yet_
