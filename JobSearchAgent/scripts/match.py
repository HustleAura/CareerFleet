import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from applications import TRACKER, applied_pairs, read_tracker, tracker_lock, tracker_path
from scan import CLIENTS, collect_company, load_config, markdown, markdown_url, validate_run, write_file, write_run


MODULE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = MODULE_ROOT.parent
RESUME = WORKSPACE / "ResumeAgent" / "resume_base.md"
POLICY = MODULE_ROOT / "MATCHING_POLICY.md"
SCHEMA = MODULE_ROOT / "templates" / "matches.schema.json"
VERSION = "2"
WEIGHTS = {"required_fit": 35, "ownership_domain_fit": 25, "coding_stack_fit": 20,
           "experience_scope_fit": 10, "ai_relevance": 10}
RANKABLE = ("strong_fit", "plausible_fit", "stretch")
DECISIONS = RANKABLE + ("not_recommended", "needs_review", "exploratory", "expired")
JD_FIELDS = ("description", "required", "preferred", "qualifications", "responsibilities")


def load(path):
    def unique_pairs(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError(f"Duplicate JSON field: {name}")
            result[name] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)


def encoded(value):
    return json.dumps(value, indent=2, ensure_ascii=True) + "\n"


def normalized(value):
    return re.sub(r"\s+", " ", value).strip()


def check_numbers(text, quotes):
    pattern = r"(?<![A-Za-z0-9])\d+(?:\.\d+)?(?:[BMK]|%)?\+?(?![A-Za-z0-9])"
    if set(re.findall(pattern, text)) - set(re.findall(pattern, quotes)):
        raise ValueError("Claim contains a number not present in its cited quotes")


def production_language_claim(text):
    return re.search(r"(?:production|professional|industry)\s+(?:experience\s+(?:in|with)\s+)?(?:Python|C\+\+)"
                     r"|(?:Python|C\+\+)\s+(?:production\s+)?(?:services|backends|service code)", text, re.I)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reference(path):
    path = Path(path).resolve()
    return str(path.relative_to(WORKSPACE)) if path.is_relative_to(WORKSPACE) else str(path)


def resolve(path):
    return (WORKSPACE / path).resolve()


def clock(value=None):
    instant = value or datetime.now(timezone.utc)
    if isinstance(instant, str):
        instant = datetime.fromisoformat(instant.replace("Z", "+00:00"))
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("A timezone-aware clock is required")
    return instant.astimezone(timezone.utc)


def evidence_index(text):
    entries = {}
    heading = None
    for line in re.finditer(r"^### ([A-Z][A-Z0-9-]*)(?:[^\n]*)$|^```yaml\n(.*?)^```", text, re.M | re.S):
        if line.group(1):
            heading = line.group(1)
            continue
        block = line.group(2)
        identifier = re.search(r"^id: ([A-Z][A-Z0-9-]*)\s*$", block, re.M)
        source_id = identifier.group(1) if identifier else heading
        heading = None
        if not source_id:
            continue
        if source_id in entries:
            raise ValueError(f"Duplicate resume source ID: {source_id}")
        section = re.search(r"^section: (\w+)$", block, re.M)
        strength = re.search(r"^strength: (\w+)$", block, re.M)
        entries[source_id] = {"raw": block, "section": section.group(1) if section else None,
                              "strength": strength.group(1) if strength else None}
    if not entries or "SKL-01" not in entries:
        raise ValueError("Resume evidence IDs or skill provenance missing")
    return entries


def match_state(job, now):
    if job.get("expired") is True:
        return "expired"
    expiry = job.get("expires_at")
    if expiry:
        try:
            if clock(expiry) <= now:
                return "expired"
        except (ValueError, TypeError):
            return "needs_review"
    if not normalized(str(job.get("description") or "")):
        return "needs_review"
    if job.get("exploratory") is True:
        return "exploratory"
    return None


def canonical_text(job):
    pieces = []
    for field in JD_FIELDS:
        value = job.get(field)
        if isinstance(value, str) and value.strip():
            if not any(normalized(value) in normalized(piece) for piece in pieces):
                pieces.append(value)
    return "\n\n".join(pieces)


