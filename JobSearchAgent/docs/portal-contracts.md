# Portal Contracts

Research snapshots: 2026-09-09 and 2026-09-13. Counts change and are not fixed test expectations.
Source access conditions remain separate from technical verification. The
clients support fifteen employers, not arbitrary ATS tenants. Collect full
public city-scoped inventories, then apply software_engineering_v1 eligibility
locally for listings and matching. Amazon also retains its SDE-II restriction.

## Rubrik

GET `https://boards-api.greenhouse.io/v1/boards/rubrik/jobs?content=true`.
Read `jobs[]`, compare unique posting IDs against `meta.total`. One response
contains the board; full JD HTML is in `content`. Preserve `absolute_url`,
`requisition_id`, dates and post ID, not just `internal_job_id`.

Use the posting's `location.name`, preserving `Bangalore` or `Bengaluru` as
supplied. Compare equivalent-city keys for scope and office consistency, while
keeping the verified `Bengaluru` query value in configuration. Office metadata
is additional evidence and can conflict. Office `22927` alone misses
postings: ID `7956920` names Bengaluru but is assigned Pune, and `7486469`
names Bangalore with an India-Remote office. Null office locations are valid.
Country-wide remote postings stay unresolved, not exact-city matches.
The research feed reconciled 137 global IDs and 29 Bengaluru-labelled postings.

