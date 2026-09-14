import re
from urllib.parse import urlsplit

from common import clean_text, posting, public_url, require_list, text_cities


HOSTS = {"www.atlassian.com"}
ORIGIN = "https://www.atlassian.com"
URL = ORIGIN + "/endpoint/careers/listings"
SCOPE = "Current public Atlassian UI feed; no independent underlying iCIMS total"
SECTIONS = ("overview", "responsibilities", "qualifications", "compensation")


def identity(value):
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)):
        raise ValueError("Atlassian id must be a numeric posting ID")
    return str(value)


def location_cities(locations):
    cities = []
    unresolved = not locations
    for location in locations:
        if not isinstance(location, str) or not location.strip():
            raise ValueError("Atlassian locations must contain nonempty text")
        named = text_cities(location)
        india = bool(re.search(r"\bindia\b", location, re.I))
        other_country = bool(re.search(r"\b(?:pakistan|sindh)\b", location, re.I))
        if india and not other_country:
            cities.extend(named)
            unresolved = unresolved or not named
        elif named and not other_country:
            unresolved = True
    if locations and all(re.fullmatch(r"remote(?:\s*-\s*remote)*", location.strip(), re.I) for location in locations):
        unresolved = True
    return sorted(set(cities)), unresolved


def normalize(row):
    job_id = identity(row["id"])
    locations = require_list(row.get("locations"), "locations")
    cities, unresolved = location_cities(locations)
    portal = row.get("portalJobPost")
    if not isinstance(portal, dict) or identity(portal.get("id")) != job_id:
        raise ValueError("Atlassian portalJobPost ID differs from the feed posting")
    portal_id = identity(row.get("portalId"))
    if identity(portal.get("portalId")) != portal_id:
        raise ValueError("Atlassian portal IDs disagree")
    portal_url = portal.get("portalUrl")
    if not isinstance(portal_url, str):
        raise ValueError("Atlassian portalJobPost has no public portal URL")
    parsed = urlsplit(portal_url)
    if (parsed.scheme != "https" or not (parsed.hostname or "").endswith(".icims.com")
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or not re.match(rf"^/jobs/{re.escape(job_id)}/[^/]+/job/?$", parsed.path)
            or parsed.query or parsed.fragment):
        raise ValueError("Atlassian portal URL does not identify the feed posting")
    sections = {field: clean_text(row.get(field)) for field in SECTIONS}
    job = posting("atlassian", job_id, row["title"],
                  public_url(f"{ORIGIN}/company/careers/details/{job_id}", HOSTS),
                  list(dict.fromkeys(locations)), cities, "", source_url=URL, source_scope=SCOPE,
                  department=row.get("category"), employment_type=row.get("type"),
                  portal_references=[{"portal_id": portal_id, "portal_job_post": dict(portal)}],
                  pay_ranges=[row["payRanges"]] if row.get("payRanges") is not None else [],
                  source_row_count=1, **sections)
    if unresolved and not cities:
        job["location_status"] = "unresolved"
    return job


def merge(previous, current):
    for field in ("title", "department", "employment_type") + SECTIONS:
        old, new = previous.get(field), current.get(field)
        if old and new and old != new:
            raise ValueError(f"Incompatible same-ID Atlassian representations: {field} differs")
        if not old and new:
            previous[field] = new
    for field in ("locations", "portal_references", "pay_ranges"):
        for value in current[field]:
            if value not in previous[field]:
                previous[field].append(value)
    previous["source_row_count"] += current["source_row_count"]
    previous["cities"], unresolved = location_cities(previous["locations"])
    previous.pop("location_status", None)
    if unresolved and not previous["cities"]:
        previous["location_status"] = "unresolved"


def collect(http, result):
    result.warnings.append(SCOPE + "; updatedDate is not treated as a posting date or expiry")
    rows = require_list(http.json(URL), "Atlassian listings")
    receipt = {"url": URL, "returned": len(rows), "source_scope": SCOPE,
               "pagination": "Entire unpaginated public UI-feed array"}
    result.pages.append(receipt)
    grouped = {}
    invalid_rows = 0
    for row in rows:
        try:
            grouped.setdefault(identity(row["id"]), []).append(row)
        except (ValueError, KeyError, TypeError) as error:
            invalid_rows += 1
            result.errors.append(f"Atlassian listing row: {error}")
    conflicts = []
    for job_id, representations in grouped.items():
        try:
            job = normalize(representations[0])
            for row in representations[1:]:
                merge(job, normalize(row))
            missing = [field for field in SECTIONS[:3] if not job[field]]
            if missing:
                job["warnings"].append("Missing full-description sections: " + ", ".join(missing))
            else:
                job["description"] = "\n\n".join(job[field] for field in SECTIONS if job[field])
            result.add(job)
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            conflicts.append(job_id)
            result.errors.append(f"Posting {job_id}: {error}")
    receipt.update(unique_ids=len(grouped), duplicate_rows=len(rows) - invalid_rows - len(grouped),
                   normalized_unique_ids=len(result.records), invalid_rows=invalid_rows,
                   conflicting_or_invalid_ids=conflicts)
    result.listing_complete = not invalid_rows and not conflicts and len(result.records) == len(grouped)
    for job in result.inventory():
        if not job["description"]:
            result.errors.append(f"Detail {job['id']}: incomplete public description sections")
