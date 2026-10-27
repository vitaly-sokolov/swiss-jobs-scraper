# Swiss Tech Jobs Scraper — Technical Design

Status: v0.5 (implemented) · Owner: Vitaly · Last updated: 2026-10-19

## Changes since v0.4

- **Phase 0 done** (`docs/sources/*.md`). Every source has JSON or server-rendered data,
  so no adapter uses Selenium. Selenium and the egress container are still provided (§5).
- **Foorilla**: the API needs a paid PRO+ key. The adapter is built but disabled until
  `api_keys.foorilla` is set.
- **Data model additions** (§7): `jobs.country`, `jobs.xref`, `jobs.pending_event`,
  `jobs.details_fetched_at`, `scrape_runs.item_errors`, `notifications.error`.
- **Detail pages fetched only when needed** (§8): only for new, reopened or never-detailed
  listings, so jobs.ch fits inside the 15 min per-source timeout.
- **Duplicates** (§8.7) point at the *root* row and also match on `xref` (the JobCloud UUID
  shared by jobs.ch and ictcareer.ch).
- **Advisory lock** is held on its own connection for the whole run (§8).
- **Retention** runs daily as `jobs-cleanup` (§15, D18).
- **Fixes**: removed `admin_chat_id` (D15) and backups from Phase 4 (D17). Schedule uses
  Europe/Zurich (same offset as Europe/Paris). An empty result marks the run `failed`, so
  a broken source can't close every job.

## 0. Decisions log

| # | Topic | Decision |
|---|---|---|
| D1 | robots.txt | Not checked. |
| D2 | Terms of use | Not used as a gate. Sources are scraped regardless of their terms. |
| D3 | Selenium egress | Through one configured HTTP proxy. Credentials in config. |
| D4 | Persistence | SQLAlchemy 2.0 ORM + Alembic. No hand-written SQL in app code. |
| D5 | Geography | Swiss-based roles, remote roles open to Switzerland, and border-region jobs. |
| D6 | Languages | German, French and English postings, all kept. |
| D7 | Telegram notifications | Per-job messages only. No digest. |
| D8 | Duplicates across sources | One row per source. Cross-source duplicates are flagged, not merged. |
| D9 | Reopened jobs | Notify again when a job returns after being closed. |
| D10 | Hosting | VPS, Docker Compose. |
| D11 | Salary | Store and show published values only. |
| D12 | Telegram token | Provided; stored in config. |
| D13 | Sources | swissdevjobs.ch, jobs.ch, jobup.ch, ictjobs.ch, ictcareer.ch, foorilla.com. |
| D14 | Proxy type | HTTP (not SOCKS). Host and port still pending. |
| D15 | Telegram destination | One private chat. Alerts go to the same chat. |
| D16 | Tech job filter | Backend development and AI engineer roles. |
| D17 | Backups | None in v1. |
| D18 | Inactive job retention | 365 days, then deleted. |

## 1. Goal and daily flow

Collect open backend and AI jobs in Switzerland (plus remote roles open to Switzerland and
border-region roles) from the configured sites. Store them in PostgreSQL and send one
Telegram message for each new or reopened job.

07:00 Europe/Zurich, `jobs-scrape --all && jobs-notify; jobs-cleanup`:
1. Each enabled adapter yields `RawListing`s (httpx; Selenium is available).
2. The pipeline filters (tech + geography), fetches details where needed, normalizes and upserts in batches.
3. Closure runs after `ok` runs; ⚠️ alerts go out for failed sources and partial streaks.
4. The notifier sends one message per pending job.
5. Cleanup applies retention.

## 3. Sources (Phase 0 results)

