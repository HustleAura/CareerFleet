from urllib.parse import urlencode

from common import clean_text, posting, require_list, require_total


ORIGIN = "https://iaziqy.fa.ocs.oraclecloud.com"
HOSTS = {"iaziqy.fa.ocs.oraclecloud.com"}
BASE = ORIGIN + "/hcmRestApi/resources/latest/"
CITY_IDS = {"Hyderabad": "100000031677115", "Bengaluru": "100000031682312"}


def normalize(row):
    locations = [{"city": row.get("PrimaryLocation"), "country": row.get("PrimaryLocationCountry"),
                  "geography_id": str(row.get("GeographyId"))}]
    for location in require_list(row.get("secondaryLocations", []), "secondaryLocations"):
        locations.append({"city": location.get("Name"), "country": location.get("CountryCode"),
                          "geography_id": str(location.get("GeographyId"))})
    cities = [city for city, identity in CITY_IDS.items() if any(
        location["country"] == "IN" and location["geography_id"] == identity for location in locations)]
    identity = str(row["Id"])
    if not identity.isdigit():
        raise ValueError("Uber job ID must be numeric")
    job = posting("uber", identity, row["Title"], f"https://jobs.uber.com/en/jobs/{identity}/",
                  locations, cities, "", source_url=BASE + "recruitingCEJobRequisitions",
                  published_at=row.get("PostedDate"), department=row.get("Department"), job_type=row.get("JobType"))
    job["expires_at"] = row.get("PostingEndDate")
    if not cities:
        job["location_status"] = "unresolved"
    return job


def collect(http, result):
    offset = 0
    expected = None
    while True:
        selected = ";".join(CITY_IDS[city] for city in result.cities)
        finder = (f"findReqs;siteNumber=UberCareers,facetsList=LOCATIONS;WORK_LOCATIONS,limit=100,"
                  f"sortBy=POSTING_DATES_DESC,offset={offset},selectedLocationsFacet={selected}")
        url = BASE + "recruitingCEJobRequisitions?" + urlencode({
            "onlyData": "true", "expand": "requisitionList.workLocation,requisitionList.secondaryLocations", "finder": finder})
        payload = http.json(url)
        items = require_list(payload["items"], "items")
        if len(items) != 1:
            raise ValueError("Uber search envelope must contain exactly one search result")
        search = items[0]
        rows = require_list(search["requisitionList"], "requisitionList")
        total = require_total(search.get("TotalJobsCount"))
        if search.get("Offset") != offset or search.get("SelectedLocationsFacet") != selected:
            raise ValueError("Uber did not honor the requested offset/location facets")
        result.pages.append({"url": url, "offset": offset, "returned": len(rows), "reported_total": total})
        if expected is None:
            expected = total
        if total != expected:
            raise ValueError("Uber total changed during pagination")
        for row in rows:
            result.add(normalize(row))
        if not rows:
            if len(result.records) != expected:
                raise ValueError("Uber unique postings do not reconcile to TotalJobsCount")
            result.listing_complete = True
            break
        offset += len(rows)
        if offset > expected:
            raise ValueError("Uber returned more postings than TotalJobsCount")
    for job in result.inventory():
        url = BASE + f"recruitingCEJobRequisitionDetails/{job['id']}?onlyData=true"
        try:
            detail = http.json(url)
            if str(detail["Id"]) != job["id"]:
                raise ValueError("Uber detail ID mismatch")
            if detail.get("PrimaryLocationCountry") != "IN":
                raise ValueError("Uber detail country changed; location needs rechecking")
            job["description"] = clean_text(detail.get("ExternalDescriptionStr"))
            job["required"] = clean_text(detail.get("ExternalQualificationsStr"))
            job["responsibilities"] = clean_text(detail.get("ExternalResponsibilitiesStr"))
            job["detail_url"] = url
            job["expires_at"] = detail.get("ExternalPostedEndDate")
            result.records.pop(job["key"])
            result.add(job)
        except (ValueError, KeyError, TypeError) as error:
            result.errors.append(f"Detail {job['id']}: {error}")