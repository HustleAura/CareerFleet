import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from time import monotonic
from uuid import uuid4

import adobe
import amazon
import apple
import arcesium
import atlassian
import databricks
import deshaw_india
import intuit
import microsoft
import rippling
import rubrik
import salesforce
import snowflake
import stripe
import uber
from common import CollectionCancelled, HttpClient, ScanResult, SUPPORTED_COMPANIES, TARGET_CITIES, city_keys, collection_summary
from roles import classify_title, validate_role_policy


MODULE_ROOT = Path(__file__).resolve().parents[1]
CLIENTS = {
    "rubrik": rubrik, "amazon": amazon, "deshaw_india": deshaw_india, "uber": uber,
    "apple": apple, "stripe": stripe, "databricks": databricks, "snowflake": snowflake,
    "rippling": rippling, "arcesium": arcesium, "atlassian": atlassian,
    "salesforce": salesforce, "adobe": adobe, "microsoft": microsoft, "intuit": intuit,
}
DEFAULT_WORKERS = len(CLIENTS)


def validate_workers(workers):
    if type(workers) is not int or not 1 <= workers <= len(CLIENTS):
        raise ValueError(f"workers must be an integer between 1 and {len(CLIENTS)}")
    return workers


def load_config(path):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_role_policy(config.get("role_filter"))
    if config.get("country") != "India":
        raise ValueError("Only India is supported")
    cities = config.get("cities")
    if not isinstance(cities, list) or not cities or any(city not in TARGET_CITIES for city in cities) or len(set(cities)) != len(cities):
        raise ValueError("cities must be a nonempty unique subset of Hyderabad and Bengaluru")
    companies = config.get("companies")
    if not isinstance(companies, dict) or set(companies) != set(SUPPORTED_COMPANIES):
        raise ValueError("Configuration must name exactly the supported companies")
    for name, entry in companies.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("enabled"), bool):
            raise ValueError(f"{name}: enabled must be a boolean")
        if entry.get("access") not in ("public_feed", "public_endpoint", "personal_use", "review_needed", "permission_required", "approved"):
            raise ValueError(f"{name}: unrecognized access status")
        if entry.get("access") == "approved" and not str(entry.get("approval_reference", "")).strip():
            raise ValueError(f"{name}: approved access requires an approval_reference")
    microsoft.validate_max_requests(companies["microsoft"].get("max_requests", microsoft.DEFAULT_MAX_REQUESTS))
    return config


def collect_company(name, config, http_factory=HttpClient):
    if name not in CLIENTS:
        raise ValueError("Unknown collection company")
    entry = config["companies"][name]
    result = ScanResult(name, config["cities"], config["role_filter"])
    if name == "microsoft":
        result.collection = microsoft.collection_metadata(entry.get("max_requests", microsoft.DEFAULT_MAX_REQUESTS))
    result.warnings.append(entry.get("note", ""))
    if entry["access"] == "permission_required":
        result.access_status = "blocked"
        result.errors.append("Automated access requires an applicable permission; no network request made")
        return result.finish()
    if not entry["enabled"]:
        result.access_status = "disabled"
        return result.finish()
    try:
        http = http_factory(CLIENTS[name].HOSTS)
        if name == "microsoft":
            microsoft.collect(http, result, max_requests=result.collection["request_limit"])
        else:
            CLIENTS[name].collect(http, result)
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError, OSError) as error:
        result.errors.append(f"{type(error).__name__}: {error}")
    return result.finish()


def collect_companies(names, config, *, workers=DEFAULT_WORKERS):
    workers = validate_workers(workers)
    names = list(dict.fromkeys(names))
    if not names or any(name not in CLIENTS for name in names):
        raise ValueError("Collection requires a nonempty set of supported companies")
    config = deepcopy(config)
    workers = min(workers, len(names))
    cancelled = Event()
    started = monotonic()
    order = {name: index for index, name in enumerate(names)}
    pending = iter(names)
    active = {}
    results = {}
    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="careerfleet-company")

    def client_factory(hosts):
        return HttpClient(hosts, cancel_event=cancelled)

    def submit_next():
        name = next(pending, None)
        if name is not None:
            print(f"Collecting {name}...", file=sys.stderr, flush=True)
            active[executor.submit(collect_company, name, config, client_factory)] = name

    try:
        for unused in range(workers):
            submit_next()
        while active:
            finished, unused = wait(active, return_when=FIRST_COMPLETED)
            for future in sorted(finished, key=lambda item: order[active[item]]):
                name = active.pop(future)
                result = future.result()
                receipt = result.receipt()
                if result.company != name:
                    raise ValueError("Worker returned a different company's results")
                validate_payload(receipt, result.inventory(), result.unresolved(), result.selected())
                results[name] = result
                print(f"Finished {name}: {receipt['status']} ({result.elapsed_seconds:.3f}s)",
                      file=sys.stderr, flush=True)
            for unused in finished:
                submit_next()
    except BaseException:
        cancelled.set()
        for future in active:
            future.cancel()
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=cancelled.is_set())
    print(f"Collection elapsed: {monotonic() - started:.3f}s; company workers: {workers}",
          file=sys.stderr, flush=True)
    return [results[name] for name in names]


