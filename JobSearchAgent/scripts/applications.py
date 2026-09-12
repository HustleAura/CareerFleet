import argparse
import csv
import io
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from common import SUPPORTED_COMPANIES


MODULE_ROOT = Path(__file__).resolve().parents[1]
TRACKER = MODULE_ROOT / "applied_jobs.csv"
FIELDS = ("company", "jobid", "title")
COMPANIES = SUPPORTED_COMPANIES


def tracker_path(path):
    path = Path(path).absolute()
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents
                                if parent != Path('/var')):
        raise ValueError("Tracker paths must not use symlinks")
    path = path.resolve()
    temporary = Path(tempfile.gettempdir()).resolve()
    if path != TRACKER or path.suffix != ".csv":
        if not path.is_relative_to(temporary) or path.suffix != ".csv":
            raise ValueError("Use the default tracker or a CSV inside system temp")
    if any((parent / "manifest.json").exists() or any((parent / name / "receipt.json").exists()
           for name in COMPANIES) for parent in path.parents):
        raise ValueError("Tracker must be outside scan and matching artifacts")
    return path


def validate_rows(rows):
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(FIELDS):
            raise ValueError("Tracker requires exactly company,jobid,title")
        for field in FIELDS:
            value = row[field]
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"Invalid or empty {field}")
            if any(ord(character) < 32 for character in value) or value.startswith(("=", "+", "-", "@")):
                raise ValueError(f"Unsafe spreadsheet/control characters in {field}")
        if row["company"] not in COMPANIES or any(character.isspace() for character in row["jobid"]):
            raise ValueError("Unknown company or invalid jobid")
        pair = (row["company"], row["jobid"])
        if pair in seen:
            raise ValueError("Duplicate company/jobid in tracker")
        seen.add(pair)
    return rows


def read_tracker(path=TRACKER):
    path = tracker_path(path)
    try:
        with path.open(encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source, strict=True)
            if reader.fieldnames != list(FIELDS):
                raise ValueError("Tracker header must be exactly company,jobid,title")
            return validate_rows(list(reader))
    except FileNotFoundError as error:
        raise ValueError("Applied tracker missing; restore it or explicitly initialize an empty tracker") from error
    except csv.Error as error:
        raise ValueError(f"Malformed tracker CSV: {error}") from error


def applied_pairs(rows):
    return {(row["company"], row["jobid"]) for row in validate_rows(rows)}


def csv_text(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(validate_rows(rows))
    return stream.getvalue()


@contextmanager
def tracker_lock(path=TRACKER):
    path = tracker_path(path)
    lock = path.with_name("." + path.name + ".lock")
    lock.mkdir(mode=0o700)
    try:
        yield path
    finally:
        lock.rmdir()


def initialize(path=TRACKER):
    with tracker_lock(path) as path:
        if path.exists():
            read_tracker(path)
            return False
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as target:
                target.write(csv_text([]))
                target.flush()
                os.fsync(target.fileno())
            read_tracker(path)
        except BaseException:
            path.unlink()
            raise
    return True


def add(company, jobid, title, path=TRACKER):
    if company not in COMPANIES:
        raise ValueError("New applications require a currently supported company")
    row = {"company": company, "jobid": jobid, "title": title}
    validate_rows([row])
    with tracker_lock(path) as path:
        rows = read_tracker(path)
        if (company, jobid) in applied_pairs(rows):
            return {"added": False, "row": next(item for item in rows
                    if (item["company"], item["jobid"]) == (company, jobid))}
        rows.append(row)
        descriptor, filename = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
        temporary = Path(filename)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as target:
                target.write(csv_text(rows))
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, path)
            if read_tracker(path) != rows:
                raise ValueError("Tracker read-back differs; keep session files and resolve before cleanup")
        finally:
            temporary.unlink(missing_ok=True)
    return {"added": True, "row": row}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Record only user-confirmed applications in a three-column CSV.")
    parser.add_argument("--tracker", type=Path, default=TRACKER)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    commands.add_parser("list")
    commands.add_parser("validate")
    command = commands.add_parser("add")
    command.add_argument("--company", choices=COMPANIES, required=True)
    command.add_argument("--jobid", required=True)
    command.add_argument("--title", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            result = {"created": initialize(args.tracker), "tracker": str(args.tracker)}
        elif args.command == "add":
            result = add(args.company, args.jobid, args.title, args.tracker)
        else:
            rows = read_tracker(args.tracker)
            result = rows if args.command == "list" else {"valid": True, "count": len(rows)}
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    except (ValueError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())