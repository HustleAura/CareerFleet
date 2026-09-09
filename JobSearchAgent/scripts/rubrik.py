import re

from common import city_keys, clean_text, posting, public_url, require_list, require_total, text_cities


HOSTS = {"boards-api.greenhouse.io"}
URL = "https://boards-api.greenhouse.io/v1/boards/rubrik/jobs?content=true"


def normalize(row):
    location = (row.get("location") or {}).get("name") or ""
    offices = require_list(row.get("offices", []), "offices")
    office_names = [office.get("name") or "" for office in offices]
    office_text = " | ".join((office.get("location") or "") + " " + (office.get("name") or "") for office in offices)
    named = text_cities(location)
    assigned = text_cities(office_text)
    india_evidence = bool(re.search(r"\b(?:india|karnataka|telangana)\b", location + " " + office_text, re.I))
    cities = list(named)
    if "Hyderabad" in cities and (not india_evidence or re.search(r"\b(?:pakistan|sindh)\b", location, re.I)):
        cities.remove("Hyderabad")
    if not location.strip():
        cities = assigned if india_evidence else []
    url = public_url(row["absolute_url"], {"www.rubrik.com", "job-boards.greenhouse.io", "boards.greenhouse.io"})
    job = posting("rubrik", row["id"], row["title"], url, [location] + office_names,
                  cities, clean_text(row.get("content")), source_url=URL,
                  requisition_id=row.get("requisition_id"), updated_at=row.get("updated_at"),
                  published_at=row.get("first_published"), department=[item.get("name") for item in row.get("departments", [])])
    job["exploratory"] = row.get("internal_job_id") is None
    job["expires_at"] = row.get("application_deadline")
    remote_india = "remote" in location.casefold() and bool(re.search(r"\bindia\b", location + " " + office_text, re.I))
    unknown_remote = location.strip().casefold() == "remote" and not office_text.strip(" |")
    if not cities and (not location.strip() or remote_india or unknown_remote or named):
        job["location_status"] = "unresolved"
    if city_keys(named) != city_keys(assigned):
        job["warnings"].append("Posting location and office metadata differ; posting location takes precedence")
    return job


def collect(http, result):
    payload = http.json(URL)
    rows = require_list(payload["jobs"], "jobs")
    total = require_total(payload.get("meta", {}).get("total"))
    result.pages.append({"url": URL, "reported_total": total, "returned": len(rows)})
    for row in rows:
        result.add(normalize(row))
    if len(result.records) != total:
        raise ValueError("Rubrik feed does not reconcile to meta.total")
    result.listing_complete = True