from urllib.parse import urlsplit

from common import text_cities
from greenhouse import (
    bare_cities, fetch_jobs, finish_jobs, identity, is_india, locate,
    normalize_posting, office_record,
)


HOSTS = {"boards-api.greenhouse.io"}
URL = "https://boards-api.greenhouse.io/v1/boards/arcesiumllc/jobs?content=true"
OFFICE_URL = "https://boards-api.greenhouse.io/v1/boards/arcesiumllc/offices/"
POSTING_HOSTS = {"job-boards.greenhouse.io", "boards.greenhouse.io"}


class OfficeAncestry:
    def __init__(self, http, result):
        self.http = http
        self.result = result
        self.offices = {}

    def remember(self, office):
        previous = self.offices.get(office["id"])
        if previous is not None and previous != office:
            raise ValueError(f"Conflicting Greenhouse office metadata: {office['id']}")
        self.offices[office["id"]] = office

    def india(self, office):
        self.remember(office)
        chain = []
        seen = set()
        while True:
            if office["id"] in seen or len(seen) >= 16:
                raise ValueError("Greenhouse office ancestry is cyclic or exceeds the depth limit")
            seen.add(office["id"])
            chain.append(office)
            if is_india(office["name"] + " " + office["location"]):
                return {"office_chain": list(chain), "source_url": OFFICE_URL + str(office["id"])}
            parent = office["parent_id"]
            if parent is None:
                return None
            if parent not in self.offices:
                url = OFFICE_URL + str(identity(parent, "office parent_id"))
                ancestor = office_record(self.http.json(url))
                if ancestor["id"] != parent:
                    raise ValueError("Greenhouse office detail identity differs from its request")
                self.remember(ancestor)
                self.result.pages.append({"url": url, "office_id": parent, "kind": "office_ancestry"})
            ancestor = self.offices[parent]
            if office["id"] not in ancestor["child_ids"]:
                raise ValueError("Greenhouse office parent/child links do not reconcile")
            office = ancestor


def normalize(row, ancestry):
    job = normalize_posting("arcesium", row, URL, POSTING_HOSTS)
    if urlsplit(job["url"]).path.rstrip("/") != "/arcesiumllc/jobs/" + job["id"]:
        raise ValueError("Arcesium posting URL does not reconcile to its board and Greenhouse ID")
    countries = {}
    named = text_cities(job["posting_location"])
    for office in job["offices"]:
        ancestry.remember(office)
        text = office["name"] + " " + office["location"]
        if text_cities(text) or (named and bare_cities(job["posting_location"])) or is_india(text):
            country = ancestry.india(office)
            if country:
                countries[office["id"]] = country
    return locate(job, countries)


def collect(http, result):
    rows, total = fetch_jobs(http, result, URL)
    ancestry = OfficeAncestry(http, result)
    for row in rows:
        result.add(normalize(row, ancestry))
    finish_jobs(result, rows, total)
