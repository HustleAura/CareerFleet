---
name: tailor-resume
description: "Use when the user wants a resume tailored to a specific role — trigger phrases: 'tailor my resume', 'tailor resume for this JD', 'apply to this role', 'generate a resume for this job', 'here's a job link'. Parses the JD, ranks bullets from ResumeAgent/resume_base.md, asks about gaps one at a time, renders a one-page PDF into ResumeAgent/roles/, then link-checks the accepted resume and estimates its screen-through odds. Not for writing a resume from scratch and not for job discovery."
---

# Tailor a Resume

Two modes — pick one.

**TAILOR** is the default: a JD comes in, a PDF goes out.
**INVENTORY** is when the user just wants to add or correct facts in
`ResumeAgent/resume_base.md` without producing a resume.

`ResumeAgent/resume_base.md` is the source of truth for every fact.
`ResumeAgent/templates/tailored.schema.json` is the contract for the file you
write. Read both before writing anything. All paths are relative to the
workspace root, and every command runs from the workspace root.

## The fabrication invariant

Applies everywhere in this skill, in both modes.

- Every piece of prose in `tailored.json` carries a `source_id` that resolves to
  an entry in `resume_base.md`, plus a `transform`:
  - `verbatim` — byte-identical to the source bullet.
  - `rephrased` — reworded for the JD. **Every fact and number unchanged.**
  - `reweighted` — same facts, emphasis reordered to lead with what the JD wants.
- A number that is not in the source entry's `metrics` may not appear in the
  output. Not rounded, not approximated, not "over 3B".
- An empty field in `metrics` is a **declared gap**, not permission to fill it.
- `strength: weak` entries with open `gaps` are unusable until those gaps are
  resolved. `tailor.py` will refuse them.

New facts enter the system in exactly one way: the user says them in chat, you
write them into `resume_base.md`, and only then may a bullet cite them.

---

## TAILOR mode

Run these in order. Never skip ahead.

### 1. Create the role folder

```bash
python3 ResumeAgent/scripts/tailor.py new "<company>" "<title>" --jd-url "<url>"
```

Drop `--jd-url` if the user pasted the JD; write it into `roles/<slug>/jd.txt`
yourself. If a fetch returns navigation chrome instead of the posting — common
on LinkedIn and Workday — say so and ask for a paste rather than working from a
bad capture.

### 2. Analyse the JD

Read `roles/<slug>/jd.txt` and write `roles/<slug>/jd_analysis.json`:

```json
{
  "company": "",
  "title": "",
  "seniority_signals": [],
  "required": [],
  "preferred": [],
  "keywords": [],
  "emphasis": []
}
```

- `required` / `preferred` — concrete capabilities, not the JD's marketing prose.
- `keywords` — literal terms an ATS keyword scan would look for.
- `emphasis` — which of the inventory `themes` this role actually rewards:
  `ownership`, `scale`, `security`, `migration`, `incident-response`, `cost`,
  `leadership`, `ai-tooling`.

Show the user the `emphasis` list and your read of the seniority bar before
continuing. If your read is wrong, everything downstream is wrong.

### 3. Rank the inventory

For each entry in `resume_base.md`, judge fit against `required`, `keywords` and
`emphasis`. Match on `themes` and `keywords`, not on surface word overlap — an
entry lists synonyms precisely so a JD saying "Kubernetes" still matches a
bullet that says "AKS".

Read each candidate entry's `variants` before writing any new phrasing. A
variant is wording already approved for an earlier application. If one was
written for an overlapping `emphasis`, reuse it rather than inventing a fresh
rewrite — it costs the user less review and keeps phrasing consistent across
applications. Say which variant you are reusing and what it was written for.

Present the ranking as a short table: entry id, why it fits, and whether its
`strength` blocks use. Do not write `tailored.json` yet.

### 4. Detect gaps and ask

A gap is any of:

- The JD requires something no entry supports.
- The best-matching entry is `strength: weak`, or its `gaps` list holds a
  question that this specific JD makes load-bearing.
- The JD asks for a number the inventory does not have.

Ask **one question at a time, in chat**. Never present a form or a numbered
batch. Each question states which bullet it would strengthen and why this JD
makes it matter. Wait for the answer before asking the next.

If the user does not know a number, that is a valid answer: drop the claim and
move on. Never negotiate for a bigger figure.

After each answer, write it into `resume_base.md` immediately — fill the
`metrics` or `scope` field, remove the resolved line from `gaps`, and raise
`strength` if the entry now stands on real numbers. This is what stops the same
question being asked on the next application.

Stop asking when every remaining gap is one the JD does not actually need.

### 5. Assemble

Write `roles/<slug>/tailored.json` against
`ResumeAgent/templates/tailored.schema.json`.

- Copy `contact`, `education` and `competitive_programming` verbatim from
  `resume_base.md`. These are frozen.
