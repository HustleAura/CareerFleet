import json
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from uuid import UUID

from common import (
    FetchError, PageData, city_keys, clean_text, posting, public_url,
    require_list, require_total, text_cities,
)


HOSTS = {"www.rippling.com", "ats.rippling.com", "6fnax3tbef-dsn.algolia.net"}
URL = "https://www.rippling.com/careers/open-roles"
APP_ID = "6FNAX3TBEF"
INDEX = "careers_en-US_production"
SEARCH_URL = "https://6fnax3tbef-dsn.algolia.net/1/indexes/" + INDEX
PAGE_SIZE = 1000
MAX_PAGES = 100
IDENTIFIER = r"[A-Za-z_$][\w$]*"


class FrontendPage(PageData):
    def __init__(self, source):
        self.sources = []
        super().__init__(source)

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        attributes = dict(attrs)
        if tag == "script" and attributes.get("src"):
            self.sources.append(attributes["src"])


def modules(source):
    pattern = rf"(?:^|[{{,])(\d+):function\({IDENTIFIER},{IDENTIFIER},{IDENTIFIER}\)\{{"
    matches = list(re.finditer(pattern, source))
    return {match[1]: source[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(source)]
            for index, match in enumerate(matches)}


def search_headers(http, result):
    page = FrontendPage(http.text(URL))
    if page.next_data()["props"]["pageProps"]["data"].get("algoliaIndexName") != INDEX:
        raise ValueError("Rippling's official frontend changed its public search index")
    sources = []
    for prefix in ("/_next/static/chunks/pages/_app-", "/_next/static/chunks/pages/careers/open-roles-"):
        candidates = [urljoin(URL, src) for src in page.sources if urlsplit(urljoin(URL, src)).path.startswith(prefix)]
        if len(candidates) != 1:
            raise ValueError("Rippling's current frontend bundle links are missing or ambiguous")
        sources.append(public_url(candidates[0], {"www.rippling.com"}))
    app_modules = modules(http.text(sources[0]))
    role_modules = modules(http.text(sources[1]))
    credentials = set()
    for identity, config in app_modules.items():
        if json.dumps(APP_ID) not in config:
            continue
        exports = dict(re.findall(rf"({IDENTIFIER}):function\(\)\{{return ({IDENTIFIER})\}}", config))
        literals = {}
        for match in re.finditer(rf"(?:\b(?:let|const|var)\s+|,)({IDENTIFIER})\s*=\s*(\"(?:\\.|[^\"\\])*\")", config):
            literals[match[1]] = json.loads(match[2])
        for client in role_modules.values():
            for imported in re.finditer(rf"({IDENTIFIER})=({IDENTIFIER})\({re.escape(identity)}\)", client):
                alias = re.escape(imported[1])
                # Resolve only literal exports actually passed to the public search client.
                call = rf"\)\({alias}\.({IDENTIFIER}),{alias}\.({IDENTIFIER}),\{{responsesCache:"
                for args in re.finditer(call, client):
                    application = literals.get(exports.get(args[1]))
                    credential = literals.get(exports.get(args[2]))
                    if application == APP_ID and isinstance(credential, str) and 16 <= len(credential) <= 2048:
                        credentials.add(credential)
    if len(credentials) != 1:
        raise ValueError("Cannot resolve an unambiguous public Rippling search credential from static frontend data")
    result.pages.append({"url": URL, "phase": "public_search_configuration", "bundles": sources, "index": INDEX})
    return {"X-Algolia-Application-Id": APP_ID, "X-Algolia-API-Key": credentials.pop()}


