#!/usr/bin/env python3
"""Record accepted design evaluations and derive progress, without workflow state."""

import argparse
from datetime import date
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
STANDARD_VERSION = "single-agent-v1"
DIMENSIONS = {
    "overall": "Overall",
    "requirements_scoping": "Requirements & scoping",
    "capacity_math": "Capacity & back-of-envelope math",
    "api_data_model": "API & data model",
    "architecture": "Core architecture & component choice",
    "scale_reliability": "Scale, reliability & bottlenecks",
    "tradeoffs_communication": "Tradeoff reasoning & communication",
}
DIFFICULTIES = ("basic", "easy", "medium", "hard", "architect")
STAMP = r"\[\d{2,}:[0-5]\d\]"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def input_path(value):
    require(nonempty(value), "Input path must be a nonempty relative path")
    path = Path(value)
    require(not path.is_absolute() and ".." not in path.parts,
            "Input paths must be relative to SystemDesignInterviewerAgent")
    resolved = (ROOT / path).resolve()
    require(resolved.is_relative_to(ROOT.resolve()), "Input path escapes the project")
    return resolved


def validate_evaluation(evaluation, require_transcript=False):
    require(isinstance(evaluation, dict), "Evaluation must be an object")
    fields = {"session_id", "date", "problem", "difficulty", "standard_version",
              "raw_transcript_path", "transcript_path", "scores", "evidence",
              "rationales", "strengths", "weaknesses", "verdict", "notes"}
    require(fields <= evaluation.keys() <= fields | {"recording_path"},
            "Evaluation fields do not match SESSION_FORMAT.md")
    identifier = evaluation["session_id"]
    require(nonempty(identifier) and identifier not in (".", "..")
            and not any(char in identifier for char in "/\\\n\r"), "Invalid session_id")
    require(nonempty(evaluation["date"]), "Date is required")
    require(date.fromisoformat(evaluation["date"]).isoformat() == evaluation["date"],
            "Date must be YYYY-MM-DD")
    require(nonempty(evaluation["problem"]), "Problem is required")
    require(evaluation["difficulty"] in DIFFICULTIES, "Unknown difficulty")
    require(evaluation["standard_version"] == STANDARD_VERSION, "Unknown evaluation method")
    input_path(evaluation["raw_transcript_path"])
    transcript = input_path(evaluation["transcript_path"])
    if "recording_path" in evaluation:
        input_path(evaluation["recording_path"])
    require(not require_transcript or transcript.is_file(), "Final transcript is required to record")
    segments = None
    if transcript.is_file():
        text = transcript.read_text(encoding="utf-8")
        segments = {}
        for match in re.finditer(rf"^({STAMP})\s*(.*?)(?=^{STAMP}|\Z)", text, re.M | re.S):
            segments.setdefault(match[1], []).append(" ".join(match[2].split()))
    for field in ("scores", "evidence", "rationales"):
        require(isinstance(evaluation[field], dict) and set(evaluation[field]) == set(DIMENSIONS),
                f"{field} must contain all seven dimensions")
    for dimension in DIMENSIONS:
        score = evaluation["scores"][dimension]
        require(score is None or type(score) is int and 0 <= score <= 10,
                f"{dimension}: score must be an integer 0-10 or null")
        evidence = evaluation["evidence"][dimension]
        require(isinstance(evidence, list) and bool(evidence) == (score is not None),
                f"{dimension}: evidence must be empty exactly when score is null")
        require(nonempty(evaluation["rationales"][dimension]), f"{dimension}: rationale required")
        for quote in evidence:
            match = re.fullmatch(rf"({STAMP}) (.+)", quote) if isinstance(quote, str) else None
            require(match is not None, "Evidence must be [mm:ss] quote")
            if segments is not None:
                require(any(" ".join(match[2].split()) in segment
                            for segment in segments.get(match[1], [])),
                        f"Quote does not occur at {match[1]} in final transcript")
    for field in ("strengths", "weaknesses"):
        require(isinstance(evaluation[field], list) and 3 <= len(evaluation[field]) <= 5,
                f"{field} must have 3-5 entries")
    require(all(nonempty(item) for item in evaluation["strengths"]), "Strengths must be text")
    rubric = (ROOT / "progress/RUBRIC.md").read_text(encoding="utf-8")
    tags = set(re.findall(r"^\|\s*`([a-z0-9-]+)`\s*\|", rubric, re.M))
    for item in evaluation["weaknesses"]:
        require(isinstance(item, dict) and set(item) == {"tag", "detail"}, "Invalid weakness")
        require(isinstance(item["tag"], str) and item["tag"] in tags, "Unknown weakness tag")
        require(nonempty(item["detail"]), "Weakness detail required")
    require(nonempty(evaluation["verdict"]), "Verdict required")
    require(isinstance(evaluation["notes"], list) and all(nonempty(note) for note in evaluation["notes"]),
            "Notes must be a list of text entries")


