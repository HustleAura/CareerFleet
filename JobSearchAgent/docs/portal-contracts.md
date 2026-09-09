# Portal Contracts

Research snapshot: 2026-09-09. Counts change and are not fixed test expectations.
Source access conditions remain separate from technical verification. The
clients support these five employers, not arbitrary ATS tenants.

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
Apply the local SDE-II filter only after this source collection.

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

Live use is disabled unless approved access is recorded. The implemented format
is paginated HTML with embedded data, not a separately documented JSON API.

GET `https://jobs.apple.com/en-in/search?location=bengaluru-BGS&page=1`
and the corresponding `hyderabad-HY1` search. Extract the script beginning
`window.__staticRouterHydrationData = JSON.parse(`. Decode its JSON string
argument and then the resulting JSON. Never execute or eval the script.

Read `loaderData.search.searchResults`, `totalRecords`, `queryParams`, `page`,
and `filters.locations`. Paginate each city independently; after the last page
Apple returns both an empty list and total zero. Reconcile each city's unique
IDs against its original total, then deduplicate the combined inventory.

Match country `iso-country-IND` and `postLocation-BGS`/`postLocation-HY1` in
the same `locations[]` object. City text may be empty. Both city searches also
return country-wide pipeline jobs; put those into unresolved locations.
Research returned 93 Bengaluru-search and 70 Hyderabad-search records. Their
union contained 154 IDs, of which 145 explicitly matched target cities and nine
were country-wide.

Follow the rendered public detail href rather than guessing from a title.
Decode `loaderData.jobDetails.jobsData` for full descriptions and qualifications.
Compare base `positionId` plus exact country/city. A location-specific search
ID such as `200682500-0321` may have detail ID `PIPE-200682500`; never replace
the search identity or drop the original URL suffix. Detail location objects
use `id` where search objects use `postLocationId`. Full description retrieval
was spot-checked during research. Ongoing checks belong to the job-search path
in the [test-agents skill](../../.github/skills/test-agents/SKILL.md); blocked
or unexercised paths must be reported, not claimed as tested.

## Phases

1. Rubrik/Amazon direct JSON collection and Amazon-only title filtering.
2. D. E. Shaw/Apple embedded-JSON parsing and source-specific validation.
3. Uber search-plus-detail collection.
4. Fixed dispatcher, private atomic outputs, receipt validation and VS Code agent.

Cross-company seniority inference, AI prioritization, resume fit and top-three
selection are deferred. Do not treat this roadmap as authorization for those
features or for a source's recurring automated access.