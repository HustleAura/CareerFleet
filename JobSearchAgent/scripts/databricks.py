from urllib.parse import parse_qs, urlsplit

from common import city_keys, text_cities
from greenhouse import bare_cities, fetch_jobs, finish_jobs, is_foreign_target, is_india, locate, normalize_posting


HOSTS = {"boards-api.greenhouse.io"}
URL = "https://boards-api.greenhouse.io/v1/boards/databricks/jobs?content=true"
POSTING_HOSTS = {"databricks.com", "www.databricks.com"}


def normalize(row):
    job = normalize_posting("databricks", row, URL, POSTING_HOSTS)
    url = urlsplit(job["url"])
    if (url.path != "/company/careers/open-positions/job"
            or parse_qs(url.query).get("gh_jid") != [job["id"]]):
        raise ValueError("Databricks posting URL does not reconcile to the Greenhouse ID")
    countries = {
        office["id"]: {"name": office["name"], "location": office["location"]}
        for office in job["offices"] if is_india(office["name"] + " " + office["location"])
    }
    if is_india(job["posting_location"]) and not is_foreign_target(job["posting_location"]):
        for office in job["offices"]:
            text = office["name"] + " " + office["location"]
            if text_cities(text) and bare_cities(text) and office["id"] not in countries:
                countries[office["id"]] = {"posting_location": job["posting_location"]}
    locate(job, countries)
    advertised = city_keys(text_cities(job["posting_location"]))
    assigned = city_keys(job["cities"])
    if assigned - advertised:
        job["warnings"].append("India city association also comes from assigned office metadata; posting label retained")
    return job


def collect(http, result):
    rows, total = fetch_jobs(http, result, URL)
    for row in rows:
        result.add(normalize(row))
    finish_jobs(result, rows, total)
