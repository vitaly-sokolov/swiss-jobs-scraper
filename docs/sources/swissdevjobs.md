# swissdevjobs.ch — Phase 0 (2026-10-19)

| Item | Finding |
|---|---|
| Access | Public JSON feed `GET https://swissdevjobs.ch/api/jobsLight` (no auth) |
| Pagination | None. One response with every live job (~220 on 2026-10-19, ~290 KB) |
| JavaScript needed | No (httpx) |
| Stable ID | `_id` (Mongo ObjectId). Public URL: `/jobs/<jobUrl>` |
| Rate | 1 request per run |
| Fields used | `name`, `company`, `actualCity`, `postalCode`, `activeFrom`, `annualSalaryFrom/To`, `contractRate*`, `jobType`, `expLevel`, `workplace` (`hybrid`/`office`/`remote`), `technologies`, `filterTags`, `metaCategory`, `language`, `isPaused` |
| Category filter | `metaCategory` ∈ softwareeng, mlaidata, architectconsulting, clouddevops (sources.yaml) |
| Description | Not in the light feed. No detail JSON endpoint found (the site is a client-rendered SPA). Not needed: title + technologies + category are enough for the filter |
| Salary | Always published (site requirement) → `salary_text` "CHF a - b per year" |
| Language | No description, so `language` falls back to the required-language field |
