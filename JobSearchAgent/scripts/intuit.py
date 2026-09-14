import json
import re
from datetime import date, datetime, time, timezone
from urllib.parse import urljoin, urlsplit

from common import (
    FetchError, PageData, city_name, clean_text, posting, public_url, require_list,
)


ORIGIN = "https://jobs.intuit.com"
HOSTS = {"jobs.intuit.com"}
INDIA = ORIGIN + "/location/india-jobs/27595/1269750/2"
JOB_PATH = re.compile(r"^/job/[^/]+/[^/]+/27595/([0-9]+)/?$")
LOCATION_PATH = re.compile(r"^/location/[^/]+/27595/1269750/2(?:/[0-9]+)?/?$")


def job_url(value, base=ORIGIN):
    url = public_url(urljoin(base, value), HOSTS)
    match = JOB_PATH.fullmatch(urlsplit(url).path)
    if not match or urlsplit(url).query or urlsplit(url).fragment:
        raise ValueError("Intuit posting URL must be a canonical TalentBrew organization 27595 job route")
    return url, match.group(1)


def location_url(value, base=ORIGIN):
    url = public_url(urljoin(base, value), HOSTS)
    if not LOCATION_PATH.fullmatch(urlsplit(url).path) or urlsplit(url).query or urlsplit(url).fragment:
        raise ValueError("Intuit pagination left the public India location route; no search/application request made")
    return url


class IntuitPage(PageData):
    def __init__(self, source):
        self.counts = []
        self.next_links = []
        self.jobs = []
        self.canonicals = []
        self.active_job = None
        self.in_location = False
        super().__init__(source)

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        attributes = dict(attrs)
        if tag == "script" and self.current is not None:
            self.current["type"] = attributes.get("type")
        if "data-total-results" in attributes:
            self.counts.append(attributes)
        if tag == "link" and "canonical" in attributes.get("rel", "").split():
            self.canonicals.append(attributes.get("href"))
        if tag == "a":
            classes = attributes.get("class", "").split()
            if "next" in classes and "disabled" not in classes and attributes.get("aria-disabled") != "true":
                self.next_links.append(attributes.get("href"))
            if "sr-item" in classes:
                self.active_job = {
                    "url": attributes.get("href"), "title": attributes.get("data-title"),
                    "listing_requisition_id": attributes.get("data-job-id"), "location_parts": [],
                }
                self.jobs.append(self.active_job)
        if self.active_job is not None and tag == "span" and "job-location" in attributes.get("class", "").split():
            self.in_location = True

    def handle_data(self, data):
        super().handle_data(data)
        if self.active_job is not None and self.in_location:
            self.active_job["location_parts"].append(data)

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        if tag == "span":
            self.in_location = False
        if tag == "a":
            self.active_job = None
            self.in_location = False

    def pagination(self):
        if len(self.counts) != 1:
            raise ValueError("Intuit expected exactly one server-rendered result-count container")
        counts = {}
        for key in ("total-results", "total-pages", "current-page", "records-per-page"):
            value = self.counts[0].get("data-" + key)
            if not isinstance(value, str) or not value.isascii() or not value.isdigit():
                raise ValueError("Intuit pagination count is missing or invalid")
            counts[key] = int(value)
        if counts["records-per-page"] <= 0 or counts["current-page"] <= 0:
            raise ValueError("Intuit pagination requires positive page size/current page")
        pages = (counts["total-results"] + counts["records-per-page"] - 1) // counts["records-per-page"]
        if counts["total-pages"] != pages and not (pages == 0 and counts["total-pages"] == 1):
            raise ValueError("Intuit page count does not reconcile to its total/page size")
        return counts

    def job_posting(self):
        matches = []

        def visit(value):
            if isinstance(value, list):
                for item in value:
                    visit(item)
            elif isinstance(value, dict):
                types = value.get("@type", [])
                if types == "JobPosting" or isinstance(types, list) and "JobPosting" in types:
                    matches.append(value)
                if "@graph" in value:
                    visit(value["@graph"])

        for script in self.scripts:
            if (script.get("type") or "").lower() == "application/ld+json":
                visit(json.loads("".join(script["parts"])))
        if not matches:
            raise FetchError("Intuit JobPosting is missing; stopped on a changed page or possible challenge")
        if len(matches) != 1:
            raise ValueError("Intuit detail must contain exactly one JSON-LD JobPosting")
        return matches[0]


def source_date(value, *, expiry=False):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Intuit source date must be text")
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", value)
    if match:
        parsed = date(*(int(part) for part in match.groups()))
        return datetime.combine(parsed, time.max, timezone.utc).isoformat() if expiry else parsed.isoformat()
    return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()


