import re
from urllib.parse import urlsplit

from common import SEARCH_POST_URLS, clean_text, public_url, require_list, require_total


PAGE_SIZE = 20
MAX_POSTINGS = 10_000


def facets(payload):
    def walk(items):
        for item in require_list(items, "facets"):
            if not isinstance(item, dict) or not isinstance(item.get("facetParameter"), str):
                raise ValueError("Workday facet has no parameter")
            values = require_list(item.get("values"), "facet.values")
            if any(not isinstance(value, dict) for value in values):
                raise ValueError("Workday facet values must be objects")
            yield item
            nested = [value for value in values if "facetParameter" in value]
            if nested:
                yield from walk(nested)

    return list(walk(payload.get("facets")))


def india_filter(payload):
    matches = []
    for facet in facets(payload):
        if (facet.get("descriptor") or "").strip().casefold() != "country":
            continue
        for value in facet["values"]:
            if (value.get("descriptor") or "").strip().casefold() == "india":
                identity = value.get("id")
                if not isinstance(identity, str) or not identity.strip():
                    raise ValueError("Workday India facet has no ID")
                matches.append(({facet["facetParameter"]: [identity]}, require_total(value.get("count"))))
    if len(matches) != 1:
        raise ValueError("Workday requires exactly one advertised India country facet; no keyword fallback")
    return matches[0]


def listing_id(row, pattern):
    if not isinstance(row, dict):
        raise ValueError("Workday posting summary must be an object")
    bullets = require_list(row.get("bulletFields"), "bulletFields")
    identities = [value for value in bullets if isinstance(value, str) and re.fullmatch(pattern, value)]
    if len(identities) != 1:
        raise ValueError("Workday listing has no unique requisition ID")
    identity = identities[0]
    path = row.get("externalPath")
    if (not isinstance(path, str) or not path.startswith("/job/")
            or "?" in path or "#" in path
            or not re.search("_" + re.escape(identity) + r"(?:-\d+)?$", path)
            or any(part in (".", "..", "") for part in path.split("/")[1:])):
        raise ValueError("Workday listing path does not reconcile to its requisition ID")
    if not isinstance(row.get("title"), str) or not row["title"].strip():
        raise ValueError("Workday listing has no title")
    if not isinstance(row.get("locationsText"), str) or not row["locationsText"].strip():
        raise ValueError("Workday listing has no location summary")
    return identity


def detail_info(row, payload, *, site, pattern, hosts):
    identity = listing_id(row, pattern)
    if not isinstance(payload, dict) or payload.get("userAuthenticated") is not False:
        raise ValueError("Workday detail is not an anonymous public response")
    info = payload.get("jobPostingInfo")
    if not isinstance(info, dict) or info.get("jobReqId") != identity:
        raise ValueError("Workday detail jobReqId does not match listing ID")
    if info.get("jobPostingSiteId") != site:
        raise ValueError("Workday detail belongs to a different posting site")
    if not isinstance(info.get("posted"), bool) or not isinstance(info.get("canApply"), bool):
        raise ValueError("Workday detail public/active flags are missing")
    if info["posted"] is not True:
        raise ValueError(f"Workday listing {identity} is no longer publicly posted")
    url = public_url(info.get("externalUrl"), hosts)
    parsed = urlsplit(url)
    if parsed.path != "/" + site + row["externalPath"] or parsed.query or parsed.fragment:
        raise ValueError("Workday external URL does not reconcile to the listing and site")
    description = clean_text(info.get("jobDescription"))
    if not description:
        raise ValueError(f"Workday detail {identity} has no full description")
    location = info.get("location")
    additional = require_list(info.get("additionalLocations", []), "additionalLocations")
    locations = [location] + additional
    if any(not isinstance(value, str) or not value.strip() for value in locations):
        raise ValueError("Workday detail has unresolved location fields")
    locations = [value.strip() for value in locations]
    if any(re.fullmatch(r"\d+\s+Locations?", value, re.I) for value in locations):
        raise ValueError("Workday detail still contains an aggregate location summary")
    if len(set(locations)) != len(locations):
        raise ValueError("Workday detail repeats a primary/additional location")
    summary = re.fullmatch(r"(\d+)\s+Locations?", row["locationsText"].strip(), re.I)
    if summary and int(summary.group(1)) != len(locations):
        raise ValueError("Workday location count changed between listing and detail")
    country = info.get("country")
    if not isinstance(country, dict) or not isinstance(country.get("descriptor"), str) or not country.get("id"):
        raise ValueError("Workday detail has no structured country evidence")
    return info, description, locations, url