def markdown(value):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return re.sub(r"([\\`*_{}\[\]<>|])", r"\\\1", text)


def markdown_url(url):
    for original, replacement in ((" ", "%20"), ("(", "%28"), (")", "%29"), ("[", "%5B"), ("]", "%5D")):
        url = url.replace(original, replacement)
    return url


def report(results):
    cities = sorted({city for result in results for city in result.cities})
    lines = ["# Job Search", "", f"India: {', '.join(cities)}. Software-engineering roles only; Amazon requires SDE II; Microsoft uses exact Software Engineer II/2 titles.", "",
             "Counts describe public source postings at fetch time, not a guarantee of active hiring.", "",
             "| Company | Status | Source IDs | City-scoped | Shown | Unresolved locations |",
             "|---|---|---:|---:|---:|---:|"]
    for result in results:
        receipt = result.receipt()
        lines.append(f"| {result.company} | {receipt['status']} | {receipt['source_unique_count']} | {receipt['in_scope_count']} | {receipt['selected_count']} | {receipt['unresolved_location_count']} |")
    for result in results:
        receipt = result.receipt()
        lines.extend(["", f"## {result.company}", "", f"Fetched: {result.started_at}", ""])
        if "collection" in receipt:
            lines.extend([collection_summary(receipt["collection"]), "",
                          "Completeness applies only to the declared query, not all company openings.", ""])
        for message in result.warnings + result.errors:
            if message:
                lines.append("- " + markdown(message))
        lines.extend(["", f"Inventory complete: {receipt['inventory_complete']}; descriptions complete: {receipt['details_complete']}.", "",
                      f"Role exclusions: {receipt['role_excluded_count']}; ambiguous roles: {receipt['role_unresolved_count']}. "
                      f"All title exclusions (including level): {receipt['title_excluded_count']}; ambiguous titles: {receipt['title_unresolved_count']}.", "",
                      "| Posting | Locations | Type | Notes |", "|---|---|---|---|"])
        for job in sorted(result.selected(), key=lambda item: (item["title"].casefold(), item["id"])):
            notes = list(job["warnings"])
            if not job["description"]:
                notes.append("Description unavailable")
            lines.append(f"| [{markdown(job['title'])}]({markdown_url(job['url'])}) ({markdown(job['id'])}) | {markdown(', '.join(job['cities']))} | {'Exploratory' if job['exploratory'] else 'Posting'} | {markdown('; '.join(notes))} |")
        if not result.selected():
            lines.append("\nNo displayable postings from this result. Check status before interpreting this as zero openings.")
        if result.unresolved():
            lines.extend(["", "### Unresolved Locations (audit only; not eligible listings)", ""])
            for job in result.unresolved():
                if job["title_filter"] == "matched" and job["expired"] is False:
                    lines.append(f"- [{markdown(job['title'])}]({markdown_url(job['url'])}) ({markdown(job['id'])})")
        if receipt["title_unresolved_count"]:
            lines.extend(["", "Ambiguous role/level labels are retained in inventory.json for audit, not recommendations."])
    return "\n".join(lines) + "\n"


def validate_payload(receipt, inventory, unresolved, selected):
    if receipt["company"] not in CLIENTS:
        raise ValueError("Unknown receipt company")
    policy = validate_role_policy(receipt.get("role_filter_policy"))
    if receipt["status"] not in ("complete", "partial", "failed", "blocked", "disabled"):
        raise ValueError("Unknown receipt status")
    if not isinstance(inventory, list) or not isinstance(unresolved, list) or not isinstance(selected, list):
        raise ValueError("Inventory outputs must be arrays")
    keys = [job["key"] for job in inventory + unresolved]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate output IDs")
    if len(inventory) != receipt["in_scope_count"] or len(unresolved) != receipt["unresolved_location_count"] or len(selected) != receipt["selected_count"]:
        raise ValueError("Output counts do not match receipt")
    if receipt["source_unique_count"] != len(inventory) + len(unresolved) + receipt["outside_count"] + receipt["nonpublic_count"]:
        raise ValueError("Source disposition counts do not reconcile")
    selected_keys = {job["key"] for job in selected}
    expected_keys = {job["key"] for job in inventory if job["expired"] is False and job["title_filter"] == "matched"}
    if len(selected_keys) != len(selected) or selected_keys != expected_keys:
        raise ValueError("Selected output does not match the inventory filter")
    inventory_by_key = {job["key"]: job for job in inventory}
    if any(job != inventory_by_key[job["key"]] for job in selected):
        raise ValueError("Selected posting content differs from inventory")
    for job in unresolved:
        if job["company"] != receipt["company"] or not job["public"] or job["location_status"] != "unresolved":
            raise ValueError("Unresolved output contains an invalid posting")
    missing = sum(not job["description"] for job in inventory)
    if missing != receipt["missing_description_count"]:
        raise ValueError("Missing-description count does not match inventory")
    if receipt["details_complete"] != (receipt["inventory_complete"] and missing == 0):
        raise ValueError("Detail completeness does not match inventory")
    for job in inventory:
        if job["company"] != receipt["company"] or not job["public"] or not city_keys(job["cities"]) & city_keys(receipt["requested_cities"]):
            raise ValueError("Inventory contains an invalid company, public flag or city")
    for job in inventory + unresolved:
        for field, expected in classify_title(job["company"], job["title"], policy).items():
            if job.get(field) != expected:
                raise ValueError("Posting role/title filter is inconsistent")
    for field in ("role_filter", "title_filter"):
        for status in ("excluded", "unresolved"):
            count = sum(job[field] == status for job in inventory)
            if receipt[field.replace("_filter", "") + "_" + status + "_count"] != count:
                raise ValueError("Role/title counts do not match inventory")
    if receipt["status"] == "complete" and (not receipt["inventory_complete"] or not receipt["details_complete"] or receipt["errors"]):
        raise ValueError("Complete status conflicts with coverage or errors")
    if receipt["company"] == "microsoft":
        microsoft.validate_collection(receipt, inventory, unresolved, selected)


