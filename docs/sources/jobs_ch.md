# jobs.ch — Phase 0 (2026-10-19)

| Item | Finding |
|---|---|
| Access | JobCloud public search API used by the site frontend (no auth) |
| List | `GET https://www.jobs.ch/api/v1/public/search?category-ids[]=106&rows=20&page=<n>` |
| Pagination | `rows` max **20** (422 above). `num_pages`, `total_hits` in the response. IT category 106: 1,409 jobs / 71 pages on 2026-10-19; the last page works |
| Detail | `GET https://www.jobs.ch/api/v1/public/search/job/<uuid>` → `template_text` (ad HTML), `zipcode`, `application_url`, `skills` |
| JavaScript needed | No (httpx) |
| Stable ID | `job_id` (UUID). Same UUID appears on ictcareer.ch as `jcJobId` → used as `xref` |
| Categories | `/api/v1/public/meta/categories`: 106 information-technology-telecom (children 169–181) |
| Employment types | `/api/v1/public/meta/employment-types`: 1 Temporär, 2 Freelance, 3 Praktikum, 4 Nebenerwerb, 5 Festanstellung, 6 Lehrstelle |
| Salary | No salary field in list or detail on the sampled ads → normally NULL (D11) |
| Rate | 1 s/request worked without errors. Listing ≈ 71 requests; detail fetched only for new/reopened matching jobs |
| Personal data | Detail has `contact_person`/`contacts`; **not stored** (§15) |
