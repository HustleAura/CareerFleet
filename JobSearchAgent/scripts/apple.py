from urllib.parse import urlencode, urljoin

from common import PageData, clean_text, posting, public_url, require_list, require_total


HOSTS = {"jobs.apple.com"}
ORIGIN = "https://jobs.apple.com"
CITY_CODES = {"Hyderabad": ("hyderabad-HY1", "postLocation-HY1"),
              "Bengaluru": ("bengaluru-BGS", "postLocation-BGS")}


def loaders(page):
    data = page.apple_data()
    if data.get("errors"):
        raise ValueError("Apple returned a route error")
    return data["loaderData"]


def location_cities(locations):
    return [city for city, codes in CITY_CODES.items() if any(
        location.get("countryID") == "iso-country-IND"
        and (location.get("postLocationId") or location.get("id")) == codes[1] for location in locations)]


def normalize(row, page):
    locations = require_list(row.get("locations"), "locations")
    cities = location_cities(locations)
    identity = str(row["id"])
    position = str(row["positionId"])
    if not position.isdigit() or any(character not in "0123456789-PIPE" for character in identity):
        raise ValueError("Apple posting identity has an unexpected format")
    slug = row["transformedPostingTitle"]
    candidates = [href for href in page.links if "/locationPicker" not in href and any(
        f"/details/{candidate}/{slug}" in href for candidate in (identity, position))]
    if not candidates:
        raise ValueError(f"No rendered public detail URL for Apple posting {identity}")
    url = public_url(urljoin(ORIGIN, candidates[0]), HOSTS)
    job = posting("apple", identity, row["postingTitle"], url, locations, cities,
                  clean_text(row.get("jobSummary")), source_url=ORIGIN + "/en-in/search",
                  position_id=position, published_at=row.get("postDateInGMT"),
                  department=(row.get("team") or {}).get("teamName"))
    if not isinstance(row.get("postExternal"), bool):
        raise ValueError("Apple public-posting flag is missing")
    job["public"] = row["postExternal"]
    job["exploratory"] = row.get("managedPipelineRole") is True or row.get("type") == "PIPE"
    if not cities:
        job["location_status"] = "unresolved"
        job["warnings"].append("City search returned a broader location; not an exact city match")
    return job


def collect(http, result):
    for city in result.cities:
        code, location_id = CITY_CODES[city]
        page_number = 1
        expected = None
        seen = set()
        while True:
            url = ORIGIN + "/en-in/search?" + urlencode({"location": code, "page": page_number})
            page = PageData(http.text(url))
            search = loaders(page)["search"]
            rows = require_list(search["searchResults"], "searchResults")
            total = require_total(search.get("totalRecords"))
            result.pages.append({"url": url, "city": city, "page": page_number, "returned": len(rows), "reported_total": total})
            if expected is None:
                expected = total
            if search.get("queryParams", {}).get("location") != code:
                raise ValueError("Apple did not echo the requested city filter")
            filters = require_list(search.get("filters", {}).get("locations"), "filters.locations")
            if (rows or page_number == 1) and not any(item.get("id") == location_id for item in filters):
                raise ValueError("Apple did not recognize the requested city filter")
            if not rows:
                if len(seen) != expected:
                    raise ValueError("Apple pagination ended before all unique postings were retrieved")
                break
            if total != expected or search.get("page") != page_number:
                raise ValueError("Apple total, page or effective city filter changed")
            for row in rows:
                job = normalize(row, page)
                if job["id"] in seen:
                    raise ValueError("Apple repeated a posting within one city's pagination")
                seen.add(job["id"])
                if job["key"] in result.records:
                    previous = result.records[job["key"]]
                    if previous["title"] != job["title"] or previous["locations"] != job["locations"]:
                        raise ValueError("Apple posting changed between city searches")
                else:
                    result.add(job)
            if len(seen) > expected:
                raise ValueError("Apple returned more postings than totalRecords")
            page_number += 1
    result.listing_complete = True
    for job in result.inventory():
        job["summary"] = job["description"]
        job["description"] = ""
        try:
            detail_loaders = loaders(PageData(http.text(job["url"])))
            data = detail_loaders["jobDetails"]["jobsData"]
            if str(data["positionId"]) != job["position_id"]:
                raise ValueError("Apple detail position ID does not match listing")
            cities = location_cities(require_list(data.get("locations"), "detail.locations"))
            if not set(job["cities"]) <= set(cities):
                raise ValueError("Apple detail no longer includes the listing's exact India city")
            description = clean_text(data.get("description"))
            if not description:
                raise ValueError("Apple detail has no full description")
            job["description"] = description
            job["required"] = clean_text(data.get("minimumQualifications"))
            job["preferred"] = clean_text(data.get("preferredQualifications"))
            job["responsibilities"] = clean_text(data.get("responsibilities"))
        except (ValueError, KeyError, TypeError) as error:
            result.errors.append(f"Detail {job['id']}: {error}")
