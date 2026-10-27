# ictjobs.ch — Phase 0 (2026-10-19)

| Item | Finding |
|---|---|
| Access | WordPress. Ads are posts: `GET https://ictjobs.ch/wp-json/wp/v2/posts?ctx_prof_group=3159,3672&per_page=100&page=<n>` |
| Pagination | `X-WP-Total`, `X-WP-TotalPages` headers. ~180 posts in total |
| Detail | Post `link` page carries schema.org `JobPosting` JSON-LD: description, `hiringOrganization`, `jobLocation.address`, `employmentType`, `validThrough` (`content.rendered` is empty in the API) |
| JavaScript needed | No (httpx) |
| Stable ID | Post `id` (also `JobPosting.identifier.value`) |
| Taxonomies | `ctx_prof_group`: 3159 Software-Entwicklung/Data/Web/UX, 3672 AI/ML/Robotik, 3185 Netzwerk/Cloud, 3369 Security, 3216 Architektur/Consulting, … `ctx_work_location`: 3251 = Germany/Austria (border check applies) |
| Rate | ~50 detail pages per run at 2 s |
