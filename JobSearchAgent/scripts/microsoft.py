from datetime import datetime, timezone
from time import monotonic, sleep
from urllib.parse import urlencode, urljoin, urlsplit

from common import (
    FetchError, city_keys, city_name, clean_text, posting, public_url,
    require_list, require_total,
)


ORIGIN = "https://apply.careers.microsoft.com"
HOSTS = {"apply.careers.microsoft.com"}
SEARCH = ORIGIN + "/api/pcsx/search"
DETAIL = ORIGIN + "/api/pcsx/position_details"
REQUEST_INTERVAL = 2.0


class PacedClient:
    def __init__(self, http):
        self.http = http
        self.finished_at = None

    def json(self, url):
        if self.finished_at is not None:
            sleep(max(0.0, self.finished_at + REQUEST_INTERVAL - monotonic()))
        try:
            return self.http.json(url)
        except FetchError as error:
            cause = error.__cause__
            if getattr(cause, "code", None) == 429:
                headers = getattr(cause, "headers", None)
                retry_after = headers.get("Retry-After") if headers is not None else None
                response_date = headers.get("Date") if headers is not None else None
                raise FetchError(
                    f"Microsoft HTTP 429; Retry-After={retry_after!r}; response Date={response_date!r}. "
                    "Collection stopped without additional retries; coverage is incomplete. "
                    "None means the server supplied no retry delay, not permission to retry immediately."
                ) from error
            raise
        finally:
            self.finished_at = monotonic()


def position_id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).isascii() or not str(value).isdigit():
        raise ValueError("Microsoft Eightfold position ID must be numeric")
    return str(value)


def response_data(payload):
    if not isinstance(payload, dict) or payload.get("status") != 200:
        raise ValueError("Microsoft returned an unsuccessful PCS response")
    error = payload.get("error")
    if isinstance(error, dict):
        error = any(error.values())
    if error:
        raise ValueError("Microsoft returned an error in its PCS response")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("Microsoft PCS response has no data object")
    return data


def location_cities(locations):
    cities = []
    unresolved = not locations
    for value in locations:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Microsoft standardized location must be nonempty text")
        parts = [part.strip() for part in value.split(",")]
        country = parts[-1].casefold()
        if country in ("in", "india"):
            city = city_name(parts[0]) if len(parts) >= 2 else None
            if city:
                cities.append(city)
            elif len(parts) < 3 or any(part.casefold() in ("remote", "multiple locations", "unknown") for part in parts[:-1]):
                unresolved = True
        elif len(parts[-1]) != 2 or not parts[-1].isascii() or not parts[-1].isalpha():
            unresolved = True
    return cities, unresolved


def normalize(row, *, detail=False):
    identity = position_id(row.get("id"))
    locations = require_list(row.get("standardizedLocations"), "standardizedLocations")
    raw_locations = require_list(row.get("locations"), "locations")
    if any(not isinstance(value, str) for value in raw_locations):
        raise ValueError("Microsoft display locations must be text")
    cities, unresolved = location_cities(locations)
    url = public_url(urljoin(ORIGIN, row["positionUrl"]), HOSTS)
    if urlsplit(url).path.rstrip("/") != f"/careers/job/{identity}":
        raise ValueError("Microsoft posting URL does not match its Eightfold ID")
    published = row.get("postedTs")
    if published is not None:
        if isinstance(published, bool) or not isinstance(published, (int, float)) or published < 0:
            raise ValueError("Microsoft postedTs must be a nonnegative Unix timestamp")
        try:
            published = datetime.fromtimestamp(published, timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError) as error:
            raise ValueError("Microsoft postedTs is outside the supported date range") from error
    job = posting(
        "microsoft", identity, row["name"], url, locations, cities,
        clean_text(row.get("jobDescription")) if detail else "",
        source_url=SEARCH, display_locations=raw_locations,
        ats_job_id=row.get("atsJobId"), display_job_id=row.get("displayJobId"),
        published_at=published, posted_ts=row.get("postedTs"),
        department=row.get("department"), work_location_option=row.get("workLocationOption"),
        location_flexibility=row.get("locationFlexibility"),
    )
    if unresolved and not cities:
        job["location_status"] = "unresolved"
        job["warnings"].append("No exact standardized India city; remote/country-only locations are not city matches")
    if detail:
        job.update(
            worksite=row.get("efcustomTextWorkSite"),
            required_travel=row.get("efcustomTextRequiredTravel"),
            profession=row.get("efcustomTextCurrentProfession"),
            discipline=row.get("efcustomTextTaDisciplineName"),
            job_type=row.get("efcustomTextEmploymentType"),
            position_extra_details=row.get("positionExtraDetails"),
        )
        if not job["description"]:
            raise ValueError("Microsoft detail has no full jobDescription")
    return job


