import re

from common import posting, text_cities
from workday import collect_india, detail_info


HOSTS = {"adobe.wd5.myworkdayjobs.com"}
SITE = "external_experienced"
BASE = "https://adobe.wd5.myworkdayjobs.com/wday/cxs/adobe/" + SITE
ID_PATTERN = r"R\d+"


def normalize(row, payload, india_id):
    info, description, locations, url = detail_info(
        row, payload, site=SITE, pattern=ID_PATTERN, hosts=HOSTS)
    country = info["country"]
    india = country["id"] == india_id and country["descriptor"].strip().casefold() == "india"
    requisition = info.get("jobRequisitionLocation")
    if not isinstance(requisition, dict) or not isinstance(requisition.get("country"), dict):
        raise ValueError("Adobe detail has no requisition-location country evidence")
    requisition_country = requisition["country"]
    if (requisition_country.get("id") != country["id"]
            or requisition_country.get("descriptor") != country["descriptor"]
            or (india and requisition_country.get("alpha2Code") != "IN")):
        raise ValueError("Adobe detail country and requisition-location country do not reconcile")
    cities = []
    unresolved = False
    for location in locations:
        named = text_cities(location)
        explicit_india = bool(re.search(r"\bindia\b", location, re.I))
        bare_city = location.casefold() in ("bangalore", "bengaluru", "hyderabad")
        if named and (explicit_india or (india and bare_city)):
            cities.extend(named)
        elif named:
            unresolved = True
    if not india and not any(re.search(r"\bindia\b", location, re.I) for location in locations):
        raise ValueError("Adobe India-filtered posting has no verifiable India location")
    if unresolved:
        raise ValueError("Adobe target-city label lacks unambiguous India location evidence")
    job = posting(
        "adobe", info["jobReqId"], info.get("title"), url, locations, cities, description,
        source_url=BASE + row["externalPath"], source_site=SITE,
        source_scope="Workday external_experienced India inventory",
        listing_title=row["title"], listing_location=row["locationsText"],
        requisition_id=info["jobReqId"], workday_posting_id=info.get("id"),
        published_at=info.get("startDate"), country=country,
        requisition_location=requisition, time_type=info.get("timeType"),
        remote_type=info.get("remoteType"), can_apply=info["canApply"], posted=info["posted"])
    if row["title"] != info["title"]:
        job["warnings"].append("Search title differs from live detail; current detail title takes precedence")
    if not info["canApply"]:
        raise ValueError(f"Adobe posting {info['jobReqId']} is no longer accepting applications")
    return job


def collect(http, result):
    result.warnings.extend([
        "Scope: Adobe Workday external_experienced India inventory; Phenom previously advertised fewer jobs than Workday and is not merged or assumed equivalent",
        "Current Workday detail titles, not stale URL slugs, determine eligibility; the unchanged title policy excludes Computer Scientist titles",
    ])
    collect_india(http, result, base=BASE, site=SITE, pattern=ID_PATTERN, normalize=normalize)
