import re

from common import posting, text_cities
from workday import collect_india, detail_info


HOSTS = {"salesforce.wd12.myworkdayjobs.com"}
SITE = "External_Career_Site"
BASE = "https://salesforce.wd12.myworkdayjobs.com/wday/cxs/salesforce/" + SITE
ID_PATTERN = r"JR\d+"


def normalize(row, payload, india_id):
    info, description, locations, url = detail_info(
        row, payload, site=SITE, pattern=ID_PATTERN, hosts=HOSTS)
    cities = []
    unresolved = False
    for location in locations:
        named = text_cities(location)
        if named and re.match(r"^India\s+-\s+", location, re.I):
            cities.extend(named)
        elif named:
            unresolved = True
    primary_india = bool(re.match(r"^India\s+-\s+", locations[0], re.I))
    country = info["country"]
    if primary_india and (country["id"] != india_id or country["descriptor"].casefold() != "india"):
        raise ValueError("Salesforce primary location contradicts its structured country")
    if not any(re.match(r"^India\s+-\s+", location, re.I) for location in locations):
        raise ValueError("Salesforce India-filtered posting has no explicit India location")
    if unresolved:
        raise ValueError("Salesforce target-city label lacks explicit India location evidence")
    job = posting(
        "salesforce", info["jobReqId"], info.get("title"), url, locations, cities, description,
        source_url=BASE + row["externalPath"], source_site=SITE,
        source_scope="Workday main External_Career_Site India inventory",
        listing_title=row["title"], listing_location=row["locationsText"],
        requisition_id=info["jobReqId"], workday_posting_id=info.get("id"),
        published_at=info.get("startDate"), country=country,
        requisition_location=info.get("jobRequisitionLocation"),
        time_type=info.get("timeType"), remote_type=info.get("remoteType"),
        can_apply=info["canApply"], posted=info["posted"])
    if row["title"] != info["title"]:
        job["warnings"].append("Search title differs from live detail; current detail title takes precedence")
    if not info["canApply"]:
        raise ValueError(f"Salesforce posting {info['jobReqId']} is no longer accepting applications")
    return job


def collect(http, result):
    result.warnings.extend([
        "Scope: Salesforce Workday External_Career_Site only, not entire-company/all-brand coverage; separate brand, research and early-career boards are excluded",
        "Salesforce static jobs_1/jobs_2 reports have previously differed from live locations/descriptions; this scan uses live Workday details only, not a static-feed union",
    ])
    collect_india(http, result, base=BASE, site=SITE, pattern=ID_PATTERN, normalize=normalize)
