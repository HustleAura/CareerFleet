import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser

from roles import ROLE_POLICY, classify_title, validate_role_policy


TARGET_CITIES = ("Hyderabad", "Bengaluru")
SUPPORTED_COMPANIES = ("amazon", "rubrik", "uber", "deshaw_india", "apple")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class FetchError(ValueError):
    pass


def public_url(url, hosts):
    if not isinstance(url, str) or any(ord(character) <= 32 or ord(character) == 127 for character in url):
        raise FetchError("URL contains whitespace or control characters")
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in hosts
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise FetchError("URL is outside this company's approved HTTPS hosts")
    return url


class RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts):
        self.hosts = hosts

    def redirect_request(self, request, response, code, message, headers, new_url):
        public_url(new_url, self.hosts)
        return super().redirect_request(request, response, code, message, headers, new_url)


class HttpClient:
    def __init__(self, hosts, timeout=30, attempts=3, max_bytes=20_000_000):
        self.hosts = set(hosts)
        self.timeout = timeout
        self.attempts = attempts
        self.max_bytes = max_bytes
        self.opener = urllib.request.build_opener(RestrictedRedirect(self.hosts))

    def text(self, url):
        public_url(url, self.hosts)
        for attempt in range(self.attempts):
            request = urllib.request.Request(url, headers={
                "User-Agent": "CareerFleetJobSearch/1.0 (personal job discovery)",
                "Accept": "application/json, text/html;q=0.9",
            })
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    body = response.read(self.max_bytes + 1)
                    if len(body) > self.max_bytes:
                        raise FetchError("Response exceeded the size limit; collection is incomplete")
                    charset = response.headers.get_content_charset() or "utf-8"
                    return body.decode(charset)
            except urllib.error.HTTPError as error:
                if error.code in (401, 403):
                    raise FetchError(f"HTTP {error.code}: access blocked; no bypass attempted") from error
                if error.code not in (429, 500, 502, 503, 504) or attempt + 1 == self.attempts:
                    raise FetchError(f"HTTP {error.code}") from error
                delay = 2 ** attempt
                retry_after = error.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        try:
                            retry_date = parsedate_to_datetime(retry_after)
                            delay = max(delay, (retry_date - datetime.now(timezone.utc)).total_seconds())
                        except (ValueError, TypeError):
                            raise FetchError("Unrecognized Retry-After; retry on a later run") from error
                if delay > 30:
                    raise FetchError("Rate limited; Retry-After exceeds this run's retry budget") from error
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                if attempt + 1 == self.attempts:
                    raise FetchError(f"Network request failed: {type(error).__name__}") from error
                time.sleep(2 ** attempt)

    def json(self, url):
        try:
            return json.loads(self.text(url))
        except json.JSONDecodeError as error:
            raise FetchError("Expected JSON, received an invalid response or challenge page") from error