- Reorder `skills` categories and items to lead with JD keywords. Adding an
  item that is not in `SKL-01` is a hard failure.
- Order experience bullets so the JD's `emphasis` leads.
- Prefer `verbatim` where the source bullet already lands. Reach for
  `rephrased` only when the JD's vocabulary genuinely differs.

### 6. Render

```bash
python3 ResumeAgent/scripts/tailor.py render <slug>
```

The script escapes LaTeX, promotes `**bold**`, fills the frozen template and
runs `pdflatex` twice. Output lands at `roles/<slug>/<slug>.pdf` — named after
the company, role and date so it stays identifiable once attached to an
application. Failures are yours to fix in `tailored.json`:

- `source_id ... is not in resume_base.md` — you invented an id.
- `transform is 'verbatim' but the text differs` — mark it `rephrased`, or
  restore the original wording.
- `strength:weak with N open gap(s)` — you skipped step 4.
- `not in the SKL-01 inventory` — you added a technology. Remove it, or ask the
  user whether they can defend it and add it to `resume_base.md` first.
- `missing LaTeX package` — run the printed `tlmgr` command, or re-run with
  `--auto-install`.

If it reports more than one page, drop the lowest-ranked bullet and render
again. Tell the user which bullet you dropped.

### 7. Bank the phrasings

Once the PDF renders, append every `rephrased` and `reweighted` bullet to its
source entry's `variants` in `resume_base.md`:

```yaml
variants:
  - text: >-
      the exact text that shipped, with **bold** markers intact
    used_for: Stripe — Backend Engineer (2026-09)
    emphasis: [scale, security]
```

Skip `verbatim` bullets — the base wording already covers those. Do not bank a
variant the user rejected or edited away; bank what actually shipped. If a new
variant says the same thing as an existing one, keep the better phrasing and
append the new `used_for` to it instead of adding a near-duplicate.

This is what makes the next application cheaper than this one.

### 8. Hand off

Report: the PDF path, which bullets were used and which were cut, every gap
question the user answered, what got written back into `resume_base.md`, and
which variants were reused from earlier applications.

Then ask whether the resume is accepted. Do not run step 9 until it is — a
review of a draft the user is still editing is wasted work.

### 9. Final review — only after the user accepts

Two checks, in this order. Both are read-only: never edit `tailored.json` or
`resume_base.md` during this step. If something is wrong, report it and let the
user decide whether to go back to step 5.

**Links.** A dead or mangled link on a resume is a silent failure — nobody tells
you the GitHub URL 404'd. Collect every URL in `roles/<slug>/tailored.json`
(`contact` fields, and every project `link`) and check each one:

```bash
curl -sS -o /dev/null -w '%{http_code}  %{url_effective}\n' -L --max-time 15 "<url>"
```

Then confirm the PDF carries the same URLs the JSON does, since LaTeX escaping
is where a good URL turns into a broken one:

```bash
grep -o 'href{[^}]*}' roles/<slug>/<slug>.tex
```

Every `href` target must match a URL from `tailored.json` character for
character. Report a small table: URL, HTTP status, and whether it survived into
the `.tex` intact. Call out anything that is not a `200`. A `403` from a site
that blocks automated fetches (LinkedIn does this) is not a broken link — say
so rather than raising a false alarm, and ask the user to eyeball that one.

**Screen-through estimate.** A short, honest read on whether this resume clears
the resume screen for *this* posting. Keep it to a percentage and three lines:

```
Screen-through estimate: NN%
Carries it:  <the strongest match against `required`>
Drags it:    <the required qual with the weakest or no evidence>
Biggest lever: <the one change that would move the number most>
```

Ground the number in `jd_analysis.json`, not in vibes:

- Start from coverage of `required`. An unmet hard minimum is the dominant
  term — it caps the estimate low no matter how strong the rest reads.
- Then weigh seniority fit, `keywords` coverage for an ATS pass, and whether
  the leading bullets actually speak to `emphasis`.
- Company selectivity is part of the number. The same resume does not have the
  same odds at Google and at a Series A startup.

The anti-fabrication invariant applies to this estimate too. Do not inflate it
to be encouraging, and do not hedge it into uselessness with a 20-point band.
If an unmet minimum makes it a long shot, say the number out loud and name what
would fix it. The user is deciding where to spend limited application effort,
and a flattering number costs them more than a blunt one.

---

## INVENTORY mode

The user wants to add a project, correct a number, or answer a gap outside of an
application.

1. Read `resume_base.md` and find or create the relevant entry.
2. Ask only what you need. One question at a time.
3. Write the answer in the user's own terms. Do not upgrade "roughly 200" into
   "200+", and do not add adjectives they did not use.
4. Update `strength` to reflect what is actually documented now, and prune the
   `gaps` lines you resolved.
5. Confirm what changed. Never render a resume in this mode.