| Source | Method | Listing | Details | Volume (2026-10-19) |
|---|---|---|---|---|
| swissdevjobs | API | `/api/jobsLight` (all jobs, one call) | none needed | ~220 total |
| jobs_ch | API | `/api/v1/public/search?category-ids[]=106`, 20/page | `/api/v1/public/search/job/<uuid>` | 1,409 IT |
| jobup | API | same API, category 702 | same | 693 IT |
| ictcareer | HTTP | `/jobs?tag=…` → `__NEXT_DATA__`, 10/page | `/job/<id>` → `__NEXT_DATA__` | ~80 |
| ictjobs | HTTP | WordPress REST `/wp-json/wp/v2/posts` | JSON-LD `JobPosting` on post page | ~50 relevant |
| foorilla | API (key) | `/api/v1/hiring/job/?country=<CH>` | in list | — (disabled) |

## 5. Proxy and Selenium

- httpx uses `proxy.url` with credentials (`ProxyConfig.httpx_proxy()`).
- Chrome uses `proxy.browser_url` (`http://egress:3128`). The `egress` container (tinyproxy,
  compose profile `selenium`) adds the upstream credentials from `config/egress.env`.
- Startup logs show the egress mode as `direct` or `proxy host:port`, never credentials.
- Chromium and chromedriver come from Debian packages in the image (`JOBS_CHROME_BIN`, `JOBS_CHROMEDRIVER`).

## 6. Adapters and normalization

`RawListing`, `FetchContext` and `SourceAdapter` follow v0.4. Additions:
- `enrich(ctx, listing)`: optional per-adapter detail fetch, called by the pipeline.
- `ctx.item_error(...)`: counts bad listings. Any item error makes the run `partial`.

Tech filter (`config/tech_keywords.yaml`), in order: company deny → title deny (unless an
override such as "fullstack" matches) → title allow (backend / AI role) → generic role
title plus at least 3 backend/AI terms in the description and source tags.

Geography (D5): keep when the country is unknown, CH or LI, a border town (`locations.yaml`), or remote.

Normalized fields follow §6.3 of v0.4, plus:
- `country`
- `remote`: only explicit full-remote phrases in the body count as remote; a home-office mention counts as hybrid.
- `dedupe_key = sha256(company without legal suffixes | title without gender/percent markers | canton or location text)`

## 7. Data model

See `src/jobscraper/db/models.py`. The baseline migration was autogenerated:
`migrations/versions/20261019_*_baseline.py`.

## 8. Persistence logic

As in v0.4, with these refinements:
- Listings are filtered *before* the database lookup. Rejected listings are not "seen", so
  a job that stops matching the filter closes after 3 runs.
- Details are fetched when the row is new, closed (about to reopen) or has `details_fetched_at IS NULL`.
  A later preview never overwrites a fetched full description.
- New → `pending_event='new'`. Reopened → `pending_event='reopened'`, `notified_at=NULL`.
- Duplicate flag: earliest row from another source with the same `dedupe_key` or `xref`,
  resolved to its root.
- Run status: `failed` on a source exception, timeout, or zero listings; `partial` when
  any item failed; otherwise `ok`. Closure only after `ok`.
- If a fetch fails mid-run, the unfinished batch is still stored (without detail fetches).
- Timeouts: a per-source deadline (15 min) and a global one (60 min) are checked before every HTTP request.

## 9. Notifications

As in v0.4. Selects `notified_at IS NULL AND is_active AND pending_event IS NOT NULL`.
A new job that closes before it was notified is never sent. Messages escape `& < >`.
httpx request logging is muted because the Telegram URL contains the bot token.

## 10. Deployment

`docker-compose.yml`: `postgres` (internal network only), `scheduler` (migrations, then
supercronic), `egress` (profile `selenium`). Config is mounted read-only; the container
runs as uid 10001. No backups (D17).

## 16. Open questions

1. **Proxy endpoint (Q1)**: host and port are still needed. Until then `proxy.enabled: false`.
2. **Recruitment agencies (Q3)**: not excluded yet. Hooks: `company_deny` in `tech_keywords.yaml`;
   foorilla `exclude_agencies`.
3. **Foorilla API key**: PRO+ subscription needed to enable the source.

## 17. Risks

As in v0.4. One more: the JobCloud and ictcareer endpoints are internal frontend APIs, not
documented products, so they can change without notice. Fixture tests and run alerts
detect this.
