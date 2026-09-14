import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote, urlencode, urljoin, urlsplit

from common import (
    FetchError, PageData, clean_text, posting, public_url,
    require_list, require_total, text_cities,
)


HOSTS = {"careers.snowflake.com"}
ORIGIN = "https://careers.snowflake.com"
URL = ORIGIN + "/us/en/search-results"
SITEMAP = ORIGIN + "/us/en/sitemap.xml"


def page_data(source):
    page = PageData(source)
    matches = []
    for script in page.scripts:
        text = "".join(script["parts"])
        for match in re.finditer(r"(?<![\w$])phApp\.ddo\s*=\s*", text):
            data, unused = json.JSONDecoder().raw_decode(text[match.end():])
            if not isinstance(data, dict):
                raise ValueError("Snowflake phApp.ddo must be a JSON object")
            matches.append(data)
    if len(matches) != 1:
        raise ValueError("Expected one static Snowflake phApp.ddo JSON assignment")
    return matches[0], page


def identity(row):
    value = row["jobId"]
    sequence = row["jobSeqNo"]
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9-]+", value):
        raise ValueError("Snowflake Phenom jobId is missing or malformed")
    if (not isinstance(sequence, str) or not re.fullmatch(r"SNCOUS[A-Z0-9]+", sequence)
            or not sequence.startswith("SNCOUS" + value.replace("-", "").upper() + "EXTERNALENUS")):
        raise ValueError("Snowflake jobSeqNo does not identify the expected Phenom posting and external site")
    return value, sequence


def public_state(row):
    if row.get("companyName") != "Snowflake":
        raise ValueError("Snowflake posting company identity changed")
    visibility = require_list(row.get("jobVisibility"), "jobVisibility")
    if any(not isinstance(value, str) for value in visibility):
        raise ValueError("Snowflake publication flags are malformed")
    if row.get("visibilityType") not in ("External", "Internal") or row.get("siteType") not in ("external", "internal"):
        raise ValueError("Snowflake publication flags are missing or unknown")
    return row["visibilityType"] == "External" and row["siteType"] == "external" and "external" in visibility


def locations(row):
    values = [{"city": row.get("city"), "country": row.get("country"), "location": row.get("location")}]
    for field in ("multi_location", "multi_location_array"):
        if row.get(field) is not None:
            values.extend(require_list(row[field], field))
    unique = []
    cities = set()
    unresolved = False
    for value in values:
        if value in unique:
            continue
        unique.append(value)
        if isinstance(value, str):
            label, country, city = value, "", ""
        elif isinstance(value, dict):
            label, country, city = value.get("location") or "", value.get("country") or "", value.get("city") or ""
            if any(not isinstance(part, str) for part in (label, country, city)):
                raise ValueError("Snowflake structured location fields must be text")
        else:
            raise ValueError("Snowflake location is not text or a structured object")
        named = text_cities(city + " " + label)
        india = country.casefold() in ("india", "in") or bool(re.search(r"\bindia\b", label, re.I))
        if india and country and country.casefold() not in ("india", "in"):
            raise ValueError("Snowflake location country evidence conflicts")
        if india:
            cities.update(named)
        if not label and not city and not country or named and not country and not india:
            unresolved = True
        if india and not named and ("remote" in label.casefold() or label.strip().casefold() in ("", "india", "multiple locations")):
            unresolved = True
        if not country and "remote" in label.casefold():
            unresolved = True
    return unique, sorted(cities), unresolved


def ashby_id(row):
    value = row.get("applyUrl")
    if not value:
        return None
    if not isinstance(value, str):
        raise ValueError("Snowflake application destination metadata must be text")
    parsed = urlsplit(value)
    parts = parsed.path.strip("/").split("/")
    if parsed.scheme == "https" and parsed.hostname == "jobs.ashbyhq.com" and len(parts) == 2 and parts[0] == "snowflake":
        return parts[1]
    return None


def detail_url(sequence, page):
    path = "/us/en/job/" + quote(sequence, safe="")
    candidates = [urljoin(ORIGIN, href) for href in page.links
                  if urlsplit(urljoin(ORIGIN, href)).path in (path, path + "/")
                  or urlsplit(urljoin(ORIGIN, href)).path.startswith(path + "/")]
    return public_url(candidates[0] if candidates else ORIGIN + path, HOSTS)


def normalize(row, page):
    value, sequence = identity(row)
    all_locations, cities, unresolved = locations(row)
    job = posting("snowflake", sequence, row["title"], detail_url(sequence, page), all_locations, cities, "",
                  source_url=URL, phenom_job_id=value, job_seq_no=sequence, ashby_job_id=ashby_id(row),
                  requisition_id=row.get("reqId"), published_at=row.get("postedDate"),
                  department=row.get("department"), employment_type=row.get("type"))
    job["public"] = public_state(row)
    if unresolved and not cities:
        job["location_status"] = "unresolved"
    return job


