# Swiss Tech Jobs Scraper

Scraper for tech jobs in Switzerland. Sources: SwissDevJobs,
jobs.ch, jobup.ch, ictjobs.ch, ictcareer.ch and foorilla. Jobs are stored in PostgreSQL and
each new or reopened job is sent to a private Telegram chat.

Design: [`docs/design.md`](docs/design.md) · Source findings: [`docs/sources/`](docs/sources/)

## Commands

| Command                                  | What it does                                                                          |
| ---------------------------------------- | ------------------------------------------------------------------------------------- |
| `jobs-scrape --all` / `--source jobs_ch` | Fetch, filter, normalize, upsert; close jobs after 3 missed `ok` runs; send ⚠️ alerts |
| `jobs-notify [--limit N]`                | One Telegram message per pending job (new / reopened)                                 |
| `jobs-cleanup`                           | Clear `raw` after 90 days; delete jobs inactive for 365 days                          |
| `jobs-migrate`                           | `alembic upgrade head`                                                                |

All four take a PostgreSQL advisory lock, so overlapping runs exit with code 2.

## Configuration

- `config/config.yaml` (gitignored; copy from `config.example.yaml`) holds the database URL,
  proxy, Telegram token and chat ID, API keys, timeouts and retention.
- `config/sources.yaml` holds per-source enable flags, throttle and category IDs.
- `config/tech_keywords.yaml` is the filter, `tech_tags.yaml` the tag vocabulary,
  `locations.yaml` the canton and border-town vocabulary.
- Env overrides: `JOBS_<FIELD>`, nested with `__`, e.g. `JOBS_TELEGRAM__CHAT_ID=123`.

## Local development

```sh
uv venv --python 3.12 && uv pip install -e '.[dev]'
pytest                       # offline tests; DB tests need Docker or TEST_DATABASE_URL
TEST_DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/jobs_test pytest
pytest -m live -s            # smoke test against the real sites (network)
```

### Runbook

- **Run now:** `docker compose exec scheduler sh -c 'jobs-scrape --all && jobs-notify'`
- **One source:** `docker compose exec scheduler jobs-scrape --source ictjobs`
- **Recent runs:** `docker compose exec postgres psql -U jobs -c "select source,status,fetched,rejected,inserted,updated,reopened,closed,item_errors,error from scrape_runs order by id desc limit 12"`
- **⚠️ `<source> failed`:** check `scrape_runs.error`, then `pytest -m live -k <source>`. If the
  site changed, update the adapter and its fixture in `tests/fixtures/`.
- **Filter tuning:** edit `config/tech_keywords.yaml` (the config is mounted, so no rebuild).
  Rejected listings are counted in `scrape_runs.rejected`.
- **Enable the proxy (Q1):** set `proxy.enabled: true` and `proxy.url`. For Selenium, also create
  `config/egress.env` (`UPSTREAM_HOST`, `UPSTREAM_PORT`, `UPSTREAM_USER`, `UPSTREAM_PASSWORD`)
  and run `docker compose --profile selenium up -d`.
- **Enable foorilla:** set `api_keys.foorilla` (PRO+), set `enabled: true` in `sources.yaml`,
  run `jobs-scrape --source foorilla` once, and check the `work_mode` codes against `/api/v1/core/metadata/`.