def snapshot(run, companies):
    run = Path(run).resolve()
    validate_run(run)
    hashes = {}
    for name in CLIENTS:
        directory = run / name
        if not directory.exists():
            continue
        receipt = load(directory / "receipt.json")
        if receipt["company"] != name:
            raise ValueError("Receipt company differs from source directory")
        for filename in ("receipt.json", "inventory.json", "listings.json", "unresolved.json"):
            hashes[reference(directory / filename)] = digest(directory / filename)
    if (run / "report.md").exists():
        hashes[reference(run / "report.md")] = digest(run / "report.md")
    sources, candidates = {}, []
    for name in companies:
        directory = run / name
        if not directory.exists():
            sources[name] = {"company": name, "status": "not_scanned", "selected_count": 0}
            continue
        sources[name] = load(directory / "receipt.json")
        for job in load(directory / "listings.json"):
            if job.get("key") != f"{name}:{job.get('id')}" or job.get("company") != name:
                raise ValueError("Invalid source identity")
            candidates.append({"job_key": job["key"], "source": job, "matching_text": canonical_text(job)})
    hashes[reference(RESUME)] = digest(RESUME)
    hashes[reference(POLICY)] = digest(POLICY)
    hashes[reference(SCHEMA)] = digest(SCHEMA)
    return sources, candidates, hashes


def safe_parent(parent, run):
    parent = Path(parent).resolve()
    temporary = Path(tempfile.gettempdir()).resolve()
    if not parent.is_relative_to(temporary) or parent == temporary:
        raise ValueError("Matching output must be inside a private system-temp session")
    protected = (Path(run).resolve(), MODULE_ROOT / "runs", WORKSPACE / "ResumeAgent",
                 WORKSPACE / "SystemDesignInterviewerAgent")
    if any(parent == path or parent.is_relative_to(path) for path in protected):
        raise ValueError("Matching outputs must be separate from source runs, resume and interview directories")
    if any(any((ancestor / name / "receipt.json").exists() for name in CLIENTS)
           for ancestor in (parent, *parent.parents)):
        raise ValueError("Matching outputs cannot be nested in any collected source run")
    if any((ancestor / "manifest.json").exists() for ancestor in (parent, *parent.parents)):
        raise ValueError("Do not nest output in an existing matching session")
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    return parent


def prepare(run, output_dir=None, companies=None, now=None, tracker=TRACKER):
    now = clock(now)
    if output_dir is None:
        raise ValueError("Explicit temporary --output-dir required; use start for a fresh session")
    if not Path(run).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise ValueError("Only this session's temporary collection is supported; use start to fetch fresh jobs")
    tracker = tracker_path(tracker)
    applied = applied_pairs(read_tracker(tracker))
    companies = list(dict.fromkeys(companies or CLIENTS))
    if not companies or any(name not in CLIENTS for name in companies):
        raise ValueError("Unknown company")
    sources, candidates, hashes = snapshot(run, companies)
    all_candidates = candidates
    excluded = [item for item in candidates if (item["source"]["company"], item["source"]["id"]) in applied]
    candidates = [item for item in candidates if (item["source"]["company"], item["source"]["id"]) not in applied]
    evidence = evidence_index(RESUME.read_text(encoding="utf-8"))
    parent = safe_parent(output_dir, run)
    staging = Path(tempfile.mkdtemp(prefix=".matching-", dir=parent))
    destination = parent / f"{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    manifest = {"schema_version": VERSION, "policy_version": VERSION, "run": reference(run),
                "companies": companies, "prepared_at": now.isoformat(), "sources": sources,
                "tracker": str(tracker), "excluded_job_keys": sorted(item["job_key"] for item in excluded),
                "listed_counts": {name: sum(item["source"]["company"] == name for item in all_candidates)
                                  for name in companies},
                "input_counts": {name: sum(item["source"]["company"] == name for item in candidates)
                                 for name in companies}, "input_hashes": hashes, "weights": WEIGHTS}
    try:
        for filename, value in (("manifest.json", manifest), ("candidates.json", candidates),
                                ("evidence.json", evidence), ("assessments.json", [])):
            write_file(staging / filename, encoded(value))
        if snapshot(run, companies) != (sources, all_candidates, hashes):
            raise ValueError("Inputs changed during preparation")
        if destination.exists():
            raise FileExistsError("Matching destination already exists")
        staging.rename(destination)
        return destination
    except BaseException:
        shutil.rmtree(staging)
        raise