def search_page(http, offset, result, phase="inventory"):
    url = URL + "?" + urlencode({"from": offset, "s": 1})
    data, page = page_data(http.text(url))
    search = data["eagerLoadRefineSearch"]
    if search.get("status") != 200:
        raise ValueError("Snowflake public search reports an unsuccessful status")
    rows = require_list(search["data"].get("jobs"), "eagerLoadRefineSearch.data.jobs")
    total = require_total(search.get("totalHits"))
    hits = require_total(search.get("hits"))
    result.pages.append({"url": url, "phase": phase, "offset": offset, "returned": len(rows), "reported_total": total})
    if hits != len(rows):
        raise ValueError("Snowflake search hits do not match its returned rows")
    if search.get("eid", {}).get("query") != "" or search.get("eid", {}).get("searchType") != "allJobs":
        raise ValueError("Snowflake did not return its unfiltered all-jobs search")
    return rows, total, page


def detail(http, url, expected_id):
    data, page = page_data(http.text(url))
    block = data["jobDetail"]
    if block.get("status") != 200 or require_total(block.get("hits")) != 1:
        raise ValueError("Snowflake public detail did not return exactly one posting")
    row = block["data"]["job"]
    job = normalize(row, page)
    if job["id"] != expected_id:
        raise ValueError("Snowflake detail identity differs from its sitemap route")
    if not job["public"]:
        raise ValueError("Snowflake sitemap posting is no longer public; description not collected")
    description = clean_text(row.get("description"))
    if not description:
        raise ValueError("Snowflake detail has no full job description")
    job.update(description=description, url=url, source_url=SITEMAP)
    return job


def sitemap(http, result, phase):
    try:
        root = ET.fromstring(http.text(SITEMAP))
    except ET.ParseError as error:
        raise ValueError("Snowflake sitemap is not valid XML") from error
    namespace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    if root.tag != namespace + "urlset":
        raise ValueError("Snowflake public sitemap format changed")
    jobs = {}
    for item in root.findall(namespace + "url"):
        url = item.findtext(namespace + "loc")
        if not isinstance(url, str):
            raise ValueError("Snowflake sitemap entry has no URL")
        parsed = urlsplit(url)
        if not parsed.path.startswith("/us/en/job/"):
            continue
        public_url(url, HOSTS)
        parts = parsed.path.split("/")
        sequence = parts[4]
        if (len(parts) != 6 or not parts[5] or not re.fullmatch(r"SNCOUS[A-Z0-9]+", sequence)
                or parsed.query or parsed.fragment or sequence in jobs):
            raise ValueError("Snowflake sitemap posting routes are malformed or duplicated")
        jobs[sequence] = parsed._replace(path=quote(parsed.path, safe="/%")).geturl()
    result.pages.append({"url": SITEMAP, "phase": phase, "unique_posting_routes": len(jobs)})
    return jobs


def collect_inventory(http, result):
    rows, expected, unused = search_page(http, 0, result, phase="source_total")
    urls = sitemap(http, result, "posting_index")
    if len(urls) != expected or any(identity(row)[1] not in urls for row in rows):
        raise ValueError("Snowflake sitemap identities/count disagree with current public search")
    for sequence, url in urls.items():
        try:
            job = detail(http, url, sequence)
            result.add(job)
        except FetchError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            result.errors.append(f"Detail {sequence}: {error}")
    check, total, unused = search_page(http, 0, result, phase="total_recheck")
    if total != expected or any(identity(row)[1] not in urls for row in check):
        raise ValueError("Snowflake public search changed during sitemap collection")
    if sitemap(http, result, "index_recheck") != urls:
        raise ValueError("Snowflake public sitemap changed during collection")
    result.pages.append({"url": SITEMAP, "phase": "identity_reconciliation", "requested_details": len(urls),
                         "unique_jobs": len(result.records), "reported_total": expected,
                         "distinct_phenom_job_ids": len({job["phenom_job_id"] for job in result.records.values()})})
    result.listing_complete = len(result.records) == expected and not result.errors


def collect(http, result):
    result.warnings.append("Snowflake uses its public sitemap and every full detail, reconciled to search totals; overlapping search pages are not unioned")
    result.warnings.append("Posting identity is the detail-route jobSeqNo; Phenom jobId is reused across distinct postings")
    try:
        collect_inventory(http, result)
    except FetchError as error:
        result.errors.append(f"Inventory: {error}; stopping further requests")
        return
    except (ValueError, KeyError, TypeError) as error:
        result.errors.append(f"Inventory: {error}")
