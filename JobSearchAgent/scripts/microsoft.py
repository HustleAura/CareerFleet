from datetime import datetime, timezone
from time import monotonic
from urllib.parse import urlencode, urljoin, urlsplit

from common import (
    CollectionCancelled, FetchError, RequestLimitError, city_keys, city_name, clean_text, posting, public_url,
    require_list, require_total,
)
from roles import MICROSOFT_TITLES, classify_title


ORIGIN = "https://apply.careers.microsoft.com"
HOSTS = {"apply.careers.microsoft.com"}
SEARCH = ORIGIN + "/api/pcsx/search"
DETAIL = ORIGIN + "/api/pcsx/position_details"
REQUEST_INTERVAL = 2.0
DEFAULT_MAX_REQUESTS = 30
SCOPE = "Microsoft India geography query; exact Software Engineer II / Software Engineer 2 titles only"
EXPECTED_FILTERS = {
    "hiringTitle": list(MICROSOFT_TITLES),
    "includeRemote": ["1"],
    "includeRelocation": ["0"],
}


def validate_max_requests(value):
    if type(value) is not int or value < 1:
        raise ValueError("Microsoft max_requests must be a positive integer")
    return value


def collection_metadata(max_requests=DEFAULT_MAX_REQUESTS):
    return {
        "scope": SCOPE, "location": "India", "hiring_titles": list(MICROSOFT_TITLES),
        "reported_total": None, "sort_by": None,
        "request_limit": validate_max_requests(max_requests), "request_attempts": 0,
        "search_attempts": 0, "detail_attempts": 0, "stop_reason": "not_started",
    }


class PacedClient:
    def __init__(self, http, result):
        self.http = http
        self.result = result
        self.finished_at = None
        self.http.restrict_requests(result.collection["request_limit"])

    def json(self, url):
        public_url(url, HOSTS)
        path = urlsplit(url).path
        if path not in (urlsplit(SEARCH).path, urlsplit(DETAIL).path):
            raise ValueError("Unexpected Microsoft collection endpoint")
        self.http._check_cancelled()
        if self.finished_at is not None:
            self.http._wait_for_retry(max(0.0, self.finished_at + REQUEST_INTERVAL - monotonic()))
        before = self.http.request_count
        try:
            return self.http.json(url)
        except FetchError as error:
            cause = error.__cause__
            code = getattr(cause, "code", None)
            self.result.collection["stop_reason"] = (
                "request_budget" if isinstance(error, RequestLimitError) else
                "rate_limited" if code == 429 else
                "access_blocked" if code in (401, 403) else "fetch_error")
            if code == 429:
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
            attempts = self.http.request_count - before
            self.result.collection["request_attempts"] += attempts
            field = "search_attempts" if path == urlsplit(SEARCH).path else "detail_attempts"
            self.result.collection[field] += attempts
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


def search_url(offset):
    return SEARCH + "?" + urlencode([
        ("domain", "microsoft.com"), ("query", ""), ("location", "India"), ("start", offset),
        *(("filter_hiring_title", title) for title in MICROSOFT_TITLES),
    ])


def validate_filters(filters):
    if (not isinstance(filters, dict) or set(filters) != set(EXPECTED_FILTERS)
            or any(not isinstance(filters[key], list) or sorted(filters[key]) != sorted(values)
                   for key, values in EXPECTED_FILTERS.items())):
        raise ValueError("Microsoft effective filters differ from the requested title/remote scope")


def search(http, result, offset, *, recheck=False):
    url = search_url(offset)
    data = response_data(http.json(url))
    rows = require_list(data.get("positions"), "positions")
    total = require_total(data.get("count"))
    filters = data.get("appliedFilters")
    validate_filters(filters)
    if data.get("sortBy") != "distance":
        raise ValueError("Microsoft location query ordering changed")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("Microsoft position entries must be objects")
    result.pages.append({
        "url": url, "offset": offset, "returned": len(rows), "reported_total": total,
        "scope": SCOPE, "recheck": recheck, "applied_filters": filters, "sort_by": "distance",
    })
    return rows, total


def collect(http, result, *, max_requests=DEFAULT_MAX_REQUESTS):
    result.collection = collection_metadata(max_requests)
    result.warnings.append(
        SCOPE + ". Complete means complete within this query, not every SDE-2 alias or all Microsoft openings. "
        "location=India is a geography search, not a verified strict country facet; exact India cities are checked locally. "
        "work_location_option is preserved verbatim; 'onsite' does not establish office attendance days. "
        "Requests are sequential with a two-second completion-to-next-request interval. "
        "The request budget is a client safety limit, not Microsoft's quota; retries and redirects are disabled."
    )
    try:
        http = PacedClient(http, result)
        result.collection["stop_reason"] = "incomplete"
        collect_pages(http, result)
    except CollectionCancelled:
        result.collection["stop_reason"] = "cancelled"
        raise
    except FetchError:
        raise
    except (ValueError, KeyError, TypeError):
        result.collection["stop_reason"] = "validation_error"
        raise
    else:
        result.collection["stop_reason"] = "detail_errors" if result.errors else "complete"