def write_file(path, content):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(content)


def write_run(results, output_dir):
    parent = Path(output_dir)
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix=".job-search-", dir=parent))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = parent / f"{stamp}-{uuid4().hex[:8]}"
    try:
        for result in results:
            receipt = result.receipt()
            inventory, unresolved, selected = result.inventory(), result.unresolved(), result.selected()
            validate_payload(receipt, inventory, unresolved, selected)
            directory = staging / result.company
            directory.mkdir(mode=0o700)
            for filename, value in (("receipt.json", receipt), ("inventory.json", inventory),
                                    ("unresolved.json", unresolved), ("listings.json", selected)):
                write_file(directory / filename, json.dumps(value, indent=2, ensure_ascii=True) + "\n")
        write_file(staging / "report.md", report(results))
        if destination.exists():
            raise FileExistsError("Run destination already exists")
        staging.rename(destination)
        return destination
    except BaseException:
        shutil.rmtree(staging)
        raise


def validate_run(directory):
    found = 0
    for name in CLIENTS:
        path = Path(directory) / name
        if not path.is_dir():
            continue
        payloads = [json.loads((path / filename).read_text(encoding="utf-8")) for filename in
                    ("receipt.json", "inventory.json", "unresolved.json", "listings.json")]
        validate_payload(*payloads)
        found += 1
    if not found:
        raise ValueError("No company outputs found")
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description="Collect supported job boards; Amazon requires SDE II and Microsoft uses India/exact Software Engineer II/2 filters.")
    targets = parser.add_mutually_exclusive_group()
    targets.add_argument("--company", action="append", choices=CLIENTS, help="Repeat for multiple companies")
    targets.add_argument("--all", action="store_true", help="Check all supported companies, reporting source status")
    parser.add_argument("--workers", type=int, choices=range(1, len(CLIENTS) + 1), default=DEFAULT_WORKERS,
                        help=f"Concurrent company scans (default: {DEFAULT_WORKERS}); use 1 for sequential collection")
    parser.add_argument("--config", type=Path, default=MODULE_ROOT / "search_config.json")
    parser.add_argument("--output-dir", type=Path, help="Explicit system-temp parent for this session's run")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and validate without writing outputs")
    parser.add_argument("--json", action="store_true", help="Print compact machine-readable receipts")
    parser.add_argument("--validate", type=Path, metavar="RUN", help="Validate saved outputs without any network calls")
    args = parser.parse_args(argv)
    try:
        if args.validate:
            print(f"Validated {validate_run(args.validate)} company outputs")
            return 0
        if not args.dry_run:
            if args.output_dir is None or not args.output_dir.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()):
                raise ValueError("Collection requires --output-dir inside system temp; use match.py start for a fresh session")
        config = load_config(args.config)
        names = list(dict.fromkeys(args.company or CLIENTS))
        results = collect_companies(names, config, workers=args.workers)
        receipts = [result.receipt() for result in results]
        destination = None if args.dry_run else write_run(results, args.output_dir)
        if args.json:
            print(json.dumps({"dry_run": args.dry_run, "output": str(destination) if destination else None, "companies": receipts}, indent=2))
        else:
            for receipt in receipts:
                print(f"{receipt['company']}: {receipt['status']}; {receipt['in_scope_count']} city-scoped, {receipt['selected_count']} shown, {receipt['unresolved_location_count']} unresolved")
                for message in receipt["warnings"] + receipt["errors"]:
                    if message:
                        print("  " + message)
            if destination:
                print(f"Report: {destination / 'report.md'}")
        return 0 if all(receipt["status"] == "complete" for receipt in receipts) else 2
    except (KeyboardInterrupt, CollectionCancelled):
        print("Collection cancelled.", file=sys.stderr)
        return 130
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())