def ledger_rows():
    path = ROOT / "progress/sessions.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def ledger_entry(evaluation, attempt):
    return {
        "standard_version": evaluation["standard_version"], "date": evaluation["date"],
        "transcript_stem": evaluation["session_id"], "problem": evaluation["problem"],
        "difficulty": evaluation["difficulty"], "attempt_number": attempt,
        "overall": evaluation["scores"]["overall"],
        "dimensions": {key: value for key, value in evaluation["scores"].items() if key != "overall"},
        "weakness_tags": list(dict.fromkeys(item["tag"] for item in evaluation["weaknesses"])),
    }


def render_card(evaluation):
    lines = [f"# {evaluation['problem']}", "",
             f"Date: {evaluation['date']} | Difficulty: {evaluation['difficulty']}",
             f"Session: {evaluation['session_id']} | Method: {evaluation['standard_version']}", "",
             f"Final transcript: {evaluation['transcript_path']}", ""]
    for dimension, label in DIMENSIONS.items():
        score = evaluation["scores"][dimension]
        lines.extend([f"## {label}: {'null' if score is None else str(score) + '/10'}", "",
                      evaluation["rationales"][dimension], ""])
        lines.extend(f"> {quote}" for quote in evaluation["evidence"][dimension])
        lines.append("")
    lines.extend(["## Strengths", "", *[f"- {text}" for text in evaluation["strengths"]], "",
                  "## Weaknesses", "", *[f"- `{item['tag']}`: {item['detail']}" for item in evaluation["weaknesses"]],
                  "", "## Verdict", "", evaluation["verdict"], "", "## Evidence Notes", "",
                  *[f"- {text}" for text in evaluation["notes"]]])
    return "\n".join(lines).rstrip() + "\n"


def render_state(rows):
    path = ROOT / "progress/STATE.md"
    header = path.read_text(encoding="utf-8").split("**Sessions completed:**")[0] if path.exists() else "# Progress\n"
    lines = [header.rstrip(), "", f"**Sessions completed:** {len(rows)}",
             "**Last 5 overall:** " + (", ".join("null" if row["overall"] is None else str(row["overall"]) for row in rows[-5:]) or "none yet"),
             "**Evaluation standards:** " + (", ".join(sorted({row.get("standard_version", "legacy-unspecified") for row in rows})) or "none yet"),
             "Scores may mix evaluation methods; a score change alone does not establish improvement.", "",
             "## Proficiency matrix", "", "| Dimension | " + " | ".join(DIFFICULTIES) + " |",
             "|---|" + "---|" * len(DIFFICULTIES)]
    for dimension, label in DIMENSIONS.items():
        cells = []
        for rung in DIFFICULTIES:
            values = [row["overall"] if dimension == "overall" else row["dimensions"][dimension]
                      for row in rows if row["difficulty"] == rung]
            values = [value for value in values if value is not None]
            cells.append(f"{sum(values) / len(values):.1f} ({len(values)})" if values else "null")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def record(source):
    evaluation = read_json(source)
    validate_evaluation(evaluation)
    folder = ROOT / "sessions" / evaluation["session_id"]
    destination = folder / "evaluation.json"
    require(Path(source).resolve() != destination.resolve(), "Submit from outside the final session folder")
    if destination.exists():
        require(read_json(destination) == evaluation, "Conflicting evaluation for existing session_id")
    rows = ledger_rows()
    matches = [row for row in rows if row["transcript_stem"] == evaluation["session_id"]]
    require(len(matches) <= 1, "Duplicate session IDs in ledger")
    attempt = matches[0]["attempt_number"] if matches else 1 + sum(row["problem"] == evaluation["problem"] for row in rows)
    entry = ledger_entry(evaluation, attempt)
    if matches:
        require(matches[0] == entry, "Evaluation conflicts with recorded progress")
    else:
        validate_evaluation(evaluation, require_transcript=True)
        rows.append(entry)
    write_text(destination, json.dumps(evaluation, indent=2) + "\n")
    write_text(folder / "card.md", render_card(evaluation))
    write_text(ROOT / "progress/sessions.jsonl", "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows))
    write_text(ROOT / "progress/STATE.md", render_state(rows))
    print("Recorded accepted evaluation" if not matches else "Already recorded; refreshed derived outputs")
    print("Reconcile WEAKNESSES.md once per session: " + ", ".join(entry["weakness_tags"]))


def validate(source):
    evaluation = read_json(source)
    validate_evaluation(evaluation)
    folder = ROOT / "sessions" / evaluation["session_id"]
    require(read_json(folder / "evaluation.json") == evaluation, "Final evaluation differs")
    require((folder / "card.md").read_text(encoding="utf-8") == render_card(evaluation), "Card differs")
    rows = ledger_rows()
    matches = [row for row in rows if row["transcript_stem"] == evaluation["session_id"]]
    require(len(matches) == 1 and matches[0] == ledger_entry(evaluation, matches[0]["attempt_number"]), "Ledger differs")
    require((ROOT / "progress/STATE.md").read_text(encoding="utf-8") == render_state(rows), "Progress summary differs")
    print("Evaluation, card, ledger and summary agree")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("record", "validate"))
    parser.add_argument("evaluation", type=Path)
    args = parser.parse_args()
    try:
        {"record": record, "validate": validate}[args.command](args.evaluation)
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())