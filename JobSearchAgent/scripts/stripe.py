import json
import re

from common import FetchError, PageData, city_keys, clean_text, posting, public_url, require_list, text_cities


HOSTS = {"stripe.com"}
ORIGIN = "https://stripe.com"
URL = ORIGIN + "/careers/search"
SCOPE = "Official Stripe careers index snapshot; not the Greenhouse API inventory"


def identity(value):
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)):
        raise ValueError("Stripe greenhouseId must be a numeric posting ID")
    return str(value)


def indexed(values, indices, field):
    selected = []
    for index in require_list(indices, field):
        if type(index) is not int or not 0 <= index < len(values):
            raise ValueError(f"Stripe {field} contains an invalid index")
        selected.append(values[index])
    return selected


def location_cities(locations):
    cities = []
    unresolved = not locations
    for location in locations:
        if not isinstance(location, dict) or not isinstance(location.get("name"), str) or not location["name"].strip():
            raise ValueError("Stripe location requires a name")
        country = location.get("countryCode")
        if country is not None and (not isinstance(country, str) or not re.fullmatch(r"[A-Z]{2}", country)):
            raise ValueError("Stripe location has an invalid countryCode")
        if "remote" in location and not isinstance(location["remote"], bool):
            raise ValueError("Stripe location has an invalid remote marker")
        named = text_cities(location["name"])
        if country == "IN":
            cities.extend(named)
            unresolved = unresolved or not named
        elif country is None and (named or location.get("remote") or "remote" in location["name"].casefold()):
            unresolved = True
    return sorted(set(cities)), unresolved


def normalize(row, locations, teams):
    job_id = identity(row["greenhouseId"])
    slug = row["slug"]
    if not isinstance(slug, str) or not re.fullmatch(r"[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)*", slug):
        raise ValueError("Stripe listing slug has an unexpected format")
    assigned = indexed(locations, row.get("locationIndices"), "locationIndices")
    department = indexed(teams, row.get("teamIndices"), "teamIndices")
    cities, unresolved = location_cities(assigned)
    job = posting("stripe", job_id, row["title"],
                  public_url(f"{ORIGIN}/careers/listing/{slug}/{job_id}", HOSTS),
                  assigned, cities, "", source_url=URL, source_scope=SCOPE,
                  slug=slug, department=[team["name"] for team in department],
                  employment_type=row.get("employmentType"))
    if unresolved and not cities:
        job["location_status"] = "unresolved"
    return job


def jsonld_detail(page, job):
    candidates = []
    for script in page.scripts:
        try:
            data = json.loads("".join(script["parts"]))
        except (ValueError, TypeError):
            continue
        nodes = data if isinstance(data, list) else [data]
        while nodes:
            node = nodes.pop()
            if not isinstance(node, dict):
                continue
            if isinstance(node.get("@graph"), list):
                nodes.extend(node["@graph"])
            kind = node.get("@type")
            if kind == "JobPosting" or isinstance(kind, list) and "JobPosting" in kind:
                candidates.append(node)
    if len(candidates) != 1:
        raise ValueError("Stripe detail requires one JSON-LD JobPosting")
    data = candidates[0]
    identifier = data.get("identifier")
    if not isinstance(identifier, dict) or identity(identifier.get("value")) != job["id"]:
        raise ValueError("Stripe JSON-LD ID differs from the index")
    if data.get("title") != job["title"] or data.get("url") != job["url"]:
        raise ValueError("Stripe JSON-LD title or URL differs from the index")
    organization = data.get("hiringOrganization")
    if not isinstance(organization, dict) or organization.get("name") != "Stripe":
        raise ValueError("Stripe JSON-LD employer is missing or changed")
    locations = data.get("jobLocation")
    if isinstance(locations, dict):
        locations = [locations]
    assigned = []
    for location in require_list(locations, "jobLocation"):
        address = location["address"]
        country = address.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name")
        assigned.append({"name": address["addressLocality"],
                         "countryCode": "IN" if country == "India" else country})
    cities, unused = location_cities(assigned)
    if not city_keys(job["cities"]) <= city_keys(cities):
        raise ValueError("Stripe JSON-LD no longer includes the index's exact India cities")
    description = clean_text(data.get("description"))
    if not description:
        raise ValueError("Stripe JSON-LD has no full description")
    return description, data.get("datePosted"), "JSON-LD"


def detail(page, job):
    if any(script["id"] == "__NEXT_DATA__" for script in page.scripts):
        data = page.next_data()["props"]["pageProps"]["listing"]
        if identity(data.get("greenhouseId")) != job["id"]:
            raise ValueError("Stripe detail ID differs from the index")
        if data.get("slug") != job["slug"] or data.get("title") != job["title"]:
            raise ValueError("Stripe detail slug or title differs from the index")
        locations = require_list(data.get("locations"), "detail.locations")
        cities, unused = location_cities(locations)
        if not city_keys(job["cities"]) <= city_keys(cities):
            raise ValueError("Stripe detail no longer includes the index's exact India cities")
        description = clean_text(data.get("contentMarkdown"))
        if description:
            return description, data.get("postedAt"), "Next.js listing.contentMarkdown"
    return jsonld_detail(page, job)


def collect(http, result):
    result.warnings.append(SCOPE + "; known source differences are not reconciled or unioned")
    page = PageData(http.text(URL))
    data = page.next_data()["props"]["pageProps"]["jobIndexData"]
    locations = require_list(data["filters"]["locations"], "filters.locations")
    teams = require_list(data["filters"]["teams"], "filters.teams")
    location_cities(locations)
    for location in locations:
        if "parentLocationIndex" in location:
            indexed(locations, [location["parentLocationIndex"]], "parentLocationIndex")
    for team in teams:
        if not isinstance(team, dict) or not isinstance(team.get("name"), str) or not team["name"].strip():
            raise ValueError("Stripe team requires a name")
    rows = require_list(data["listings"], "listings")
    receipt = {"url": URL, "returned": len(rows), "source_scope": SCOPE,
               "pagination": "Entire embedded jobIndexData.listings array"}
    result.pages.append(receipt)
    for row in rows:
        result.add(normalize(row, locations, teams))
    receipt["unique_ids"] = len(result.records)
    if len(result.records) != len(rows):
        raise ValueError("Stripe official index did not reconcile to unique greenhouseIds")
    result.listing_complete = True
    for job in result.inventory():
        try:
            description, published_at, source = detail(PageData(http.text(job["url"])), job)
            job.update(description=description, published_at=published_at, description_source=source)
        except FetchError as error:
            result.errors.append(f"Detail {job['id']}: {error}; stopping further detail requests")
            break
        except (ValueError, KeyError, TypeError, AttributeError, UnicodeError, OSError) as error:
            result.errors.append(f"Detail {job['id']}: {error}")
