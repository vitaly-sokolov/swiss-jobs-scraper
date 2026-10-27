# foorilla.com — Phase 0 (2026-10-19)

| Item | Finding |
|---|---|
| Access | Official API `https://foorilla.com/api/v1/` (docs `/api/v1/docs`, schema `/api/v1/schema.json`, `/api/llms.txt`) |
| Auth | `Api-Key` header on every endpoint except the root. **Requires a PRO+ subscription ($64/month)**. Without a key every call returns 401 |
| Jobs | `GET /api/v1/hiring/job/?country=<id>&page=<n>&page_size=<1..1000>`; filters: topic, tag, region, country, title, location, company, experience_level, language, has_remote, work_mode, company_remote, company_agency, published_after/before |
| Envelope | `{"results": [...], "count", "pages", "page", "page_size"}` |
| Rate limit | 5 req/s, 600 req/min per account |
| License | Data CC BY-SA 4.0 — attribution required (`/api/list/attribution/`) |
| Salary | `salary_min/max` (published) and `*_est` (estimated). Only published values are used (D11) |
| HTML fallback | Site is htmx with session-scoped filters over ~228k global jobs; not implemented. The API is the documented access path |
| Status | Adapter implemented against the schema, **disabled** in sources.yaml until a key is configured. `work_mode` codes and the country lookup must be verified with a live key |
| Open | `company_agency=false` can implement recruitment-agency exclusion (Q3) |