class PageData(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.scripts = []
        self.links = []
        self.card_ids = []
        self.current = None
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "script":
            self.current = {"id": attributes.get("id"), "parts": []}
        if tag == "a" and attributes.get("href"):
            self.links.append(attributes["href"])
        if attributes.get("data-job-id"):
            self.card_ids.append(attributes["data-job-id"])

    def handle_endtag(self, tag):
        if tag == "script" and self.current is not None:
            self.scripts.append(self.current)
            self.current = None

    def handle_data(self, data):
        if self.current is not None:
            self.current["parts"].append(data)

    def next_data(self):
        matches = [script for script in self.scripts if script["id"] == "__NEXT_DATA__"]
        if len(matches) != 1:
            raise FetchError("Expected exactly one __NEXT_DATA__ script")
        return json.loads("".join(matches[0]["parts"]))

    def apple_data(self):
        prefix = "window.__staticRouterHydrationData = JSON.parse("
        matches = ["".join(script["parts"]).strip() for script in self.scripts
                   if "".join(script["parts"]).strip().startswith(prefix)]
        if len(matches) != 1:
            raise FetchError("Apple hydration-data signature is missing or changed")
        argument, unused = json.JSONDecoder().raw_decode(matches[0][len(prefix):])
        if not isinstance(argument, str):
            raise FetchError("Apple hydration argument is not a JSON string")
        return json.loads(argument)


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag in ("p", "div", "li", "br", "h1", "h2", "h3", "ul", "ol"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        if tag in ("p", "div", "li", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def clean_text(value):
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(clean_text(item) for item in value)
    if not isinstance(value, str):
        raise ValueError("Description must be text or a list of text")
    for unused in range(3):
        decoded = unescape(value)
        if decoded == value:
            break
        value = decoded
    parser = TextExtractor()
    parser.feed(value)
    return "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())


def city_name(value):
    normalized = (value or "").strip().casefold()
    return {"hyderabad": "Hyderabad", "bengaluru": "Bengaluru", "bangalore": "Bangalore"}.get(normalized)


def city_keys(values):
    names = {city_name(value) for value in values}
    return {"Bengaluru" if name == "Bangalore" else name for name in names if name}


def text_cities(value):
    return sorted({city_name(match.group()) for match in
                   re.finditer(r"\b(?:hyderabad|bengaluru|bangalore)\b", value or "", re.I)})


def require_list(value, field):
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array; source schema may have changed")
    return value


def require_total(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Missing or invalid source total")
    return value


def posting(company, identity, title, url, locations, cities, description, **extra):
    if identity is None or not str(identity).strip() or not isinstance(title, str) or not title.strip():
        raise ValueError("Posting requires a stable ID and title")
    return dict(company=company, id=str(identity), key=f"{company}:{identity}", title=title.strip(),
                url=url, locations=locations, cities=sorted(set(cities)), description=description,
                public=True, exploratory=False, expires_at=None, warnings=[], **extra)


class ScanResult:
    def __init__(self, company, cities=TARGET_CITIES, role_policy=ROLE_POLICY):
        if company not in SUPPORTED_COMPANIES:
            raise ValueError("Unknown collection company")
        self.company = company
        self.role_policy = validate_role_policy(role_policy)
        self.cities = tuple(cities)
        self.started_at = utc_now()
        self.records = {}
        self.errors = []
        self.warnings = []
        self.pages = []
        self.listing_complete = False
        self.access_status = "enabled"

    def add(self, job):
        if job["company"] != self.company:
            raise ValueError("Posting company differs from collection")
        if job["key"] in self.records:
            raise ValueError(f"Duplicate source posting ID: {job['id']}")
        job["fetched_at"] = utc_now()
        job["location_status"] = "in_scope" if city_keys(job["cities"]) & city_keys(self.cities) else job.get("location_status", "outside")
        job.update(classify_title(self.company, job["title"], self.role_policy))
        expiry = job.get("expires_at")
        if expiry:
            try:
                parsed = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("Expiry timezone is unspecified")
                job["expired"] = parsed <= datetime.fromisoformat(self.started_at)
            except (ValueError, AttributeError):
                job["expired"] = None
                job["warnings"].append("Unparseable expiry; active state needs review")
        else:
            job["expired"] = False
        self.records[job["key"]] = job

    def inventory(self):
        return [job for job in self.records.values() if job["public"] and job["location_status"] == "in_scope"]

    def unresolved(self):
        return [job for job in self.records.values() if job["public"] and job["location_status"] == "unresolved"]

    def selected(self):
        return [job for job in self.inventory() if job["expired"] is False
                and job["title_filter"] == "matched"]

    def receipt(self):
        inventory = self.inventory()
        missing = sum(not job["description"] for job in inventory)
        if self.access_status != "enabled":
            status = self.access_status
        elif self.listing_complete and not self.errors and not missing:
            status = "complete"
        else:
            status = "partial" if self.records else "failed"
        return {"company": self.company, "status": status, "started_at": self.started_at,
                "role_filter_policy": self.role_policy,
                "finished_at": utc_now(), "requested_cities": list(self.cities), "country": "India",
                "inventory_complete": self.listing_complete, "details_complete": self.listing_complete and missing == 0,
                "source_unique_count": len(self.records), "in_scope_count": len(inventory),
                "unresolved_location_count": len(self.unresolved()),
                "outside_count": sum(job["public"] and job["location_status"] == "outside" for job in self.records.values()),
                "nonpublic_count": sum(not job["public"] for job in self.records.values()),
                "selected_count": len(self.selected()), "missing_description_count": missing,
                "expired_count": sum(job["expired"] is True for job in inventory),
                "exploratory_count": sum(job["exploratory"] for job in inventory),
                "title_excluded_count": sum(job["title_filter"] == "excluded" for job in inventory),
                "title_unresolved_count": sum(job["title_filter"] == "unresolved" for job in inventory),
                "role_excluded_count": sum(job["role_filter"] == "excluded" for job in inventory),
                "role_unresolved_count": sum(job["role_filter"] == "unresolved" for job in inventory),
                "pages": self.pages, "errors": self.errors, "warnings": self.warnings}