def collect_pages(http, result):
    offset = 0
    expected = None
    first_ids = None
    while True:
        rows, total = search(http, result, offset)
        if expected is None:
            expected = total
            result.collection.update(reported_total=total, sort_by="distance")
            first_ids = [position_id(row.get("id")) for row in rows]
        if total != expected:
            raise ValueError("Microsoft count changed during filtered pagination")
        for row in rows:
            result.add(normalize(row))
        if any(classify_title("microsoft", row["name"])["title_filter"] != "matched" for row in rows):
            raise ValueError("Microsoft returned a title outside the verified exact-title query")
        if not rows:
            if offset != expected or len(result.records) != expected:
                raise ValueError("Microsoft pagination ended before all count/unique positions reconciled")
            break
        offset += len(rows)
        if offset > expected:
            raise ValueError("Microsoft returned more positions than its filtered count")
        eligible_keys = {job["key"] for job in result.selected()}
        for row in rows:
            listed = result.records[f"microsoft:{position_id(row['id'])}"]
            if listed["key"] in eligible_keys:
                fetch_detail(http, result, listed)
    final_rows, final_total = search(http, result, 0, recheck=True)
    if final_total != expected or [position_id(row.get("id")) for row in final_rows] != first_ids:
        raise ValueError("Microsoft inventory or first-page ordering changed during pagination")
    result.listing_complete = True


def fetch_detail(http, result, listed):
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


def validate_collection(receipt, inventory, unresolved, selected):
    collection = receipt.get("collection")
    if collection is None:
        if receipt["status"] not in ("blocked", "disabled", "failed") or receipt["source_unique_count"]:
            raise ValueError("Microsoft receipt is missing its filtered collection scope")
        return
    if (collection["scope"] != SCOPE or collection["location"] != "India"
            or collection["hiring_titles"] != list(MICROSOFT_TITLES)):
        raise ValueError("Microsoft receipt has an unsupported collection scope")
    limit = validate_max_requests(collection["request_limit"])
    for field in ("request_attempts", "search_attempts", "detail_attempts", "eligible_count", "detailed_count"):
        if type(collection[field]) is not int or collection[field] < 0:
            raise ValueError("Invalid Microsoft collection count")
    if (collection["request_attempts"] > limit
            or collection["request_attempts"] != collection["search_attempts"] + collection["detail_attempts"]
            or collection["search_attempts"] < len(receipt["pages"])):
        raise ValueError("Microsoft request accounting does not reconcile")
    detailed = sum(bool(job["description"]) for job in selected)
    if (type(collection["collected_details_complete"]) is not bool
            or collection["eligible_count"] != len(selected) or collection["detailed_count"] != detailed
            or collection["detail_attempts"] < detailed
            or collection["collected_details_complete"] != (
                (bool(selected) or receipt["inventory_complete"]) and detailed == len(selected))):
        raise ValueError("Microsoft collected-set description coverage does not reconcile")
    reasons = {"not_started", "incomplete", "complete", "detail_errors", "cancelled",
               "request_budget", "rate_limited", "access_blocked", "fetch_error", "validation_error"}
    if collection["stop_reason"] not in reasons:
        raise ValueError("Invalid Microsoft stop reason")
    if collection["stop_reason"] == "request_budget" and collection["request_attempts"] != limit:
        raise ValueError("Microsoft budget stop occurred before the request limit")
    if collection["reported_total"] is not None:
        require_total(collection["reported_total"])
    if collection["sort_by"] != ("distance" if collection["reported_total"] is not None else None):
        raise ValueError("Microsoft query ordering is inconsistent")
    for job in inventory + unresolved:
        cities, _ = location_cities(job["locations"])
        if city_keys(cities) != city_keys(job["cities"]):
            raise ValueError("Microsoft stored cities differ from standardized country/city evidence")
    offset = 0
    terminal = rechecked = False
    for page in receipt["pages"]:
        if (page["scope"] != SCOPE or page["sort_by"] != "distance"
                or (receipt["inventory_complete"] and page["reported_total"] != collection["reported_total"])):
            raise ValueError("Microsoft page scope/filters/count changed")
        require_total(page["reported_total"])
        validate_filters(page["applied_filters"])
        start = page["offset"]
        if type(start) is not int or start < 0:
            raise ValueError("Invalid Microsoft page offset")
        if page["url"] != search_url(start):
            raise ValueError("Microsoft page did not use the declared filtered query")
        returned = require_total(page["returned"])
        if type(page["recheck"]) is not bool:
            raise ValueError("Invalid Microsoft reconciliation flag")
        if page["recheck"]:
            if not terminal or start != 0 or rechecked:
                raise ValueError("Invalid Microsoft reconciliation page")
            if receipt["inventory_complete"] and returned != receipt["pages"][0]["returned"]:
                raise ValueError("Microsoft first-page size changed during reconciliation")
            rechecked = True
        else:
            if terminal or start != offset:
                raise ValueError("Microsoft page offsets do not reconcile")
            offset += returned
            terminal = returned == 0
    if receipt["inventory_complete"] and (
            not terminal or not rechecked or offset != collection["reported_total"]
            or receipt["source_unique_count"] != collection["reported_total"]):
        raise ValueError("Microsoft query completeness does not reconcile")
    if receipt["status"] == "complete" and collection["stop_reason"] != "complete":
        raise ValueError("Complete Microsoft receipt has an incomplete stop reason")
    if collection["stop_reason"] == "complete" and receipt["status"] != "complete":
        raise ValueError("Microsoft completion marker conflicts with source coverage")