def normalize(row, url):
    canonical, identity = job_url(row.get("url"))
    if job_url(url)[1] != identity:
        raise ValueError("Intuit detail URL ID differs from its listing TalentBrew ID")
    locations = row.get("jobLocation", [])
    if isinstance(locations, dict):
        locations = [locations]
    locations = require_list(locations, "jobLocation")
    cities = []
    unresolved = not locations
    for location in locations:
        if not isinstance(location, dict) or not isinstance(location.get("address"), dict):
            raise ValueError("Intuit jobLocation must contain a structured address")
        address = location["address"]
        country = address.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name")
        if country is not None and not isinstance(country, str):
            raise ValueError("Intuit addressCountry must be text or a named Country")
        locality = address.get("addressLocality")
        if locality is not None and not isinstance(locality, str):
            raise ValueError("Intuit addressLocality must be text")
        if (country or "").strip().casefold() in ("in", "ind", "india"):
            city = city_name(locality)
            if city:
                cities.append(city)
            elif not locality or locality.strip().casefold() in ("india", "remote", "multiple locations"):
                unresolved = True
        elif not country:
            unresolved = True
    requisition = row.get("identifier")
    if isinstance(requisition, dict):
        requisition = requisition.get("value")
    if isinstance(requisition, bool) or not isinstance(requisition, (str, int)) or not str(requisition).strip():
        raise ValueError("Intuit JSON-LD requisition identifier is missing")
    job = posting(
        "intuit", identity, row["title"], canonical, locations, cities,
        clean_text(row.get("description")), source_url=INDIA,
        requisition_id=str(requisition), published_at=source_date(row.get("datePosted")),
        source_date_posted=row.get("datePosted"), job_type=row.get("employmentType"),
        job_location_type=row.get("jobLocationType"),
        applicant_location_requirements=row.get("applicantLocationRequirements"),
    )
    job["expires_at"] = source_date(row.get("validThrough"), expiry=True)
    if not job["description"]:
        raise ValueError("Intuit detail has no full JSON-LD description")
    if unresolved and not cities:
        job["location_status"] = "unresolved"
        job["warnings"].append("India/remote or unknown address is not an exact city match")
    return job


def collect(http, result):
    result.warnings.append(
        "Intuit coverage is the published all-role India location inventory, not search-jobs AJAX or Avature. "
        "TalentBrew canonical URL IDs are tracker identities; JSON-LD requisitions are separate. "
        "No explicit open-state/expiry flag is assumed when the source omits it."
    )
    url = INDIA
    seen_pages = set()
    initial = None
    first_ids = None
    page_number = 1
    while True:
        url = location_url(url)
        if url in seen_pages:
            raise ValueError("Intuit repeated a pagination URL")
        seen_pages.add(url)
        page = IntuitPage(http.text(url))
        counts = page.pagination()
        if initial is None:
            initial = counts
            first_ids = [job_url(row["url"], url)[1] for row in page.jobs]
        if counts["current-page"] != page_number or any(
            counts[key] != initial[key] for key in ("total-results", "total-pages", "records-per-page")
        ):
            raise ValueError("Intuit source count/page changed during pagination")
        expected_rows = min(counts["records-per-page"], counts["total-results"] - len(result.records))
        if len(page.jobs) != expected_rows:
            raise ValueError("Intuit rendered rows do not reconcile to the reported India total/page size")
        result.pages.append({
            "url": url, "page": page_number, "returned": len(page.jobs),
            "reported_total": counts["total-results"], "reported_pages": counts["total-pages"],
        })
        for row in page.jobs:
            detail_url, identity = job_url(row["url"], url)
            location = clean_text("".join(row["location_parts"]))
            job = posting(
                "intuit", identity, row["title"], detail_url, [location] if location else [], [], "",
                source_url=url, listing_location=location,
                listing_requisition_id=row["listing_requisition_id"], location_status="unresolved",
            )
            result.add(job)
        if page_number >= max(1, counts["total-pages"]):
            if page.next_links or len(result.records) != counts["total-results"]:
                raise ValueError("Intuit terminal pagination does not reconcile to all unique India jobs")
            break
        if len(page.next_links) != 1 or not page.next_links[0]:
            raise ValueError("Intuit did not supply exactly one next location-page link")
        url = location_url(page.next_links[0], url)
        page_number += 1
    fresh = IntuitPage(http.text(INDIA))
    fresh_counts = fresh.pagination()
    result.pages.append({
        "url": INDIA, "page": 1, "returned": len(fresh.jobs),
        "reported_total": fresh_counts["total-results"], "recheck": True,
    })
    if fresh_counts != initial or [job_url(row["url"], INDIA)[1] for row in fresh.jobs] != first_ids:
        raise ValueError("Intuit India inventory changed during pagination")
    result.listing_complete = True
    for listed in list(result.records.values()):
        try:
            page = IntuitPage(http.text(listed["url"]))
            row = page.job_posting()
            job = normalize(row, listed["url"])
            if len(page.canonicals) != 1 or job_url(page.canonicals[0], listed["url"])[1] != job["id"]:
                raise ValueError("Intuit canonical link and JSON-LD/listing job IDs disagree")
            if listed["listing_requisition_id"] and listed["listing_requisition_id"] != job["requisition_id"]:
                raise ValueError("Intuit listing and JSON-LD requisition IDs disagree")
            if listed["title"] != job["title"]:
                job["warnings"].append("Listing and public detail titles differ; current detail title is used")
            job["listing_title"] = listed["title"]
            job["listing_location"] = listed["listing_location"]
            job["listing_requisition_id"] = listed["listing_requisition_id"]
            job["detail_url"] = listed["url"]
            result.records.pop(listed["key"])
            result.add(job)
        except FetchError:
            raise
        except (ValueError, KeyError, TypeError) as error:
            result.errors.append(f"Detail {listed['id']}: {error}")
