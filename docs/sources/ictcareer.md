# ictcareer.ch — Phase 0 (2026-10-19)

| Item | Finding |
|---|---|
| Access | Next.js site, server-rendered. Job data in `<script id="__NEXT_DATA__">` → `props.pageProps.initialState.public.jobs` |
| List | `GET https://www.ictcareer.ch/jobs?tag=538&tag=533&tag=540&page=<n>` (repeat `tag`; comma-joined fails) |
| Pagination | 10 per page; `resultCount`, `pageSize`, `page`. Pages past the end return an empty list |
| Detail | `GET https://www.ictcareer.ch/job/<jobId>` → `…jobs.job` with `description` (HTML), `workload`, `tags` (employment type), `applyUrl` |
| API | `https://api.ictcareer.ch` exists (runtimeConfig) but list paths are not public; HTML parsing is simpler |
| JavaScript needed | No (httpx) |
| Stable ID | `jobId` (numeric). `jcJobId` = jobs.ch UUID of the same ad → `xref` for D8 |
| Tags | 532 Beratung, 533 Datenbanken, 534 ERP/BI, 535 IT-Mgmt, 536 Netzwerk/Security, 537 Support, 538 Software Engineering, 539 Systemtechnik, 540 Webdesign/-programmierung |
| Volume | ~80 jobs for tags 538+533+540 |