Reference: [Greenhouse public Job Board API](https://docs.greenhouse.io/job-board.html#list-jobs).

## Amazon

GET `https://www.amazon.jobs/en/search.json` with repeated query parameters:

```text
normalized_country_code[]=IND
normalized_city_name[]=Bengaluru
normalized_city_name[]=Hyderabad
result_limit=100
offset=0
sort=recent
```

City values are ORed, with country ANDed. `city[]` was ignored, and the
`Bangalore` facet returned zero; use `Bengaluru`. Advance the absolute offset
by returned rows until empty and reconcile unique IDs with `hits`. Never copy
the upstream 20-page cap. Total drift or repeated IDs is incomplete coverage.

`locations[]` can contain JSON-encoded strings. Parse each and require country
`IND` plus one target normalized city in the same location object. A primary
city outside scope does not invalidate a target secondary location.
Descriptions, basic qualifications and preferred qualifications are inline.
URL is the official origin plus `job_path`; keep `id_icims` as identity.
Apply the shared role filter and local SDE-II restriction after source collection.

Research reconciled 1,767 unique two-city records, including 85 shared between
cities. Implementation runs may differ as listings change.

## D. E. Shaw India

GET `https://www.deshawindia.com/careers/work-with-us`. Parse HTML to locate
the `__NEXT_DATA__` script, then JSON to read `props.pageProps.regularJobs`.
Require `jobsFetchingError` to be false. Reconcile embedded IDs with rendered
`data-job-id` cards, including hidden cards after the first four. Show-more is
a visibility toggle, not pagination. Do not rely on a build ID or the tested
Next.js data URL, which returned 404.

Exact office codes: `HYD`, `BLR`, `GGM`. Retain only the first two requested
cities, not the aggregate `india`/`worldwide` selectors. Check wrapper offices
against `data.jobMetadata.jobLocations`. Use `activeOnJobsListing` and keep
`isExploratory` distinct. Ignore `internalJobs` entirely.

`peopleWeAreLookingForHtml` matched published requirements in checked roles,
while plain-text variants could be stale or contain editorial placeholders.
Preserve a warning when variants differ. Job `6989` had four years in plain
text but five in published HTML; never choose the easier requirement. Use
the supplied `jobUrl` slug, not a title-generated slug.

Research reconciled 84 public IDs; 83 were in the two cities, including eight
exploratory listings. Internal records were inactive and were not collected.

## Uber

The current first-party site is `https://jobs.uber.com/en/jobs/`. Its public
application links identify Oracle tenant `iaziqy.fa.ocs.oraclecloud.com` and
site `UberCareers`.

GET `/hcmRestApi/resources/latest/recruitingCEJobRequisitions` on that tenant.
URL-encode each whole query value with a structured encoder:

```text
onlyData=true
expand=requisitionList.workLocation,requisitionList.secondaryLocations
finder=findReqs;siteNumber=UberCareers,facetsList=LOCATIONS;WORK_LOCATIONS,limit=100,sortBy=POSTING_DATES_DESC,offset=0,selectedLocationsFacet=100000031677115;100000031682312
```

The two IDs represent Hyderabad/Telangana/India and Bengaluru/Karnataka/India
respectively. Do not replace them with a guessed literal `location` parameter.
Keep `expand`; omitting it can remove the nested job list.

Use `items[0].requisitionList`, `TotalJobsCount`, `Offset`, and the echoed
`SelectedLocationsFacet`. Outer `count`/`hasMore` describes the search envelope,
not all job pages. Exhaust offsets; validate each primary/secondary location's
country and geography ID. Individual-city, union, invalid-ID and terminal-page
checks passed during research.

List descriptions are empty. GET
`/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails/{Id}?onlyData=true`
for `ExternalDescriptionStr` and public qualification/responsibility fields.
Ignore internal qualifications and recruiter/candidate fields. Preserve source
ID and `https://jobs.uber.com/en/jobs/{Id}/`. Respect posting end timestamps.
All 17 research postings had nonempty matching public detail responses.

## Apple

GET `https://jobs.apple.com/en-in/search?location=bengaluru-BGS&page=1`
and the corresponding `hyderabad-HY1` search. Parse the embedded script beginning
`window.__staticRouterHydrationData = JSON.parse(` by decoding the JSON string
argument and its JSON payload; do not execute the script.

Read `loaderData.search.searchResults`, `totalRecords`, `queryParams`, `page`,
and `filters.locations`. Paginate each city independently to an empty terminal
page, reconcile unique IDs against the original total, then deduplicate the
combined inventory. Match country `iso-country-IND` and `postLocation-BGS` or
`postLocation-HY1` in the same location object. Broader India-wide pipeline jobs
remain unresolved locations, not eligible exact-city candidates.

Follow the rendered public detail link. Read
`loaderData.jobDetails.jobsData` for the full description, minimum/preferred
qualifications and responsibilities. Verify the base positionId and exact
country/cities. Detail locations use `id` where search locations use
`postLocationId`. Preserve exploratory flags and original posting identities.

A location-specific posting such as `200682500-0321` can have a detail ID such
as `PIPE-200682500`. Keep the original search ID and URL suffix; use the verified
positionId only for opportunity grouping. The shared software-role filter gates
listings and matching after collection. Current format/coverage checks belong
to the [test-agents skill](../../.github/skills/test-agents/SKILL.md).

## Stripe

GET `https://stripe.com/careers/search`. Decode `__NEXT_DATA__` and
`props.pageProps.jobIndexData` for the official index, location filters and
`greenhouseId` identities. Resolve country and city from location indices,
keeping Remote in India separate. Follow the supplied slug/ID detail links for
full `listing.contentMarkdown` or published structured description data.

Coverage is the official index, not the Greenhouse board: research found 594
website IDs versus 633 Greenhouse IDs with city-assignment differences. Do not
silently union, intersect or substitute these sources. Validate IDs, location
indices and full city-scoped details; do not execute the embedded scripts.

## Databricks And Arcesium

Use the documented Greenhouse GET jobs contract described for Rubrik, with boards:

- `https://boards-api.greenhouse.io/v1/boards/databricks/jobs?content=true`
- `https://boards-api.greenhouse.io/v1/boards/arcesiumllc/jobs?content=true`

The board token for Arcesium is `arcesiumllc`, not `arcesium`. Both feeds include
full JD `content`; reconcile `meta.total` and unique posting `id` values. Source
locations and office metadata may differ; normalization remains company-specific.
Do not infer country from text appearing incidentally in the JD.
These two collectors union advertised cities with country-verified assigned
offices and retain the evidence/warnings; they do not inherit Rubrik's precedence
rule or expand office descendants into assumed posting locations.

Arcesium can advertise `Bengaluru; Hyderabad` while assigning only a Hyderabad
office. Preserve both advertised cities and obtain country evidence from the
public office hierarchy. The researched India parent was `4022022007`; verify
the returned office rather than treating a bare Hyderabad label as India.

## Atlassian

GET `https://www.atlassian.com/endpoint/careers/listings`. The public UI consumes
a top-level JSON array with `id`, `title`, `locations`, `overview`,
`responsibilities`, `qualifications` and portal metadata. The description sections
are inline; public details are `/company/careers/details/{id}`.

Research found 239 rows but 229 unique IDs. Merge compatible duplicate
representations before adding records; retain raw/unique counts and reject
conflicting identities/content. No separate total or pagination was exposed:
complete means the current public feed, not independently reconciled iCIMS
coverage. Portal references do not justify fetching candidate/application routes.
Country-wide remote eligibility alone is not an exact-city posting.

## Rippling

The official `https://www.rippling.com/careers/open-roles` frontend supplies
Algolia index `careers_en-US_production` and public search configuration.
GET the index on `6fnax3tbef-dsn.algolia.net` with the frontend's current
`X-Algolia-Application-Id` and `X-Algolia-API-Key` headers. Do not pin a changing
bundle hash or search key, persist credentials, or use browse/admin APIs.

Validate `nbHits`, `nbPages`, exhaustive flags and actual raw hits. A public
retrieval cap cannot become successful truncated coverage. Hits may be expanded
by location: `objectID` is not job identity. Merge compatible locations by
`jobId` and fetch one native ATS detail per unique city-scoped UUID.

GET `https://ats.rippling.com/rippling/jobs/{uuid}` and parse
`__NEXT_DATA__.props.pageProps.apiData.jobPost`: `uuid`, `name`, descriptions,
`workLocations`, board/company and `unlistedFromSearch`. Application-form
configuration such as `activeJobApplication` is not a vacancy-status flag.

## Snowflake

Use the officially advertised `https://careers.snowflake.com/us/en/sitemap.xml`
as the posting index and reconcile its unique job routes against
`https://careers.snowflake.com/us/en/search-results?from=0&s=1` before and after
collection. Search offsets overlap even for unique detail-route IDs; do not
union partial pagination passes and claim complete coverage.

Fetch every indexed full detail, including those needed to resolve country/city
scope, and recheck the sitemap's identity set. Decode `phApp.ddo` as JSON, never
executable script. Full text is `jobDetail.data.job.description`, not a teaser.
Percent-encode Unicode sitemap paths while preserving existing percent escapes.
Verify every route identity, external-publication flag and location entry.
Completeness requires stable sitemap identities, agreement with live search
totals, and successful public detail normalization for every indexed posting.

The stable posting identity is the full **jobSeqNo** in the public detail route.
Live validation disproved the initial jobId assumption: the same shorter jobId
can identify different titles, locations and Ashby destinations. Preserve it as
`phenom_job_id` metadata; no existing application rows were rekeyed.
Official Ashby destination UUIDs also remain metadata.
The Ashby feed returned 403 during research and is not a fallback endpoint.
Do not execute source scripts or substitute a browser after denial.

## Salesforce And Adobe

Fixed Workday sites:

| Company | Host | Tenant | Site |
|---|---|---|---|
| Salesforce | `salesforce.wd12.myworkdayjobs.com` | `salesforce` | `External_Career_Site` |
| Adobe | `adobe.wd5.myworkdayjobs.com` | `adobe` | `external_experienced` |

POST `/wday/cxs/{tenant}/{site}/jobs` with a read-only JSON search body containing
`appliedFacets`, `limit`, `offset`, `searchText`. GET details using the returned
`externalPath` beneath the same CXS site. Validate IDs and use
`jobPostingInfo.jobDescription`, `jobReqId`, primary/additional locations and
public posting flags. The summary `5 Locations` is not enough to reject a job
before detail resolution. City keywords alone cannot establish complete scope.

Both sites returned nonempty later pages with `total: 0`. Retain the first-page
total, advance by actual returned rows, detect duplicate pages and reconcile
against a fresh first page. Stop exactly at the initial-total boundary:
`offset=total` restarts page zero rather than returning an empty terminal page.
Do not terminate merely because a later total is zero. A genuinely empty global
board is checked with a fresh zero-total/zero-row response.

Salesforce coverage is **only its main external board**. Separate Slack, Tableau,
Heroku, MuleSoft, research and early-career boards are not collected. Its official
static reports can disagree with live Workday details in location and description;
do not silently substitute them. Adobe's Workday inventory exceeded its Phenom
inventory in research; coverage is the Workday site, not proven source parity.
Current titles control eligibility: an old Software Engineer URL slug cannot
override an Adobe Computer Scientist title.

## Microsoft

Use the current Eightfold public layer at `https://apply.careers.microsoft.com`,
domain `microsoft.com`, not historical Microsoft search APIs.
GET `/api/pcsx/search` returns `data.count`, `data.positions`, applied filters and
offset-based pages. Full JD text is returned by
`/api/pcsx/position_details?position_id={id}&domain=microsoft.com&hl=en`.

Use a complete source inventory and inspect all standardized country/city
locations. The UI's default proximity search includes remote jobs and a broad
radius; a narrow-radius query is not by itself proof of full city coverage.
The client enumerates the unfiltered global inventory with empty applied filters,
reconciles every offset and rechecks the first page. Requests are sequential and
paced; the source's observed ten-row pages can make this scan substantial.
Rate-limit failures retain diagnostics and incomplete coverage, not an assumed
successful city subset. Explicit city associations are not excluded solely
because a role is remote/hybrid.

Keep Eightfold `id` as posting identity and retain `atsJobId`/`displayJobId`
separately. Worksite details can describe hybrid attendance even when an enum says
`onsite`; preserve the original evidence rather than inferring days in office.

## Intuit

Use `https://jobs.intuit.com/location/india-jobs/27595/1269750/2` and supplied
pagination links. Public TalentBrew location pages contain advertised totals,
current/total pages and ordinary job links. Slugs may change between pages;
location facet type `4` is not a page number. Reconcile current inventory and
use the public sitemap only as supplementary evidence.

Full details at `/job/{city}/{title}/27595/{id}` contain JobPosting JSON-LD.
Validate the canonical TalentBrew ID and all `jobLocation` addresses, preserving
structured Bangalore versus displayed Bengaluru. Dates may not be zero-padded.
The JSON-LD requisition identifier is metadata, not the TalentBrew posting key.

Do not request `/search-jobs/` AJAX/search routes or Avature application URLs.
A remote facet or URL city alone is insufficient location evidence; no known end
date is not a guarantee that hiring remains active.

## Posting Identities

| Company | `id` / applied `jobid` |
|---|---|
| Stripe | Official `greenhouseId` |
| Databricks, Arcesium | Greenhouse posting `id` |
| Atlassian | Public-feed `id` |
| Rippling | Native job UUID / search `jobId`, not location-expanded `objectID` |
| Snowflake | Full detail-route `jobSeqNo`, not reused Phenom `jobId` or Ashby UUID |
| Salesforce, Adobe | Verified Workday `jobReqId` |
| Microsoft | Eightfold position `id`, not displayed ATS requisition |
| Intuit | Canonical TalentBrew posting ID, not Avature requisition |

Preserve the existing five companies' identities above. Alternate identifiers
do not silently rekey the applied tracker. Identical titles do not prove shared
opportunity identity.

## Transport And Deferred Sources

Existing GET behavior remains available. Custom headers are restricted to
Rippling's public Algolia search origin and cannot cross origins. JSON POST is
limited to the two fixed Workday search endpoints and rejects redirects.
All sources retain bounded requests, explicit errors and no denial bypass.
No applications, browser fallback, account sessions or private credentials.

NVIDIA is deferred: its current official `https://jobs.nvidia.com/careers`
destination returned 403 and its underlying current ATS contract was not
verified. No historical tenant is guessed or registered.

## Integration

All fifteen collectors use the fixed dispatcher, shared software-role filtering,
private atomic temporary output and receipt validation. Match/tracker behavior is
shared; only source normalization and verified identity contracts differ.

Resume fit, AI prioritization within eligible roles and top-three selection are
governed by [MATCHING_POLICY.md](../MATCHING_POLICY.md), not portal contracts.
Cross-company seniority inference remains unsupported. Permissions for the added
sources are managed manually by the user; these technical contracts do not
constitute legal approval.