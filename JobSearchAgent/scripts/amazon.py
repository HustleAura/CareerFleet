import json
from urllib.parse import urlencode, urljoin

from common import clean_text, posting, public_url, require_list, require_total
from roles import amazon_title_filter as title_filter


HOSTS = {"www.amazon.jobs", "amazon.jobs"}
BASE = "https://www.amazon.jobs/en/search.json"


def normalize(row):
    locations = []
    cities = set()
    for raw in require_list(row.get("locations"), "locations"):
        location = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(location, dict):
            raise ValueError("Amazon location is not an object")
        country = location.get("normalizedCountryCode")
        city = location.get("normalizedCityName")
        locations.append({"city": city, "country": country,
                          "raw": location.get("normalizedLocation"), "workplace": location.get("type")})
        if country == "IND" and city in ("Hyderabad", "Bengaluru"):
            cities.add(city)
    url = public_url(urljoin(BASE, row["job_path"]), HOSTS)
    description = "\n\n".join(part for part in (
        clean_text(row.get("description")), clean_text(row.get("basic_qualifications")),
        clean_text(row.get("preferred_qualifications"))) if part)
    job = posting("amazon", row.get("id_icims") or row.get("id"), row["title"], url,
                  locations, cities, description, source_url=BASE,
                  required=clean_text(row.get("basic_qualifications")),
                  preferred=clean_text(row.get("preferred_qualifications")),
                  published_at=row.get("posted_date"), updated_at=row.get("updated_time"),
                  job_type=row.get("job_schedule_type"), department=row.get("job_category"))
    if not cities:
        job["location_status"] = "unresolved"
        job["warnings"].append("Filtered API result has no exact requested India/city location pair")
    if not row.get("description"):
        job["description"] = ""
    return job


def collect(http, result):
    offset = 0
    expected = None
    while True:
        params = [("normalized_country_code[]", "IND")]
        params.extend(("normalized_city_name[]", city) for city in result.cities)
        params.extend((("offset", offset), ("result_limit", 100), ("sort", "recent")))
        url = BASE + "?" + urlencode(params)
        payload = http.json(url)
        if payload.get("error"):
            raise ValueError("Amazon API returned an error")
        rows = require_list(payload["jobs"], "jobs")
        total = require_total(payload.get("hits"))
        result.pages.append({"url": url, "offset": offset, "returned": len(rows), "reported_total": total})
        if expected is None:
            expected = total
        if total != expected:
            raise ValueError("Amazon total changed during pagination; rerun for a consistent inventory")
        for row in rows:
            result.add(normalize(row))
        if not rows:
            if len(result.records) != expected:
                raise ValueError("Amazon pagination ended before all unique postings were retrieved")
            result.listing_complete = True
            return
        offset += len(rows)
        if offset > expected:
            raise ValueError("Amazon returned more postings than hits")