def job_id(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Rippling jobId must be a canonical UUID")
    return value


def location_cities(locations):
    cities = set()
    unresolved = not locations
    for location in locations:
        if not isinstance(location, dict) or not isinstance(location.get("name"), str) or not location["name"].strip():
            raise ValueError("Rippling search location must supply a name and country evidence")
        country = location.get("country")
        code = location.get("countryCode")
        india = country == "India" or code == "IN"
        if india and (country not in (None, "", "India") or code not in (None, "", "IN")):
            raise ValueError("Rippling location country fields disagree")
        named = text_cities(location["name"])
        broad = "remote" in location["name"].casefold() or location["name"].strip().casefold() in ("india", "multiple locations")
        if india:
            cities.update(named)
        if (not country and not code and (named or broad)) or (india and not named and broad):
            unresolved = True
    return sorted(cities), unresolved


def merge_hit(groups, row):
    identity = job_id(row["jobId"])
    object_id = row["objectID"]
    if not isinstance(object_id, str) or not object_id.startswith(identity + "__") or object_id == identity + "__":
        raise ValueError("Rippling location-expanded objectID does not match jobId")
    url = public_url(row["url"], {"ats.rippling.com"})
    if url != "https://ats.rippling.com/rippling/jobs/" + identity:
        raise ValueError("Rippling search URL does not identify its native board and job UUID")
    title = row["name"]
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Rippling search hit has no title")
    locations = require_list(row.get("locations"), "locations")
    location_cities(locations)
    names = require_list(row.get("locationNames"), "locationNames")
    if any(not isinstance(name, str) for name in names) or set(names) != {location["name"] for location in locations}:
        raise ValueError("Rippling locationNames disagree with structured locations")
    signature = (title.strip(), url, row.get("departmentName"), row.get("department"))
    if identity not in groups:
        groups[identity] = {"signature": signature, "locations": [], "location_names": [], "object_ids": []}
    group = groups[identity]
    if group["signature"] != signature:
        raise ValueError("Rippling same-job location hits have conflicting title, URL or department")
    for location in locations:
        if location not in group["locations"]:
            group["locations"].append(location)
    for name in names:
        if name not in group["location_names"]:
            group["location_names"].append(name)
    group["object_ids"].append(object_id)


def search_page(http, headers, page_number, result, phase="inventory"):
    params = {"query": "", "page": page_number, "hitsPerPage": PAGE_SIZE}
    url = SEARCH_URL + "?" + urlencode(params)
    payload = http.json(url, headers=headers)
    rows = require_list(payload.get("hits"), "hits")
    total = require_total(payload.get("nbHits"))
    pages = require_total(payload.get("nbPages"))
    result.pages.append({"url": url, "phase": phase, "page": page_number,
                         "returned": len(rows), "reported_total": total, "reported_pages": pages,
                         "exhaustive_count": payload.get("exhaustiveNbHits")})
    if payload.get("exhaustiveNbHits") is not True or payload.get("exhaustive", {}).get("nbHits", True) is not True:
        raise ValueError("Rippling public search count is not exhaustive")
    if payload.get("page") != page_number or payload.get("hitsPerPage") != PAGE_SIZE or payload.get("query") != "":
        raise ValueError("Rippling did not honor unfiltered search pagination")
    echoed = parse_qs(payload.get("params", ""), keep_blank_values=True)
    if echoed != {key: [str(value)] for key, value in params.items()}:
        raise ValueError("Rippling search parameters changed or unexpected filters were applied")
    if len(rows) > PAGE_SIZE or pages > MAX_PAGES:
        raise ValueError("Rippling public search exceeded the bounded pagination budget")
    return rows, total, pages


def normalize(identity, group):
    title, url, department, department_id = group["signature"]
    cities, unresolved = location_cities(group["locations"])
    job = posting("rippling", identity, title, url, group["locations"], cities, "",
                  source_url=SEARCH_URL, department=department, department_id=department_id,
                  algolia_object_ids=group["object_ids"], location_names=group["location_names"])
    if unresolved and not cities:
        job["location_status"] = "unresolved"
    return job


def detail(http, job):
    data = PageData(http.text(job["url"])).next_data()["props"]["pageProps"]["apiData"]["jobPost"]
    if job_id(data["uuid"]) != job["id"] or data.get("url") != job["url"]:
        raise ValueError("Rippling native detail UUID or URL differs from its search hit")
    board = data["board"]
    if data.get("companyName") != "Rippling" or board.get("slug") != "rippling" or board.get("companyName") != "Rippling":
        raise ValueError("Rippling detail does not belong to the Rippling company and board")
    if not isinstance(data.get("unlistedFromSearch"), bool):
        raise ValueError("Rippling native detail is missing its public-listing flag")
    job["public"] = not data["unlistedFromSearch"]
    if not isinstance(data.get("name"), str) or data["name"].strip() != job["title"]:
        raise ValueError("Rippling native detail title changed after search")
    locations = require_list(data.get("workLocations"), "workLocations")
    if any(not isinstance(location, str) for location in locations):
        raise ValueError("Rippling native workLocations are not text")
    cities, unresolved = location_cities([
        {"name": location, "country": "India" if re.search(r"\bindia\b", location, re.I) else None}
        for location in locations
    ])
    if not city_keys(job["cities"]) <= city_keys(cities):
        raise ValueError("Rippling native work locations no longer include the listing's India cities")
    description = data["description"]
    role = clean_text(description.get("role"))
    if not role:
        raise ValueError("Rippling native detail has no full role description")
    job.update(description="\n\n".join(part for part in (clean_text(description.get("company")), role) if part),
               cities=cities, work_locations=locations, published_at=data.get("createdOn"),
               employment_type=data.get("employmentType"), board_slug=board["slug"],
               location_status="unresolved" if unresolved and not cities else "outside")


def collect(http, result):
    headers = search_headers(http, result)
    groups = {}
    seen = set()
    expected = pages = None
    first_ids = None
    complete = False
    request_failed = False
    try:
        for page_number in range(MAX_PAGES + 1):
            rows, total, count = search_page(http, headers, page_number, result)
            if expected is None:
                expected, pages = total, count
            terminal = not rows and page_number == pages and len(seen) == expected
            if (total != expected or count != pages) and not (terminal and total == count == 0):
                raise ValueError("Rippling search total or page count changed during collection")
            ids = [row["objectID"] for row in rows]
            if first_ids is None:
                first_ids = ids
            for row in rows:
                if row["objectID"] in seen:
                    raise ValueError("Rippling repeated a raw location hit within pagination")
                merge_hit(groups, row)
                seen.add(row["objectID"])
            if pages != (expected + PAGE_SIZE - 1) // PAGE_SIZE:
                raise ValueError("Rippling public search retrieval cap prevents exhaustive inventory")
            if not rows:
                if len(seen) != expected or page_number != pages:
                    raise ValueError("Rippling search ended before its raw-hit count reconciled")
                check, total, count = search_page(http, headers, 0, result, phase="total_recheck")
                if total != expected or count != pages or [row["objectID"] for row in check] != first_ids:
                    raise ValueError("Rippling inventory changed during the final count and first-page recheck")
                complete = True
                break
            if page_number >= pages or len(rows) != min(PAGE_SIZE, expected - page_number * PAGE_SIZE):
                raise ValueError("Rippling raw page size does not reconcile to the public search total")
        else:
            raise ValueError("Rippling exceeded the public search pagination budget")
    except FetchError as error:
        result.errors.append(f"Inventory: {error}; stopping further requests")
        request_failed = True
    except (ValueError, KeyError, TypeError) as error:
        result.errors.append(f"Inventory: {error}")
    finally:
        headers.clear()
    result.pages.append({"url": SEARCH_URL, "phase": "identity_reconciliation",
                         "raw_hits": len(seen), "unique_jobs": len(groups), "reported_total": expected})
    for identity, group in groups.items():
        result.add(normalize(identity, group))
    result.listing_complete = complete
    if request_failed:
        return
    for job in result.records.values():
        if job["location_status"] not in ("in_scope", "unresolved"):
            continue
        try:
            detail(http, job)
            if city_keys(job["cities"]) & city_keys(result.cities):
                job["location_status"] = "in_scope"
        except FetchError as error:
            result.errors.append(f"Detail {job['id']}: {error}; stopping further requests")
            break
        except (ValueError, KeyError, TypeError) as error:
            result.errors.append(f"Detail {job['id']}: {error}")