def search_page(http, result, url, applied, offset, phase, limit=PAGE_SIZE):
    if url not in SEARCH_POST_URLS:
        raise ValueError("Unsupported Workday search endpoint")
    payload = http.post_json(url, {
        "appliedFacets": applied, "limit": limit, "offset": offset, "searchText": "",
    })
    if not isinstance(payload, dict) or payload.get("userAuthenticated") is not False:
        raise ValueError("Workday search is not an anonymous public response")
    rows = require_list(payload.get("jobPostings"), "jobPostings")
    total = require_total(payload.get("total"))
    result.pages.append({
        "url": url, "phase": phase, "applied_facets": applied, "offset": offset,
        "limit": limit, "returned": len(rows), "reported_total": total,
    })
    if len(rows) > limit:
        raise ValueError("Workday returned more rows than the requested limit")
    return payload


def collect_india(http, result, *, base, site, pattern, normalize):
    url = base + "/jobs"
    discovery = search_page(http, result, url, {}, 0, "country_discovery", limit=1)
    if discovery["total"] == 0:
        fresh = search_page(http, result, url, {}, 0, "empty_board_reconciliation", limit=1)
        if discovery["jobPostings"] or fresh["total"] != 0 or fresh["jobPostings"]:
            raise ValueError("Workday empty-board total does not reconcile to its postings")
        result.listing_complete = True
        return
    applied, country_count = india_filter(discovery)
    first = search_page(http, result, url, applied, 0, "india_inventory")
    expected = require_total(first["total"])
    if expected > MAX_POSTINGS:
        raise ValueError("Workday India inventory exceeds the bounded traversal budget")
    if india_filter(first) != (applied, expected) or country_count != expected:
        raise ValueError("Workday India facet and filtered first-page total do not reconcile")
    if expected > discovery["total"]:
        raise ValueError("Workday India total exceeds the unfiltered board total")
    india_id = next(iter(applied.values()))[0]
    offset = 0
    seen = set()
    page = first
    first_ids = [listing_id(row, pattern) for row in first["jobPostings"]]
    while True:
        rows = page["jobPostings"]
        total = require_total(page["total"])
        # These two public tenants return total=0 on later, nonempty pages.
        if offset and total not in (0, expected):
            raise ValueError("Workday noninitial total changed during pagination")
        if offset and not total and rows:
            warning = "Workday later pages report total=0 despite rows; completion uses the initial-total bound and fresh first-page reconciliation"
            if warning not in result.warnings:
                result.warnings.append(warning)
        if not rows:
            if offset != expected:
                raise ValueError("Workday pagination ended before the initial total")
            break
        if offset + len(rows) > expected:
            raise ValueError("Workday returned rows beyond the initial total; inventory drifted")
        for row in rows:
            identity = listing_id(row, pattern)
            if identity in seen:
                raise ValueError(f"Workday repeated a listing ID/page: {identity}")
            seen.add(identity)
            detail_url = public_url(base + row["externalPath"], {urlsplit(base).hostname})
            job = normalize(row, http.json(detail_url), india_id)
            if job["id"] != identity or job.get("source_site") != site:
                raise ValueError("Workday normalizer changed the verified posting identity/site")
            result.add(job)
        offset += len(rows)
        # At offset=total these tenants restart page zero instead of returning [].
        if offset == expected:
            result.pages[-1]["terminal_bound_reached"] = True
            break
        page = search_page(http, result, url, applied, offset, "india_inventory")
    fresh = search_page(http, result, url, applied, 0, "india_reconciliation")
    if (fresh["total"] != expected or india_filter(fresh) != (applied, expected)
            or [listing_id(row, pattern) for row in fresh["jobPostings"]] != first_ids
            or fresh["jobPostings"] != first["jobPostings"]):
        raise ValueError("Workday fresh first-page reconciliation changed; inventory is partial")
    if len(seen) != expected:
        raise ValueError("Workday unique listing IDs do not reconcile to the initial total")
    if result.unresolved():
        raise ValueError("Workday has unresolved target-city country/location evidence")
    result.listing_complete = True