def check_shape(value, schema, root=None, label="assessment"):
    root = root or schema
    if "$ref" in schema:
        return check_shape(value, root["$defs"][schema["$ref"].split("/")[-1]], root, label)
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
    if "type" in schema and type(value) is not types[schema["type"]]:
        raise ValueError(f"{label}: expected {schema['type']}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{label}: invalid enum")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        if set(schema.get("required", [])) - set(value):
            raise ValueError(f"{label}: missing fields")
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            raise ValueError(f"{label}: unknown fields {set(value) - set(properties)}")
        for name, item in value.items():
            if name in properties:
                check_shape(item, properties[name], root, f"{label}.{name}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ValueError(f"{label}: too few items")
        if schema.get("uniqueItems") and len({encoded(item) for item in value}) != len(value):
            raise ValueError(f"{label}: duplicate items")
        for item in value:
            check_shape(item, schema.get("items", {}), root, label)
    if isinstance(value, str) and len(value.strip()) < schema.get("minLength", 0):
        raise ValueError(f"{label}: empty text")
    if type(value) is int and not schema.get("minimum", value) <= value <= schema.get("maximum", value):
        raise ValueError(f"{label}: out of range")


def usable_text(entry):
    fields = re.split(r"(?=^[a-z_]+:)", entry["raw"], flags=re.M)
    allowed = []
    for field in fields:
        name = field.split(":", 1)[0]
        if name not in ("bullet", "metrics", "scope", "tech", "variants", "provenance", "degree", "items", "categories"):
            continue
        if name == "bullet" and "attribution_warning:" in entry["raw"]:
            continue
        if name == "variants":
            field = "\n".join(part for part in re.split(r"(?=^  - text:)", field, flags=re.M)
                              if not re.search(r"^    retired: true", part, re.M))
        field = "\n".join(line for line in field.splitlines()
                          if not any(marker in line for marker in ("DO NOT PUBLISH", "CONTEXT ONLY", "attribution_warning:", "afd_note:", "incident_note:")))
        allowed.append(field)
    return normalized("\n".join(allowed))


def validate_record(record, candidate, evidence, now, schema=None):
    check_shape(record, schema or load(SCHEMA))
    job = candidate["source"]
    if record["job_key"] != candidate["job_key"]:
        raise ValueError("Assessment key differs from candidate")
    forced = match_state(job, now)
    if forced and record["decision"] != forced:
        raise ValueError(f"{job['key']}: source requires {forced}")
    if record["decision"] in ("expired", "exploratory") and forced != record["decision"]:
        raise ValueError("Expired/exploratory decisions require source evidence")
    requirements = {item["id"]: item for item in record["requirements"]}
    if len(requirements) != len(record["requirements"]):
        raise ValueError("Duplicate requirement IDs")
    if not requirements and forced is None:
        raise ValueError("A usable JD requires an evidence-anchored disposition")
    for requirement in requirements.values():
        text = job.get(requirement["source_field"])
        if not isinstance(text, str) or normalized(requirement["jd_quote"]) not in normalized(text):
            raise ValueError("JD quote is not in its source field")
        positive = requirement["evidence_status"] in ("supported", "transferable")
        if requirement["evidence_status"] == "supported" and production_language_claim(requirement["jd_quote"]):
            alternative = requirement["relation"]["type"] == "any" and re.search(r"C#|\.NET", requirement["jd_quote"], re.I)
            if not alternative:
                raise ValueError("Production Python/C++ requirement is not directly supported by the current resume")
        if positive and not requirement["evidence"]:
            raise ValueError("Positive support needs resume evidence")
        if requirement["evidence_status"] == "undocumented" and requirement["evidence"]:
            raise ValueError("Undocumented requirements must not invent evidence")
        for link in requirement["evidence"]:
            entry = evidence.get(link["source_id"])
            if not entry or normalized(link["resume_quote"]) not in normalized(entry["raw"]):
                raise ValueError("Unknown resume source or mismatched quote")
            check_numbers(link["explanation"], requirement["jd_quote"] + " " + link["resume_quote"])
            if positive:
                if entry["strength"] == "weak" or normalized(link["resume_quote"]) not in usable_text(entry):
                    raise ValueError("Weak, retired, restricted or non-evidentiary text cannot affirm support")
                if link["scope"] == "professional" and entry["section"] != "experience":
                    raise ValueError("Professional evidence must come from an experience entry")
                if link["capability"] in ("production_python", "production_cpp"):
                    raise ValueError("Current resume does not document production Python/C++")
                if link["source_id"] == "SKL-01" and link["scope"] not in ("skills", "tooling", "competitive"):
                    raise ValueError("Skills provenance cannot establish production tenure")
    for gap in record["gaps"]:
        if gap["requirement_id"] not in requirements:
            raise ValueError("Gap references an unknown requirement")
        requirement = requirements[gap["requirement_id"]]
        if gap["kind"] == "preferred_only" and requirement["importance"] != "preferred":
            raise ValueError("Required gaps cannot be labelled preferred-only")
        if gap["kind"] == "unmet_minimum" and record["decision"] in RANKABLE[:2]:
            raise ValueError("Unmet minimum requires stretch or review, not strong/plausible")
    for requirement in requirements.values():
        if requirement["importance"] == "required" and requirement["evidence_status"] in ("contradicted", "undocumented"):
            if not any(gap["requirement_id"] == requirement["id"] for gap in record["gaps"]):
                raise ValueError("Unsupported mandatory requirement needs an explicit gap")
            if requirement["evidence_status"] == "contradicted" and record["decision"] in RANKABLE[:2]:
                raise ValueError("Contradicted mandatory requirement cannot be strong/plausible")
    for dimension, grade in record["grades"].items():
        if any(identifier not in requirements for identifier in grade["requirement_ids"]):
            raise ValueError("Grade references an unknown requirement")
        if grade["value"] and not grade["requirement_ids"]:
            raise ValueError("Nonzero grade needs requirement references")
        if dimension != "ai_relevance" and grade["value"] >= 2:
            if not any(requirements[identifier]["evidence_status"] in ("supported", "transferable")
                       for identifier in grade["requirement_ids"]):
                raise ValueError("Positive candidate grade lacks usable support")
            if grade["value"] >= 3 and not any(requirements[identifier]["evidence_status"] == "supported"
                                               for identifier in grade["requirement_ids"]):
                raise ValueError("Direct grade requires direct evidence, not only transferability")
    for claim in [record["summary"], *record["reasons_to_apply"]]:
        if any(identifier not in requirements for identifier in claim["requirement_ids"]):
            raise ValueError("Claim references an unknown requirement")
        if record["decision"] in RANKABLE and not claim["requirement_ids"]:
            raise ValueError("Recommendation claims need evidence references")
        quoted = " ".join(requirements[identifier]["jd_quote"] + " " + " ".join(
            link["resume_quote"] for link in requirements[identifier]["evidence"])
            for identifier in claim["requirement_ids"])
        check_numbers(claim["text"], quoted)
    if record["decision"] in RANKABLE:
        if record["role_scope_fit"] not in ("direct", "transferable"):
            raise ValueError("Fundamental/unknown role scope cannot rank")
        if any(gap["kind"] == "fundamental" for gap in record["gaps"]):
            raise ValueError("Fundamental mismatch cannot rank")
        if not record["reasons_to_apply"]:
            raise ValueError("Rankable roles need reasons to apply")
        professional = any(link["scope"] == "professional" and link["source_id"] != "EXP-MSFT-01"
                           and evidence[link["source_id"]]["strength"] in ("strong", "medium")
                           for requirement in requirements.values()
                           if requirement["evidence_status"] in ("supported", "transferable")
                           for link in requirement["evidence"])
        if not professional or any(record["grades"][name]["value"] < 2 for name in ("ownership_domain_fit", "coding_stack_fit")):
            raise ValueError("Recommendation lacks substantive professional/core engineering relevance")
        if record["decision"] == "stretch" and not record["gaps"]:
            raise ValueError("Stretch must name its risk")
    return record


def session_inputs(session):
    session = Path(session).resolve()
    manifest = load(session / "manifest.json")
    if manifest.get("schema_version") != VERSION or manifest.get("policy_version") != VERSION or manifest.get("weights") != WEIGHTS:
        raise ValueError("Unsupported session/policy version or weights")
    companies = manifest["companies"]
    if not isinstance(companies, list) or not companies or len(companies) != len(set(companies)) or any(name not in CLIENTS for name in companies):
        raise ValueError("Invalid manifest companies")
    clock(manifest["prepared_at"])
    sources, expected, hashes = snapshot(resolve(manifest["run"]), companies)
    if hashes != manifest["input_hashes"] or sources != manifest["sources"]:
        raise ValueError("Inputs changed or missing; prepare a new session")
    if "tracker" not in manifest or "excluded_job_keys" not in manifest:
        raise ValueError("Old saved sessions are not supported; start a fresh collection")
    current_applied = applied_pairs(read_tracker(manifest["tracker"]))
    excluded = manifest["excluded_job_keys"]
    if not isinstance(excluded, list) or any(not isinstance(key, str) for key in excluded) or len(excluded) != len(set(excluded)):
        raise ValueError("Invalid excluded job keys")
    if not set(excluded) <= {item["job_key"] for item in expected}:
        raise ValueError("Applied exclusions must refer to this collection")
    if any((item["source"]["company"], item["source"]["id"]) not in current_applied
           for item in expected if item["job_key"] in excluded):
        raise ValueError("Excluded job is not in the applied tracker; start a new session if history changed")
    if manifest["listed_counts"] != {name: sum(item["source"]["company"] == name for item in expected) for name in companies}:
        raise ValueError("Listed counts differ from source")
    expected = [item for item in expected if item["job_key"] not in excluded]
    candidates = load(session / "candidates.json")
    evidence = evidence_index(RESUME.read_text(encoding="utf-8"))
    if candidates != expected or load(session / "evidence.json") != evidence:
        raise ValueError("Candidate/evidence bundle differs from original inputs")
    if manifest["input_counts"] != {name: sum(item["source"]["company"] == name for item in expected) for name in companies}:
        raise ValueError("Manifest counts differ from listings")
    return manifest, {item["job_key"]: item for item in candidates}, evidence


def validate_records(records, candidates, evidence, now, complete=False):
    if not isinstance(records, list):
        raise ValueError("Assessments must be an array")
    seen = set()
    schema = load(SCHEMA)
    for record in records:
        check_shape(record, schema)
        key = record["job_key"]
        if key in seen or key not in candidates:
            raise ValueError("Unknown or duplicate assessment key")
        seen.add(key)
        validate_record(record, candidates[key], evidence, now, schema)
    if complete and seen != set(candidates):
        raise ValueError(f"Incomplete assessments: {len(seen)}/{len(candidates)}")
    return seen


def validate(session, complete=False, now=None):
    manifest, candidates, evidence = session_inputs(session)
    applied = applied_pairs(read_tracker(manifest["tracker"]))
    records = load(Path(session) / "assessments.json")
    session = Path(session)
    finalized = (session / "receipt.json").exists()
    instant = clock(now)
    if finalized:
        receipt = load(session / "receipt.json")
        instant = clock(receipt["finalized_at"])
        if receipt["input_hashes"] != manifest["input_hashes"] or receipt["assessment_sha256"] != digest(session / "assessments.json"):
            raise ValueError("Final receipt inputs/assessments changed")
        if receipt["output_hashes"] != {name: digest(session / name) for name in ("selections.json", "shortlist.md")}:
            raise ValueError("Final output hashes changed")
        output = selection_output(manifest, candidates, records, instant, applied)
        if output != load(session / "selections.json") or render_shortlist(output, candidates) != (session / "shortlist.md").read_text(encoding="utf-8"):
            raise ValueError("Final outputs differ from deterministic selection/rendering")
        if receipt.get("assessment_complete") is not True or receipt.get("assessed_count") != len(records):
            raise ValueError("Invalid final receipt coverage")
        expected_companies = {name: {field: value[field] for field in ("source_status", "assessed_count", "selected_count", "provisional")}
                              for name, value in output["companies"].items()}
        if receipt.get("companies") != expected_companies or receipt.get("schema_version") != VERSION:
            raise ValueError("Invalid final receipt summary")
    elif any((session / name).exists() for name in ("selections.json", "shortlist.md")):
        raise ValueError("Incomplete final output transaction; do not treat as finalized")
    seen = validate_records(records, candidates, evidence, instant, complete or finalized)
    return {"assessed": len(seen), "total": len(candidates), "complete": seen == set(candidates),
            "listed": sum(manifest["listed_counts"].values()), "excluded_before_assessment": len(manifest["excluded_job_keys"]),
            "finalized": finalized, "expiry_checked_at": instant.isoformat(),
            "remaining_keys": sorted(set(candidates) - seen), "source_statuses": {
                name: source["status"] for name, source in manifest["sources"].items()}}


def ingest(session, batch, now=None):
    session = Path(session).resolve()
    if any((session / name).exists() for name in ("receipt.json", "selections.json", "shortlist.md")):
        raise ValueError("Final outputs are immutable; prepare a new session")
    lock = session / ".write-lock"
    lock.mkdir(mode=0o700)
    temporary = session / f".assessments-{uuid4().hex}.json"
    try:
        if any((session / name).exists() for name in ("receipt.json", "selections.json", "shortlist.md")):
            raise ValueError("Final outputs are immutable; prepare a new session")
        _, candidates, evidence = session_inputs(session)
        records = load(session / "assessments.json")
        validate_records(records, candidates, evidence, clock(now))
        validate_records(batch, candidates, evidence, clock(now))
        merged = {item["job_key"]: item for item in records}
        merged.update({item["job_key"]: item for item in batch})
        records = [merged[key] for key in sorted(merged)]
        validate_records(records, candidates, evidence, clock(now))
        write_file(temporary, encoded(records))
        session_inputs(session)
        os.replace(temporary, session / "assessments.json")
        return {"assessed": len(records), "total": len(candidates)}
    finally:
        temporary.unlink(missing_ok=True)
        lock.rmdir()


def relevance(record):
    return sum(weight * record["grades"][name]["value"] for name, weight in WEIGHTS.items()) / 4


def opportunity(job):
    field = {"rubrik": "requisition_id", "apple": "position_id"}.get(job["company"])
    identity = job.get(field) if field else None
    return (job["company"], field, str(identity)) if identity else (job["company"], "key", job["key"])


def select(records, candidates, companies, applied=()):
    ordered = sorted((record for record in records if record["decision"] in RANKABLE
                      and (candidates[record["job_key"]]["source"]["company"], candidates[record["job_key"]]["source"]["id"]) not in applied),
                     key=lambda record: (-relevance(record), RANKABLE.index(record["decision"]), record["job_key"]))
    selected = {name: [] for name in companies}
    seen = set()
    for record in ordered:
        job = candidates[record["job_key"]]["source"]
        identity = opportunity(job)
        if identity not in seen and len(selected[job["company"]]) < 3:
            selected[job["company"]].append(record)
            seen.add(identity)
    return selected


def fetch_age(value, now):
    try:
        return round((now - clock(value)).total_seconds() / 86400, 2) if value else None
    except (ValueError, TypeError):
        return None


def selection_output(manifest, candidates, records, now, applied=()):
    selected = select(records, candidates, manifest["companies"], applied)
    by_key = {record["job_key"]: record for record in records}
    companies = {}
    for name in manifest["companies"]:
        source = manifest["sources"][name]
        rows = [item["source"] for item in candidates.values() if item["source"]["company"] == name]
        provisional = source["status"] != "complete" or not source.get("inventory_complete") or not source.get("details_complete")
        recommendations = []
        for rank, record in enumerate(selected[name], 1):
            job = candidates[record["job_key"]]["source"]
            variants = [row for row in rows if opportunity(row) == opportunity(job) and (name, row["id"]) not in applied]
            gaps = sorted(record["gaps"], key=lambda gap: (
                gap["kind"] != "unmet_minimum", gap["severity"] != "major", gap["kind"] == "preferred_only"))
            warnings = list(dict.fromkeys(job.get("warnings", []) + record["source_warnings"]))
            if len(variants) == 1 and any(row["title"] == job["title"] and row["key"] != job["key"] for row in rows):
                warnings.append("Same title appears on other source IDs; no verified shared identity, retained separately.")
            recommendations.append({"rank": rank, "job_key": job["key"], "title": job["title"],
                "url": job["url"], "cities": job["cities"], "decision": record["decision"],
                "relevance_index": relevance(record), "summary": record["summary"],
                "reasons_to_apply": record["reasons_to_apply"], "gaps": gaps,
                "largest_required_gap": next((gap["explanation"] for gap in gaps if gap["kind"] != "preferred_only"), "No unmet required minimum identified; undocumented eligibility may remain."),
                "source_ids": sorted({link["source_id"] for requirement in record["requirements"] for link in requirement["evidence"]}),
                "ai_relevance": record["grades"]["ai_relevance"], "warnings": warnings,
                "fetched_at": job.get("fetched_at"), "fetch_age_days": fetch_age(job.get("fetched_at"), now),
                "requirements": record["requirements"], "audit": record["audit"],
                "grouped_links": [{"job_key": row["key"], "url": row["url"], "cities": row["cities"],
                                   "decision": by_key[row["key"]]["decision"], "warnings": row.get("warnings", [])}
                                  for row in variants]})
        companies[name] = {"source_status": source["status"], "inventory_complete": source.get("inventory_complete", False),
            "listed_count": manifest["listed_counts"][name],
            "previously_applied": sorted([key for key in manifest["excluded_job_keys"] if key.startswith(name + ":")]
                                         + [row["key"] for row in rows if (name, row["id"]) in applied]),
            "details_complete": source.get("details_complete", False), "fetched_at": source.get("started_at"),
            "fetch_age_days": fetch_age(source.get("started_at"), now), "source_warnings": source.get("warnings", []),
            "source_errors": source.get("errors", []), "unresolved_location_count": source.get("unresolved_location_count", 0),
            "role_excluded_count": source.get("role_excluded_count", 0),
            "role_unresolved_count": source.get("role_unresolved_count", 0),
            "title_excluded_count": source.get("title_excluded_count", 0),
            "title_unresolved_count": source.get("title_unresolved_count", 0),
            "input_count": len(rows), "assessed_count": sum(row["key"] in by_key for row in rows),
            "selected_count": len(recommendations), "provisional": bool(provisional), "recommendations": recommendations,
            "needs_review": [row["key"] for row in rows if by_key[row["key"]]["decision"] == "needs_review" and (name, row["id"]) not in applied],
            "exploratory": [row["key"] for row in rows if by_key[row["key"]]["decision"] == "exploratory" and (name, row["id"]) not in applied]}
    return {"schema_version": VERSION, "policy_version": VERSION, "source_run": manifest["run"],
            "finalized_at": now.isoformat(), "companies": companies}


def render_shortlist(output, candidates):
    lines = ["# Session Matches", "", f"Temporary source: {markdown(output['source_run'])}",
             f"Matched at: {output['finalized_at']}", "",
             "Based on this session's collection. No known expiry is not proof of availability.",
             "Relevance indices are prioritization heuristics, not ATS scores or hiring probabilities.",
             "No tailoring or applications performed. Evidence checks do not replace semantic judgment.", ""]
    for name, company in output["companies"].items():
        label = " (PROVISIONAL: best among assessed collected jobs)" if company["provisional"] and company["input_count"] else ""
        lines.extend([f"## {name}{label}", "", f"Source: **{company['source_status']}**. "
            f"Inventory complete: {company['inventory_complete']}; details complete: {company['details_complete']}; "
            f"unresolved locations: {company['unresolved_location_count']}.",
            f"Fetched: {company['fetched_at'] or 'not available'}; age: {company['fetch_age_days']} days.",
            f"Listed: {company['listed_count']}; previously applied: {len(company['previously_applied'])}.",
            f"Role exclusions: {company['role_excluded_count']}; ambiguous roles: {company['role_unresolved_count']}; "
            f"all title exclusions: {company['title_excluded_count']}; ambiguous titles: {company['title_unresolved_count']}.",
            f"Assessed: {company['assessed_count']}/{company['input_count']} collected listings; selected: {company['selected_count']}.", ""])
        for warning in company["source_errors"] + company["source_warnings"]:
            lines.append("- " + markdown(warning))
        if company["previously_applied"]:
            lines.append("Excluded applied IDs: " + ", ".join(company["previously_applied"]))
        if not company["recommendations"]:
            lines.append("\nNo recommendations from these inputs. A blocked or missing source does not mean zero openings.")
        for job in company["recommendations"]:
            lines.extend(["", f"### {job['rank']}. [{markdown(job['title'])}]({markdown_url(job['url'])})", "",
                          f"{markdown(job['job_key'])} | {markdown(', '.join(job['cities']))} | **{job['decision']}** | index {job['relevance_index']:g}/100",
                          f"Fetched: {job['fetched_at']}; age: {job['fetch_age_days']} days.", "",
                          markdown(job["summary"]["text"]), "",
                          "**Largest required risk:** " + markdown(job["largest_required_gap"]), ""])
            for reason in job["reasons_to_apply"]:
                lines.append("- " + markdown(reason["text"]) + " [" + ", ".join(reason["requirement_ids"]) + "]")
            lines.append(f"\nAI relevance: {job['ai_relevance']['value']}/4. {markdown(job['ai_relevance']['explanation'])}")
            lines.append("Evidence IDs: " + ", ".join(job["source_ids"]))
            for gap in job["gaps"]:
                lines.append(f"- Gap ({gap['kind']}, {gap['severity']}): {markdown(gap['explanation'])}")
            for warning in job["warnings"]:
                lines.append("- Warning: " + markdown(warning))
            if len(job["grouped_links"]) > 1:
                for variant in job["grouped_links"]:
                    lines.append(f"- Same verified opportunity: [{markdown(variant['job_key'])}]({markdown_url(variant['url'])}), "
                                 f"{markdown(', '.join(variant['cities']))}; {variant['decision']}; {markdown('; '.join(variant['warnings']))}")
            lines.extend(["", "#### Evidence Audit", ""])
            for requirement in job["requirements"]:
                lines.append(f"- {markdown(requirement['id'])} ({requirement['importance']}, {requirement['evidence_status']}), "
                             f"{requirement['source_field']}: \"{markdown(requirement['jd_quote'])}\"")
                for link in requirement["evidence"]:
                    lines.append(f"  {link['source_id']} ({link['scope']}): \"{markdown(link['resume_quote'])}\". {markdown(link['explanation'])}")
            lines.append("\nAudit: " + markdown(job["audit"]["notes"]))
        for category in ("needs_review", "exploratory"):
            if company[category]:
                lines.extend(["", "### " + category.replace("_", " ").title(), ""])
                for key in company[category]:
                    job = candidates[key]["source"]
                    lines.append(f"- [{markdown(job['title'])}]({markdown_url(job['url'])}) ({markdown(key)})")
    lines.extend(["", "All dispositions and grade rationales remain in assessments.json. Inputs remain unchanged.", ""])
    return "\n".join(lines)


def finalize(session, now=None):
    manifest, _, _ = session_inputs(session)
    with tracker_lock(manifest["tracker"]):
        applied = applied_pairs(read_tracker(manifest["tracker"]))
        return finalize_locked(session, now, applied)


def finalize_locked(session, now, applied):
    session = Path(session).resolve()
    now = clock(now)
    names = ("selections.json", "shortlist.md", "receipt.json")
    if any((session / name).exists() for name in names):
        raise ValueError("Final outputs already exist; never overwrite them")
    lock = session / ".write-lock"
    lock.mkdir(mode=0o700)
    staging = None
    installed = []
    try:
        manifest, candidates, evidence = session_inputs(session)
        records = load(session / "assessments.json")
        validate_records(records, candidates, evidence, now, complete=True)
        output = selection_output(manifest, candidates, records, now, applied)
        for company in output["companies"].values():
            if any(not record["audit"]["reviewed"] for record in company["recommendations"]):
                raise ValueError("Selected recommendations require a direct semantic evidence audit")
        staging = Path(tempfile.mkdtemp(prefix=".finalize-", dir=session))
        write_file(staging / "selections.json", encoded(output))
        write_file(staging / "shortlist.md", render_shortlist(output, candidates))
        receipt = {"schema_version": VERSION, "finalized_at": now.isoformat(), "assessment_complete": True,
                   "assessed_count": len(records), "input_hashes": manifest["input_hashes"],
                   "assessment_sha256": digest(session / "assessments.json"),
                   "output_hashes": {name: digest(staging / name) for name in names[:2]},
                   "companies": {name: {field: value[field] for field in ("source_status", "assessed_count", "selected_count", "provisional")}
                                 for name, value in output["companies"].items()}}
        write_file(staging / "receipt.json", encoded(receipt))
        session_inputs(session)
        for name in names:
            os.link(staging / name, session / name)
            installed.append(session / name)
        return session / "shortlist.md"
    except BaseException:
        for path in installed:
            path.unlink()
        raise
    finally:
        if staging is not None:
            shutil.rmtree(staging)
        lock.rmdir()


def start(companies=None, tracker=TRACKER):
    tracker = tracker_path(tracker)
    read_tracker(tracker)
    companies = list(dict.fromkeys(companies or CLIENTS))
    if not companies or any(name not in CLIENTS for name in companies):
        raise ValueError("Unknown company")
    config = load_config(MODULE_ROOT / "search_config.json")
    root = Path(tempfile.mkdtemp(prefix="careerfleet-jobs-")).resolve()
    try:
        write_file(root / ".careerfleet-session.json", encoded({"tracker": str(tracker)}))
        results = []
        for name in companies:
            print(f"Collecting {name}...", file=sys.stderr)
            results.append(collect_company(name, config))
        run = write_run(results, root / "collection")
        session = prepare(run, root / "matching", companies, tracker=tracker)
        progress = validate(session)
        return {"root": str(root), "run": str(run), "session": str(session), **progress}
    except BaseException:
        shutil.rmtree(root)
        raise


def cleanup(root, recorded=()):
    root = Path(root).absolute()
    if root.is_symlink():
        raise ValueError("Refusing to clean a symlink")
    root = root.resolve()
    if root.parent != Path(tempfile.gettempdir()).resolve() or not root.name.startswith("careerfleet-jobs-"):
        raise ValueError("Cleanup requires the exact owned system-temp session root")
    if root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o777 != 0o700:
        raise ValueError("Session root ownership/permissions differ")
    if any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError("Unexpected symlink in session; inspect before cleanup")
    marker = load(root / ".careerfleet-session.json")
    if not isinstance(marker, dict) or set(marker) != {"tracker"}:
        raise ValueError("Invalid session ownership marker")
    tracker = tracker_path(marker["tracker"])
    if tracker.is_relative_to(root):
        raise ValueError("Never delete the applied tracker during session cleanup")
    with tracker_lock(tracker):
        pairs = applied_pairs(read_tracker(tracker))
        for key in recorded:
            if tuple(key.split(":", 1)) not in pairs:
                raise ValueError(f"Application {key} is not recorded; keep session files and retry recording")
        shutil.rmtree(root)
    return {"cleaned": str(root), "tracker_preserved": str(tracker)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evidence-based matching within a temporary job-search session.")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("start", help="Fetch fresh listings and prepare temporary un-applied candidates")
    command.add_argument("--company", action="append", choices=CLIENTS)
    command.add_argument("--tracker", type=Path, default=TRACKER)
    command = commands.add_parser("cleanup", help="Remove only this session's temporary files after recording applications")
    command.add_argument("root", type=Path)
    command.add_argument("--recorded", action="append", default=[], metavar="COMPANY:JOBID")
    command = commands.add_parser("prepare")
    command.add_argument("--run", type=Path, required=True)
    command.add_argument("--output-dir", type=Path, required=True)
    command.add_argument("--tracker", type=Path, default=TRACKER)
    command.add_argument("--company", action="append", choices=CLIENTS)
    command = commands.add_parser("validate")
    command.add_argument("session", type=Path)
    command.add_argument("--complete", action="store_true")
    command.add_argument("--batch", type=Path, help="Validate and atomically ingest this assessment array")
    command = commands.add_parser("finalize")
    command.add_argument("session", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            result = start(args.company, args.tracker)
            print(encoded(result))
            return 0 if all(value == "complete" for value in result["source_statuses"].values()) else 2
        elif args.command == "cleanup":
            print(encoded(cleanup(args.root, args.recorded)))
        elif args.command == "prepare":
            print(prepare(args.run, args.output_dir, args.company, tracker=args.tracker))
        elif args.command == "validate":
            if args.batch:
                print(encoded(ingest(args.session, load(args.batch))))
            print(encoded(validate(args.session, args.complete)))
        elif args.command == "finalize":
            print(finalize(args.session))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())