def search(http, result, offset, *, recheck=False):
    # Location search is proximity-based. The unfiltered inventory includes
    # remote and hybrid postings without relying on a radius or city facet.
    url = SEARCH + "?" + urlencode({"domain": "microsoft.com", "query": "", "start": offset})
    data = response_data(http.json(url))
    rows = require_list(data.get("positions"), "positions")
    total = require_total(data.get("count"))
    if data.get("appliedFilters") != {}:
        raise ValueError("Microsoft unexpectedly applied filters to the global inventory")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("Microsoft position entries must be objects")
    result.pages.append({
        "url": url, "offset": offset, "returned": len(rows), "reported_total": total,
        "scope": "global public Eightfold inventory", "recheck": recheck,
    })
    return rows, total


def collect(http, result):
    http = PacedClient(http)
    result.warnings.append(
        "Microsoft coverage is the global public Eightfold inventory, filtered by every standardized India city. "
        "work_location_option is preserved verbatim; 'onsite' does not establish office attendance days. "
        "Requests are sequential with a two-second completion-to-next-request interval; "
        "the shared HTTP client's bounded Retry-After handling still applies."
    )
    offset = 0
    expected = None
    first_ids = None
    while True:
        rows, total = search(http, result, offset)
        if expected is None:
            expected = total
            first_ids = [position_id(row.get("id")) for row in rows]
        if total != expected:
            raise ValueError("Microsoft count changed during global pagination; rerun for a fresh snapshot")
        for row in rows:
            result.add(normalize(row))
        if not rows:
            if offset != expected or len(result.records) != expected:
                raise ValueError("Microsoft pagination ended before all count/unique positions reconciled")
            break
        offset += len(rows)
        if offset > expected:
            raise ValueError("Microsoft returned more positions than its global count")
    final_rows, final_total = search(http, result, 0, recheck=True)
    if final_total != expected or [position_id(row.get("id")) for row in final_rows] != first_ids:
        raise ValueError("Microsoft inventory or first-page ordering changed during pagination")
    result.listing_complete = True
    for listed in list(result.inventory()) + list(result.unresolved()):
        url = DETAIL + "?" + urlencode({
            "position_id": listed["id"], "domain": "microsoft.com", "hl": "en",
        })
        try:
            data = response_data(http.json(url))
            job = normalize(data, detail=True)
            if job["id"] != listed["id"] or job["title"] != listed["title"]:
                raise ValueError("Microsoft detail identity/title differs from the listing")
            for field in ("ats_job_id", "display_job_id"):
                if listed[field] != job[field]:
                    raise ValueError("Microsoft ATS/display ID changed between listing and detail")
            if not city_keys(listed["cities"]) <= city_keys(job["cities"]):
                raise ValueError("Microsoft detail no longer includes the listing's exact India city")
            job["detail_url"] = url
            job["listing_locations"] = listed["locations"]
            result.records.pop(listed["key"])
            result.add(job)
        except FetchError:
            raise
        except (ValueError, KeyError, TypeError) as error:
            result.errors.append(f"Detail {listed['id']}: {error}")
