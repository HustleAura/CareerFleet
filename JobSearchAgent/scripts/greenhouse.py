import re

from common import clean_text, posting, public_url, require_list, require_total, text_cities


def identity(value, field="id"):
    if type(value) is not int or value <= 0:
        raise ValueError(f"Greenhouse {field} must be a positive integer")
    return value


def optional_text(value, field):
    if value is not None and not isinstance(value, str):
        raise ValueError(f"Greenhouse {field} must be text or null")
    return value or ""


def office_record(value):
    if not isinstance(value, dict):
        raise ValueError("Greenhouse office must be an object")
    parent = value.get("parent_id")
    if parent is not None:
        identity(parent, "office parent_id")
    children = require_list(value.get("child_ids"), "office child_ids")
    for child in children:
        identity(child, "office child_id")
    if len(children) != len(set(children)):
        raise ValueError("Greenhouse office has duplicate child IDs")
    name = optional_text(value.get("name"), "office name")
    if not name.strip():
        raise ValueError("Greenhouse office requires a name")
    return {"id": identity(value.get("id"), "office id"), "name": name,
            "location": optional_text(value.get("location"), "office location"),
            "parent_id": parent, "child_ids": list(children)}


def fetch_jobs(http, result, url):
    payload = http.json(url)
    if not isinstance(payload, dict) or not isinstance(payload.get("meta"), dict):
        raise ValueError("Greenhouse feed requires jobs and meta objects")
    rows = require_list(payload.get("jobs"), "jobs")
    total = require_total(payload["meta"].get("total"))
    result.pages.append({"url": url, "reported_total": total, "returned": len(rows)})
    return rows, total


def finish_jobs(result, rows, total):
    source_ids = [str(identity(row.get("id"))) for row in rows]
    if (len(rows) != total or len(set(source_ids)) != total
            or {job["id"] for job in result.records.values()} != set(source_ids)):
        raise ValueError("Greenhouse source rows and unique posting IDs do not reconcile to meta.total")
    result.listing_complete = True


def normalize_posting(company, row, source_url, url_hosts):
    if not isinstance(row, dict):
        raise ValueError("Greenhouse job must be an object")
    location = row.get("location")
    if not isinstance(location, dict) or "name" not in location:
        raise ValueError("Greenhouse job requires location.name")
    location = optional_text(location["name"], "location.name")
    offices = [office_record(value) for value in require_list(row.get("offices"), "offices")]
    if len({office["id"] for office in offices}) != len(offices):
        raise ValueError("Greenhouse job has duplicate office IDs")
    departments = require_list(row.get("departments"), "departments")
    names = []
    for department in departments:
        if not isinstance(department, dict):
            raise ValueError("Greenhouse department must be an object")
        names.append(optional_text(department.get("name"), "department name"))
    for field in ("updated_at", "first_published", "application_deadline"):
        optional_text(row.get(field), field)
    description = clean_text(optional_text(row.get("content"), "content"))
    url = public_url(row.get("absolute_url"), url_hosts)
    job = posting(company, identity(row.get("id")), row.get("title"), url,
                  [location] + [office["name"] for office in offices], [], description,
                  source_url=source_url, requisition_id=row.get("requisition_id"),
                  internal_job_id=row.get("internal_job_id"), updated_at=row.get("updated_at"),
                  published_at=row.get("first_published"), department=names,
                  posting_location=location, offices=offices)
    job["exploratory"] = row.get("internal_job_id") is None
    job["expires_at"] = row.get("application_deadline")
    return job


def is_india(value):
    return bool(re.search(r"\b(?:india|karnataka|telangana)\b", value, re.I))


def is_foreign_target(value):
    return bool(re.search(
        r"\b(?:pakistan|sindh|united states|usa|united kingdom|uk|canada|"
        r"australia|bangladesh|nepal|sri lanka)\b", value, re.I))


def bare_cities(value):
    remainder = re.sub(r"\b(?:hyderabad|bengaluru|bangalore|and|or|hybrid|onsite|on-site)\b",
                       "", value, flags=re.I)
    return not remainder.strip(" ,;/|&()-")


def locate(job, office_countries):
    """Keep advertised cities and country-verified assigned offices, not descendants."""
    location = job["posting_location"]
    pieces = re.split(r"[;|]", location)
    cities = set()
    unresolved = False
    evidence = []
    india_offices = [office for office in job["offices"] if office_countries.get(office["id"])]
    for office in job["offices"]:
        text = office["name"] + " " + office["location"]
        if text_cities(text) and office["id"] not in office_countries and not is_foreign_target(text):
            unresolved = True
    for office in india_offices:
        text = office["name"] + " " + office["location"]
        if is_foreign_target(text):
            unresolved = True
            job["warnings"].append("Office country evidence conflicts with its city label")
            continue
        cities.update(text_cities(text))
        evidence.append({"type": "office", "office_id": office["id"],
                         "country": "India", "source": office_countries[office["id"]]})
    for piece in pieces:
        named = text_cities(piece)
        if is_foreign_target(piece):
            if is_india(piece):
                unresolved = True
                job["warnings"].append("Posting location contains conflicting country evidence")
            continue
        if is_india(piece):
            cities.update(named)
            evidence.append({"type": "posting_location", "value": piece, "country": "India"})
        elif named:
            if bare_cities(piece) and india_offices:
                cities.update(named)
            else:
                unresolved = True
    job["cities"] = sorted(cities)
    job["country_evidence"] = evidence
    if not cities:
        text = location + " " + " ".join(office["name"] + " " + office["location"] for office in job["offices"])
        broad = bool(re.fullmatch(r"\s*(?:(?:remote|hybrid)\s*[-,]?\s*)?(?:india|apac|global|worldwide)?\s*",
                                  location, re.I))
        if unresolved or not text.strip() or (broad and (is_india(text) or not job["offices"])):
            job["location_status"] = "unresolved"
    elif unresolved:
        job["warnings"].append("Some advertised city locations lack unambiguous India evidence")
    return job
