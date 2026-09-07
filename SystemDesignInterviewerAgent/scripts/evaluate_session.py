#!/usr/bin/env python3
"""Session lifecycle for multi-model design interview evaluation.

Every interview lives in one folder under `sessions/<session-id>/`. Two pinned
evaluator models score the same frozen transcript independently; disagreements
are settled by an anonymised adjudication pass. Scores are never averaged.

Durable artifacts per session:
    evaluation.json      full structured audit bundle
    card.md              human-readable card, generated from evaluation.json

The recording stays in `recordings/` and the transcript in `transcripts/`. Both
are working material, not artifacts: they are gitignored, referenced by path and
hash, and safe to delete once a session is finalized.

`.work/` holds resumable in-flight state and is deleted at finalization.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SESSIONS_DIR = ROOT / "sessions"
RECORDINGS_DIR = ROOT / "recordings"
TRANSCRIPTS_DIR = ROOT / "transcripts"
PROGRESS_DIR = ROOT / "progress"
RUBRIC_PATH = PROGRESS_DIR / "RUBRIC.md"
JSONL_PATH = PROGRESS_DIR / "sessions.jsonl"
STATE_PATH = PROGRESS_DIR / "STATE.md"

SCHEMA_VERSION = 1
STANDARD_VERSION = "v2"

DIMENSIONS = (
    "overall",
    "requirements_scoping",
    "capacity_math",
    "api_data_model",
    "architecture",
    "scale_reliability",
    "tradeoffs_communication",
)
DIMENSION_LABELS = {
    "overall": "Overall",
    "requirements_scoping": "Requirements & scoping",
    "capacity_math": "Capacity & back-of-envelope math",
    "api_data_model": "API & data model",
    "architecture": "Core architecture & component choice",
    "scale_reliability": "Scale, reliability & bottlenecks",
    "tradeoffs_communication": "Tradeoff reasoning & communication",
}
DIFFICULTIES = ("basic", "easy", "medium", "hard", "architect")
TIMESTAMP = re.compile(r"\[(\d{2,}):(\d{2})\]")
STATUSES = (
    "created",
    "transcribed",
    "frozen",
    "judged",
    "adjudicating",
    "resolved",
    "needs_review",
    "finalized",
)


class SessionError(Exception):
    pass


# --- primitives -------------------------------------------------------------


def fail(message):
    raise SessionError(message)


def rel(path):
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def sha256_file(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"Cannot read {rel(path)}: {error}")


def write_json(path, payload):
    Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def concept_tags():
    """Closed tag vocabulary, parsed from the rubric so there is one source."""
    pattern = re.compile(r"^\|\s*`([a-z0-9-]+)`\s*\|")
    tags = [m.group(1) for m in (pattern.match(line) for line in RUBRIC_PATH.read_text(encoding="utf-8").splitlines()) if m]
    if not tags:
        fail("No concept tags found in progress/RUBRIC.md")
    return set(tags)


def session_dir(session_id):
    return SESSIONS_DIR / session_id


def work_dir(session_id):
    return session_dir(session_id) / ".work"


def state_file(session_id):
    return work_dir(session_id) / "state.json"


def load_state(session_id):
    path = state_file(session_id)
    if not path.is_file():
        if (session_dir(session_id) / "evaluation.json").is_file():
            fail(f"Session {session_id} is finalized and immutable")
        fail(f"No in-flight session at {rel(session_dir(session_id))}")
    return read_json(path)


def save_state(state):
    write_json(state_file(state["session_id"]), state)


def require(state, *allowed):
    if state["status"] not in allowed:
        fail(f"Session is '{state['status']}'; expected one of: {', '.join(allowed)}")


def transcript_duration(path):
    stamps = TIMESTAMP.findall(Path(path).read_text(encoding="utf-8"))
    if not stamps:
        return None
    minutes, seconds = stamps[-1]
    return f"{int(minutes):02d}:{seconds}"


def jsonl_lines():
    if not JSONL_PATH.is_file():
        return []
    return [json.loads(line) for line in JSONL_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def attempt_number(problem, existing=None):
    rows = jsonl_lines() if existing is None else existing
    return sum(1 for row in rows if row["problem"] == problem) + 1


# --- validation -------------------------------------------------------------


def validate_scores(scores, label):
    if set(scores) != set(DIMENSIONS):
        fail(f"{label}.scores must contain exactly: {', '.join(DIMENSIONS)}")
    for dimension, score in scores.items():
        if score is None:
            continue
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 10:
            fail(f"{label}.scores.{dimension} must be an integer 0-10 or null")


def validate_scorecard(payload, state, model):
    label = f"judgment[{model}]"
    if payload.get("schema_version") != SCHEMA_VERSION:
        fail(f"{label}: unsupported schema_version")
    if payload.get("session_id") != state["session_id"]:
        fail(f"{label}: session_id does not match this session")
    if payload.get("transcript_sha256") != state["transcript_sha256"]:
        fail(f"{label}: scored a different transcript than the frozen one")

    validate_scores(payload.get("scores", {}), label)
    for field in ("evidence", "rationales"):
        if set(payload.get(field, {})) != set(DIMENSIONS):
            fail(f"{label}.{field} must contain exactly the seven dimension keys")

    for dimension in DIMENSIONS:
        score = payload["scores"][dimension]
        evidence = payload["evidence"][dimension]
        if not isinstance(evidence, list):
            fail(f"{label}.evidence.{dimension} must be a list")
        if score is None:
            if evidence:
                fail(f"{label}.evidence.{dimension} must be empty when the score is null")
        else:
            if not evidence:
                fail(f"{label}.evidence.{dimension} needs at least one timestamped quote")
            for item in evidence:
                if not isinstance(item, str) or not TIMESTAMP.search(item):
                    fail(f"{label}.evidence.{dimension} entries must include an [mm:ss] timestamp")
        rationale = payload["rationales"][dimension]
        if not isinstance(rationale, str) or not rationale.strip():
            fail(f"{label}.rationales.{dimension} is required")

    strengths = payload.get("strengths")
    if not isinstance(strengths, list) or not 3 <= len(strengths) <= 5:
        fail(f"{label}.strengths must be 3-5 items")
    if not all(isinstance(item, str) and item.strip() for item in strengths):
        fail(f"{label}.strengths entries must be non-empty strings")

    weaknesses = payload.get("weaknesses")
    if not isinstance(weaknesses, list) or not 3 <= len(weaknesses) <= 5:
        fail(f"{label}.weaknesses must be 3-5 items")
    allowed = concept_tags()
    seen = set()
    for item in weaknesses:
        if not isinstance(item, dict) or set(item) != {"tag", "detail"}:
            fail(f"{label}.weaknesses entries must be objects with exactly 'tag' and 'detail'")
        if item["tag"] not in allowed:
            fail(f"{label}: '{item['tag']}' is not a concept tag in RUBRIC.md")
        if item["tag"] in seen:
            fail(f"{label}: duplicate weakness tag '{item['tag']}'")
        seen.add(item["tag"])
        if not isinstance(item["detail"], str) or not item["detail"].strip():
            fail(f"{label}.weaknesses['{item['tag']}'].detail is required")

    if not isinstance(payload.get("verdict"), str) or not payload["verdict"].strip():
        fail(f"{label}.verdict is required")
    return payload


def validate_adjudication(payload, state, adjudicator):
    label = f"adjudication[{adjudicator}]"
    disputes = state.get("disputes")
    if not disputes:
        fail("No dispute packet has been built for this session")
    if payload.get("schema_version") != SCHEMA_VERSION:
        fail(f"{label}: unsupported schema_version")
    if payload.get("session_id") != state["session_id"]:
        fail(f"{label}: session_id does not match this session")

    dimensions = payload.get("dimensions", {})
    if set(dimensions) != set(disputes["dimensions"]):
        fail(f"{label}.dimensions must decide exactly the disputed dimensions: {', '.join(disputes['dimensions']) or '(none)'}")
    for dimension, decision in dimensions.items():
        if not isinstance(decision, dict) or set(decision) != {"choice", "rationale"}:
            fail(f"{label}.dimensions.{dimension} must have exactly 'choice' and 'rationale'")
        if decision["choice"] not in ("A", "B"):
            fail(f"{label}.dimensions.{dimension}.choice must be 'A' or 'B'")
        if not isinstance(decision["rationale"], str) or not decision["rationale"].strip():
            fail(f"{label}.dimensions.{dimension}.rationale is required")

    tags = payload.get("tags", {})
    if set(tags) != set(disputes["tags"]):
        fail(f"{label}.tags must decide exactly the disputed tags: {', '.join(disputes['tags']) or '(none)'}")
    for tag, decision in tags.items():
        if not isinstance(decision, dict) or set(decision) != {"include", "rationale"}:
            fail(f"{label}.tags.{tag} must have exactly 'include' and 'rationale'")
        if not isinstance(decision["include"], bool):
            fail(f"{label}.tags.{tag}.include must be true or false")
        if not isinstance(decision["rationale"], str) or not decision["rationale"].strip():
            fail(f"{label}.tags.{tag}.rationale is required")
    return payload


# --- lifecycle --------------------------------------------------------------


def cmd_init(args):
    session_id = args.session_id
    if args.difficulty not in DIFFICULTIES:
        fail(f"difficulty must be one of: {', '.join(DIFFICULTIES)}")
    folder = session_dir(session_id)
    if folder.exists():
        fail(f"Session already exists: {rel(folder)}")
    work_dir(session_id).mkdir(parents=True)

    state = {
        "schema_version": SCHEMA_VERSION,
        "standard_version": STANDARD_VERSION,
        "session_id": session_id,
        "problem": args.problem,
        "difficulty": args.difficulty,
        "date": args.date or date.today().isoformat(),
        "status": "created",
        "recording": None,
        "transcript_raw_path": None,
        "transcript_raw_sha256": None,
        "transcript_path": None,
        "transcript_sha256": None,
        "clarifications": [],
        "excluded_additions": [],
        "refinements": {},
        "judgments": {},
        "disputes": None,
        "adjudications": {},
        "resolution": None,
    }

    if args.recording:
        source = Path(args.recording).expanduser().resolve()
        if not source.is_file():
            fail(f"Not a file: {args.recording}")
        state["recording"] = {"path": rel(source), "sha256": sha256_file(source)}

    save_state(state)
    print(f"Created {rel(folder)} (status: created)")


def cmd_transcribe(args):
    state = load_state(args.session_id)
    require(state, "created")
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    raw = TRANSCRIPTS_DIR / f"{args.session_id}.txt"

    if args.from_file:
        source = Path(args.from_file).expanduser().resolve()
        if not source.is_file():
            fail(f"Not a file: {args.from_file}")
        if source != raw:
            shutil.copyfile(source, raw)
    else:
        if not state["recording"]:
            fail("No recording attached; pass --from-file with an existing transcript")
        recording = ROOT / state["recording"]["path"]
        if not recording.is_file():
            fail(f"Recording no longer at {state['recording']['path']}")
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "transcribe.py"), str(recording), "--out", str(raw)],
            check=False,
        )
        if result.returncode != 0:
            fail("Transcription failed")

    if not raw.is_file() or not raw.read_text(encoding="utf-8").strip():
        fail("Transcription produced no text")
    state["transcript_raw_path"] = rel(raw)
    state["transcript_raw_sha256"] = sha256_file(raw)
    state["status"] = "transcribed"
    save_state(state)
    print(f"Wrote {rel(raw)} (status: transcribed)")


def cmd_freeze(args):
    """Promote the clarified transcript to the immutable scoring input."""
    state = load_state(args.session_id)
    require(state, "transcribed")
    raw = ROOT / state["transcript_raw_path"]

    # An unchanged transcript is frozen in place rather than duplicated.
    if args.corrected:
        source = Path(args.corrected).expanduser().resolve()
        if not source.is_file():
            fail(f"Not a file: {source}")
        final = TRANSCRIPTS_DIR / f"{args.session_id}.frozen.txt"
        shutil.copyfile(source, final)
    else:
        final = raw

    state["transcript_path"] = rel(final)
    state["transcript_sha256"] = sha256_file(final)
    state["clarifications"] = read_json(args.clarifications) if args.clarifications else []
    state["excluded_additions"] = read_json(args.excluded) if args.excluded else []
    state["status"] = "frozen"
    save_state(state)
    print(f"Froze {rel(final)} sha256={state['transcript_sha256'][:12]} (status: frozen)")
    print("Both evaluators must now score this exact file.")


def cmd_import(args):
    state = load_state(args.session_id)
    payload = read_json(args.file)

    if args.kind == "refinement":
        require(state, "transcribed")
        state["refinements"][args.model] = payload
    elif args.kind == "judgment":
        require(state, "frozen", "judged")
        validate_scorecard(payload, state, args.model)
        state["judgments"][args.model] = payload
        if len(state["judgments"]) >= 2:
            state["status"] = "judged"
    elif args.kind == "adjudication":
        require(state, "adjudicating", "needs_review")
        validate_adjudication(payload, state, args.model)
        state["adjudications"][args.model] = payload
        state["status"] = "adjudicating"
        state["resolution"] = None

    save_state(state)
    print(f"Imported {args.kind} from {args.model} (status: {state['status']})")


def cmd_disputes(args):
    state = load_state(args.session_id)
    require(state, "judged")
    models = sorted(state["judgments"])
    if len(models) != 2:
        fail(f"Expected exactly 2 judgments, found {len(models)}")

    # Deterministic but content-derived A/B assignment, so packet order carries
    # no information about which model produced which scorecard.
    flip = int(state["transcript_sha256"][:8], 16) % 2
    ab_map = {"A": models[flip], "B": models[1 - flip]}
    first, second = state["judgments"][ab_map["A"]], state["judgments"][ab_map["B"]]

    disputed_dimensions = {}
    for dimension in DIMENSIONS:
        if first["scores"][dimension] != second["scores"][dimension]:
            disputed_dimensions[dimension] = {
                "A": {
                    "score": first["scores"][dimension],
                    "evidence": first["evidence"][dimension],
                    "rationale": first["rationales"][dimension],
                },
                "B": {
                    "score": second["scores"][dimension],
                    "evidence": second["evidence"][dimension],
                    "rationale": second["rationales"][dimension],
                },
            }

    tags_a = {item["tag"]: item["detail"] for item in first["weaknesses"]}
    tags_b = {item["tag"]: item["detail"] for item in second["weaknesses"]}
    agreed_tags = sorted(set(tags_a) & set(tags_b))
    disputed_tags = {
        tag: {"cited_by": "A" if tag in tags_a else "B", "detail": tags_a.get(tag) or tags_b[tag]}
        for tag in sorted(set(tags_a) ^ set(tags_b))
    }

    state["ab_map"] = ab_map
    state["disputes"] = {
        "dimensions": disputed_dimensions,
        "tags": disputed_tags,
        "agreed_tags": agreed_tags,
    }
    state["adjudications"] = {}
    state["status"] = "adjudicating" if (disputed_dimensions or disputed_tags) else "judged"
    save_state(state)

    if not disputed_dimensions and not disputed_tags:
        print("Both evaluators agree on every dimension and tag. Run 'resolve' next.")
        return

    packet = {
        "schema_version": SCHEMA_VERSION,
        "session_id": state["session_id"],
        "transcript_path": state["transcript_path"],
        "transcript_sha256": state["transcript_sha256"],
        "rubric_path": rel(RUBRIC_PATH),
        "difficulty": state["difficulty"],
        "problem": state["problem"],
        "dimensions": disputed_dimensions,
        "tags": disputed_tags,
    }
    packet_path = work_dir(state["session_id"]) / "dispute-packet.json"
    write_json(packet_path, packet)
    print(json.dumps(packet, indent=2))
    print(f"\nWrote {rel(packet_path)}", file=sys.stderr)
    print(
        f"{len(disputed_dimensions)} disputed dimension(s), {len(disputed_tags)} disputed tag(s). "
        "Send this packet to both adjudicators verbatim.",
        file=sys.stderr,
    )


def cmd_resolve(args):
    state = load_state(args.session_id)
    require(state, "judged", "adjudicating", "needs_review")
    if state["disputes"] is None:
        fail("Run 'disputes' before resolving")

    models = sorted(state["judgments"])
    ab_map = state["ab_map"]
    disputes = state["disputes"]
    unresolved = []

    if disputes["dimensions"] or disputes["tags"]:
        adjudicators = sorted(state["adjudications"])
        if len(adjudicators) != 2:
            fail(f"Expected 2 adjudications, found {len(adjudicators)}")
    else:
        adjudicators = []

    scores, sources = {}, {}
    for dimension in DIMENSIONS:
        if dimension in disputes["dimensions"]:
            choices = {state["adjudications"][a]["dimensions"][dimension]["choice"] for a in adjudicators}
            if len(choices) != 1:
                unresolved.append(f"dimension '{dimension}': adjudicators chose A and B")
                continue
            letter = choices.pop()
            scores[dimension] = disputes["dimensions"][dimension][letter]["score"]
            sources[dimension] = "adjudicated"
        else:
            scores[dimension] = state["judgments"][models[0]]["scores"][dimension]
            sources[dimension] = "agreed"

    tags = list(disputes["agreed_tags"])
    for tag in disputes["tags"]:
        votes = {state["adjudications"][a]["tags"][tag]["include"] for a in adjudicators}
        if len(votes) != 1:
            unresolved.append(f"tag '{tag}': adjudicators disagree on inclusion")
        elif votes.pop():
            tags.append(tag)
    tags = sorted(set(tags))

    if unresolved:
        state["status"] = "needs_review"
        state["resolution"] = {"unresolved": unresolved}
        save_state(state)
        print("NEEDS REVIEW - canonical result is blocked:", file=sys.stderr)
        for item in unresolved:
            print(f"  - {item}", file=sys.stderr)
        fail("Adjudication did not converge; a human must settle these before finalizing")

    if not tags:
        fail("Canonical weakness list is empty; a human must settle the tag set before finalizing")

    # The narrative comes from whichever judge the canonical scores overrode
    # least, so the card's prose matches the numbers it sits beside.
    overrides = {m: sum(1 for d in DIMENSIONS if state["judgments"][m]["scores"][d] != scores[d]) for m in models}
    primary = min(models, key=lambda m: (overrides[m], m))
    other = [m for m in models if m != primary][0]
    details = {i["tag"]: i["detail"] for i in state["judgments"][other]["weaknesses"]}
    details.update({i["tag"]: i["detail"] for i in state["judgments"][primary]["weaknesses"]})

    state["resolution"] = {
        "scores": scores,
        "score_sources": sources,
        "weaknesses": [{"tag": tag, "detail": details[tag]} for tag in tags],
        "strengths": state["judgments"][primary]["strengths"],
        "verdict": state["judgments"][primary]["verdict"],
        "narrative_model": primary,
        "overrides": overrides,
        "ab_map": ab_map,
        "unresolved": [],
    }
    state["status"] = "resolved"
    save_state(state)

    print(f"Resolved. Narrative from {primary} (overrides {overrides}).")
    for dimension in DIMENSIONS:
        print(f"  {DIMENSION_LABELS[dimension]:<38} {str(scores[dimension]):>4}  ({sources[dimension]})")
    print(f"  weakness tags: {', '.join(tags)}")


def render_card(bundle):
    lines = [
        f"# {bundle['problem']}",
        "",
        f"- **Date:** {bundle['date']}",
        f"- **Difficulty:** {bundle['difficulty']}",
        f"- **Attempt:** {bundle['attempt_number']} of this problem",
        f"- **Duration:** {bundle['duration'] or 'unknown'}",
        f"- **Transcript:** {bundle['transcript_path']}",
        f"- **Evaluated by:** {' + '.join(bundle['models'])} ({bundle['standard_version']})",
        "",
        "## Scores",
        "",
        "| Dimension | Score |",
        "|---|---|",
    ]
    for dimension in DIMENSIONS:
        score = bundle["scores"][dimension]
        lines.append(f"| {DIMENSION_LABELS[dimension]} | {'null' if score is None else score} |")
    lines += ["", "## Strengths", ""]
    lines += [f"- {item}" for item in bundle["strengths"]]
    lines += ["", "## Weaknesses", ""]
    lines += [f"- `{item['tag']}` — {item['detail']}" for item in bundle["weaknesses"]]
    lines += ["", "## Verdict", "", bundle["verdict"], ""]
    return "\n".join(lines)


def cmd_finalize(args):
    state = load_state(args.session_id)
    require(state, "resolved")
    folder = session_dir(args.session_id)
    resolution = state["resolution"]

    bundle = {
        "schema_version": SCHEMA_VERSION,
        "standard_version": state["standard_version"],
        "session_id": state["session_id"],
        "problem": state["problem"],
        "difficulty": state["difficulty"],
        "date": state["date"],
        "attempt_number": attempt_number(state["problem"]),
        "duration": transcript_duration(ROOT / state["transcript_path"]),
        "finalized_at": date.today().isoformat(),
        "models": sorted(state["judgments"]),
        "rubric_sha256": sha256_file(RUBRIC_PATH),
        "recording": state["recording"],
        "transcript_raw_path": state["transcript_raw_path"],
        "transcript_raw_sha256": state["transcript_raw_sha256"],
        "transcript_path": state["transcript_path"],
        "transcript_sha256": state["transcript_sha256"],
        "clarifications": state["clarifications"],
        "excluded_additions": state["excluded_additions"],
        "scores": resolution["scores"],
        "score_sources": resolution["score_sources"],
        "strengths": resolution["strengths"],
        "weaknesses": resolution["weaknesses"],
        "verdict": resolution["verdict"],
        "narrative_model": resolution["narrative_model"],
        "audit": {
            "refinements": state["refinements"],
            "judgments": state["judgments"],
            "ab_map": resolution["ab_map"],
            "disputes": state["disputes"],
            "adjudications": state["adjudications"],
            "overrides": resolution["overrides"],
        },
        "recorded_in_progress": False,
    }

    write_json(folder / "evaluation.json", bundle)
    (folder / "card.md").write_text(render_card(bundle), encoding="utf-8")
    shutil.rmtree(work_dir(args.session_id))
    print(f"Finalized {rel(folder)}")
    print(f"  evaluation.json + card.md written; .work/ removed")
    print(f"  next: python3 scripts/evaluate_session.py record {args.session_id}")


# --- progress ledger --------------------------------------------------------


def render_state_md(rows):
    header = STATE_PATH.read_text(encoding="utf-8").split("**Sessions completed:**")[0]
    overalls = [row["overall"] for row in rows][-5:]
    lines = [
        header.rstrip("\n"),
        "",
        f"**Sessions completed:** {len(rows)}",
        f"**Last 5 overall:** {', '.join(str(value) for value in overalls) if overalls else 'none yet'}",
        "",
        "## Proficiency matrix",
        "",
        "| Dimension | " + " | ".join(DIFFICULTIES) + " |",
        "|---|" + "---|" * len(DIFFICULTIES),
    ]
    for dimension in DIMENSIONS:
        cells = []
        for rung in DIFFICULTIES:
            values = [
                row["overall"] if dimension == "overall" else row["dimensions"][dimension]
                for row in rows
                if row["difficulty"] == rung
            ]
            values = [value for value in values if value is not None]
            cells.append(f"{sum(values) / len(values):.1f} ({len(values)})" if values else "null")
        lines.append(f"| {DIMENSION_LABELS[dimension]} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def cmd_record(args):
    folder = session_dir(args.session_id)
    bundle_path = folder / "evaluation.json"
    if not bundle_path.is_file():
        fail(f"Session {args.session_id} is not finalized")
    bundle = read_json(bundle_path)
    rows = jsonl_lines()
    if any(row["transcript_stem"] == args.session_id for row in rows):
        fail(f"Session {args.session_id} is already recorded in sessions.jsonl")

    entry = {
        "date": bundle["date"],
        "transcript_stem": bundle["session_id"],
        "problem": bundle["problem"],
        "difficulty": bundle["difficulty"],
        "attempt_number": bundle["attempt_number"],
        "overall": bundle["scores"]["overall"],
        "dimensions": {d: bundle["scores"][d] for d in DIMENSIONS if d != "overall"},
        "weakness_tags": [item["tag"] for item in bundle["weaknesses"]],
    }
    with JSONL_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, separators=(",", ":")) + "\n")
    STATE_PATH.write_text(render_state_md(rows + [entry]), encoding="utf-8")

    bundle["recorded_in_progress"] = True
    write_json(bundle_path, bundle)
    print(f"Appended to {rel(JSONL_PATH)} and rewrote {rel(STATE_PATH)}")
    print(f"Now update progress/WEAKNESSES.md by hand for tags: {', '.join(entry['weakness_tags'])}")


# --- inspection -------------------------------------------------------------


def cmd_status(args):
    if args.session_id:
        ids = [args.session_id]
    else:
        ids = sorted(p.name for p in SESSIONS_DIR.iterdir() if p.is_dir()) if SESSIONS_DIR.is_dir() else []
    if not ids:
        print("No sessions.")
        return
    for session_id in ids:
        folder = session_dir(session_id)
        if (folder / "evaluation.json").is_file():
            bundle = read_json(folder / "evaluation.json")
            recorded = "recorded" if bundle.get("recorded_in_progress") else "not recorded"
            print(f"{session_id}  finalized  overall={bundle['scores']['overall']}  {recorded}  [{bundle['standard_version']}]")
        elif state_file(session_id).is_file():
            state = read_json(state_file(session_id))
            print(f"{session_id}  {state['status']}  judgments={len(state['judgments'])}")
        else:
            print(f"{session_id}  unscored")


def cmd_validate(args):
    folder = session_dir(args.session_id)
    bundle_path = folder / "evaluation.json"
    if not bundle_path.is_file():
        fail(f"Session {args.session_id} is not finalized")
    bundle = read_json(bundle_path)
    problems = []

    # Transcript and recording are working material; absence means pruned, not broken.
    transcript = ROOT / bundle["transcript_path"]
    if transcript.is_file() and sha256_file(transcript) != bundle["transcript_sha256"]:
        problems.append(f"{bundle['transcript_path']} no longer matches the hash that was scored")

    if bundle["recording"]:
        recording = ROOT / bundle["recording"]["path"]
        if recording.is_file() and sha256_file(recording) != bundle["recording"]["sha256"]:
            problems.append(f"{bundle['recording']['path']} no longer matches the hash that was scored")

    if work_dir(args.session_id).exists():
        problems.append(".work/ still present in a finalized session")

    validate_scores(bundle["scores"], "evaluation")
    allowed = concept_tags()
    for item in bundle["weaknesses"]:
        if item["tag"] not in allowed:
            problems.append(f"unknown concept tag '{item['tag']}'")

    card = folder / "card.md"
    if not card.is_file():
        problems.append("card.md is missing")
    elif card.read_text(encoding="utf-8") != render_card(bundle):
        problems.append("card.md has drifted from evaluation.json")

    if problems:
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        fail(f"{args.session_id}: {len(problems)} problem(s)")
    print(f"{args.session_id}: OK")


# --- cli --------------------------------------------------------------------


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create a session folder")
    p.add_argument("session_id")
    p.add_argument("--problem", required=True)
    p.add_argument("--difficulty", required=True)
    p.add_argument("--recording")
    p.add_argument("--date")

    p = sub.add_parser("transcribe", help="write the raw transcript into transcripts/")
    p.add_argument("session_id")
    p.add_argument("--from-file", dest="from_file")

    p = sub.add_parser("freeze", help="pin the transcript that will be scored")
    p.add_argument("session_id")
    p.add_argument("--corrected")
    p.add_argument("--clarifications")
    p.add_argument("--excluded")

    p = sub.add_parser("import", help="import a worker model's JSON output")
    p.add_argument("session_id")
    p.add_argument("--kind", required=True, choices=("refinement", "judgment", "adjudication"))
    p.add_argument("--model", required=True)
    p.add_argument("--file", required=True)

    p = sub.add_parser("disputes", help="build the anonymised adjudication packet")
    p.add_argument("session_id")

    p = sub.add_parser("resolve", help="compute the canonical result")
    p.add_argument("session_id")

    p = sub.add_parser("finalize", help="write evaluation.json and card.md, drop .work/")
    p.add_argument("session_id")

    p = sub.add_parser("record", help="append to sessions.jsonl and rewrite STATE.md")
    p.add_argument("session_id")

    p = sub.add_parser("status", help="show session states")
    p.add_argument("session_id", nargs="?")

    p = sub.add_parser("validate", help="check a finalized session for drift")
    p.add_argument("session_id")

    return parser.parse_args()


def main():
    args = parse_args()
    handlers = {
        "init": cmd_init,
        "transcribe": cmd_transcribe,
        "freeze": cmd_freeze,
        "import": cmd_import,
        "disputes": cmd_disputes,
        "resolve": cmd_resolve,
        "finalize": cmd_finalize,
        "record": cmd_record,
        "status": cmd_status,
        "validate": cmd_validate,
    }
    try:
        handlers[args.command](args)
    except SessionError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
