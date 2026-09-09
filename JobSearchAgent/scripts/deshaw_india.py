from urllib.parse import urljoin

from common import PageData, clean_text, posting, public_url, require_list


HOSTS = {"www.deshawindia.com"}
URL = "https://www.deshawindia.com/careers/work-with-us"
CITIES = {"HYD": "Hyderabad", "BLR": "Bengaluru", "GGM": "Gurugram"}


def normalize(row):
    data = row["data"]
    if str(row["id"]) != str(data["id"]):
        raise ValueError("D. E. Shaw wrapper ID does not match posting ID")
    offices = require_list(row.get("office"), "office")
    metadata = data["jobMetadata"]
    locations = require_list(metadata.get("jobLocations"), "jobLocations")
    office_pairs = {(item.get("abbreviation"), item.get("name")) for item in offices}
    if office_pairs != {(item.get("abbreviation"), item.get("name")) for item in locations}:
        raise ValueError("D. E. Shaw location fields disagree")
    cities = []
    unresolved = not locations
    for code, name in office_pairs:
        if code not in CITIES or CITIES[code] != name:
            unresolved = True
        elif name in ("Hyderabad", "Bengaluru"):
            cities.append(name)
    description = data["jobDescription"]
    html_qualifications = clean_text(description.get("peopleWeAreLookingForHtml"))
    plain_qualifications = clean_text(description.get("peopleWeAreLookingForStr") or description.get("peopleWeAreLookingFor"))
    qualifications = html_qualifications or plain_qualifications
    if not html_qualifications and any(marker in qualifications.casefold() for marker in ("shared with ta", "attached on the ticket", "please use the jd")):
        qualifications = ""
    body = "\n\n".join(part for part in (
        clean_text(description.get("websiteDescription")),
        clean_text(description.get("responsibilitiesHtml") or description.get("responsibilities")),
        qualifications) if part)
    url = public_url(urljoin("https://www.deshawindia.com/careers/", data["jobUrl"].lower()), HOSTS)
    job = posting("deshaw_india", data["id"], data["displayName"], url, locations, cities, body,
                  source_url=URL, qualifications=qualifications,
                  qualification_source="peopleWeAreLookingForHtml" if html_qualifications else "plain_text",
                  department=(data.get("department") or {}).get("name"), job_type=metadata.get("workStatus"))
    if not isinstance(data.get("activeOnJobsListing"), bool):
        raise ValueError("Missing public-listing flag")
    job["public"] = data["activeOnJobsListing"]
    job["exploratory"] = metadata.get("isExploratory") is True
    job["expires_at"] = data.get("validToDate")
    if unresolved and not cities:
        job["location_status"] = "unresolved"
    if html_qualifications and plain_qualifications and html_qualifications != plain_qualifications:
        job["warnings"].append("HTML and plain qualifications differ; using public HTML version")
    if not qualifications and not job["exploratory"]:
        job["warnings"].append("No usable qualifications supplied")
    return job


def collect(http, result):
    page = PageData(http.text(URL))
    props = page.next_data()["props"]["pageProps"]
    if props.get("jobsFetchingError") is not False:
        raise ValueError("D. E. Shaw reports a job-fetching error or missing health flag")
    rows = require_list(props["regularJobs"], "regularJobs")
    result.pages.append({"url": URL, "returned": len(rows), "reported_total": len(page.card_ids)})
    for row in rows:
        result.add(normalize(row))
    if set(page.card_ids) != {job["id"] for job in result.records.values()} or len(page.card_ids) != len(rows):
        raise ValueError("D. E. Shaw embedded IDs do not match all rendered job cards")
    result.listing_complete = True