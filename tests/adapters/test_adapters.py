"""Fixture-based parser tests (no network). Fixtures are trimmed real responses
captured during Phase 0 (2026-10-19), except foorilla (synthetic, from its schema)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from pydantic import SecretStr

from jobscraper.adapters.foorilla import FoorillaAdapter, MissingApiKey
from jobscraper.adapters.ictcareer import IctCareerAdapter
from jobscraper.adapters.ictjobs import IctJobsAdapter
from jobscraper.adapters.jobcloud import JobsChAdapter, JobupAdapter
from jobscraper.adapters.swissdevjobs import SwissDevJobsAdapter
from tests.conftest import fixture_text


@respx.mock
def test_swissdevjobs(make_ctx):
    respx.get("https://swissdevjobs.ch/api/jobsLight").respond(text=fixture_text("swissdevjobs_jobsLight.json"))
    listings = list(SwissDevJobsAdapter().fetch(make_ctx({"meta_categories": []})))
    assert len(listings) == 6
    first = listings[0]
    assert first.source_job_id == "69f4814f510fe4e0e6cf7cfb"
    assert first.url == "https://swissdevjobs.ch/jobs/SCAIT-Senior-Backend--AI-Engineer-mwd---100"
    assert first.title == "Senior Backend & AI Engineer (m/w/d) - 100%"
    assert first.company == "SCAIT"
    assert first.location_text == "6343 Rotkreuz"
    assert first.salary_text == "CHF 110000 - 130000 per year"
    assert first.extra["workplace"] == "hybrid"
    assert "FastAPI" in first.extra["technologies"]


@respx.mock
def test_swissdevjobs_category_filter(make_ctx):
    respx.get("https://swissdevjobs.ch/api/jobsLight").respond(text=fixture_text("swissdevjobs_jobsLight.json"))
    items = json.loads(fixture_text("swissdevjobs_jobsLight.json"))
    expected = sum(1 for i in items if i["metaCategory"] == "softwareeng")
    listings = list(SwissDevJobsAdapter().fetch(make_ctx({"meta_categories": ["softwareeng"]})))
    assert len(listings) == expected


@respx.mock
def test_swissdevjobs_bad_item_is_skipped(make_ctx):
    items = json.loads(fixture_text("swissdevjobs_jobsLight.json"))[:2]
    del items[0]["name"]
    respx.get("https://swissdevjobs.ch/api/jobsLight").respond(json=items)
    ctx = make_ctx({"meta_categories": []})
    listings = list(SwissDevJobsAdapter().fetch(ctx))
    assert len(listings) == 1
    assert ctx.item_errors == 1


@respx.mock
def test_jobs_ch_list_and_enrich(make_ctx):
    route = respx.get("https://www.jobs.ch/api/v1/public/search").respond(text=fixture_text("jobs_ch_search.json"))
    detail = json.loads(fixture_text("jobs_ch_detail.json"))
    respx.get(f"https://www.jobs.ch/api/v1/public/search/job/{detail['job_id']}").respond(json=detail)

    ctx = make_ctx()
    listings = list(JobsChAdapter().fetch(ctx))
    assert len(listings) == 2
    assert route.calls[0].request.url.params.get_list("category-ids[]") == ["106"]
    assert route.calls[0].request.url.params["rows"] == "20"

    job = next(listing for listing in listings if listing.source_job_id == detail["job_id"])
    assert job.title == "Data Platform Engineer"
    assert job.company == "Schweizerische Nationalbank"
    assert job.url.startswith("https://www.jobs.ch/en/vacancies/detail/")
    assert job.extra["xref"] == job.source_job_id
    assert job.extra["enriched"] is False
    assert "Festanstellung" in job.employment_text

    enriched = JobsChAdapter().enrich(ctx, job)
    assert enriched.extra["enriched"] is True
    assert enriched.location_text == "8022 Zürich"
    assert "Data Platform Engineer" in enriched.description_html


@respx.mock
def test_jobs_ch_paginates(make_ctx):
    page = json.loads(fixture_text("jobs_ch_search.json"))
    page["num_pages"] = 3
    route = respx.get("https://www.jobs.ch/api/v1/public/search").respond(json=page)
    listings = list(JobsChAdapter().fetch(make_ctx()))
    assert route.call_count == 3
    assert len(listings) == 6


@respx.mock
def test_jobup_uses_its_own_category(make_ctx):
    route = respx.get("https://www.jobup.ch/api/v1/public/search").respond(text=fixture_text("jobup_search.json"))
    listings = list(JobupAdapter().fetch(make_ctx()))
    assert len(listings) == 3
    assert route.calls[0].request.url.params.get_list("category-ids[]") == ["702"]
    assert all(listing.url.startswith("https://www.jobup.ch/fr/") for listing in listings)


@respx.mock
def test_ictcareer_list_and_enrich(make_ctx):
    route = respx.get("https://www.ictcareer.ch/jobs").respond(text=fixture_text("ictcareer_list.html"))
    ctx = make_ctx()
    listings = list(IctCareerAdapter().fetch(ctx))
    assert len(listings) == 3
    assert route.call_count == 1  # resultCount reached on page 1
    assert route.calls[0].request.url.params.get_list("tag") == ["538", "533", "540"]
    first = listings[0]
    assert first.url == f"https://www.ictcareer.ch/job/{first.source_job_id}"
    assert first.extra["xref"]  # jobs.ch UUID

    respx.get(first.url).respond(text=fixture_text("ictcareer_detail.html"))
    enriched = IctCareerAdapter().enrich(ctx, first)
    assert enriched.description_html.startswith("<p>")
    assert "Festanstellung" in enriched.employment_text


@respx.mock
def test_ictjobs(make_ctx):
    posts = json.loads(fixture_text("ictjobs_posts.json"))
    respx.get("https://ictjobs.ch/wp-json/wp/v2/posts").respond(json=posts, headers={"X-WP-TotalPages": "1"})
    for post in posts:
        respx.get(post["link"]).respond(text=fixture_text("ictjobs_detail.html"))
    listings = list(IctJobsAdapter().fetch(make_ctx()))
    assert len(listings) == 2
    first = listings[0]
    assert first.source_job_id == "199935"
    assert first.title == "Oracle PL/SQL Developer (f/m/x)"
    assert first.company == "IBM Suisse SA"
    assert first.location_text == "1212 Grand-Lancy"
    assert first.employment_text == "FULL_TIME, PART_TIME"
    assert first.description_html and "IBM Consulting" in first.description_html


def test_foorilla_requires_key(make_ctx):
    with pytest.raises(MissingApiKey):
        list(FoorillaAdapter().fetch(make_ctx()))


@respx.mock
def test_foorilla_with_key(make_ctx, settings):
    settings.api_keys = {"foorilla": SecretStr("k")}
    job = {
        "id": 7,
        "title": "Senior Python Backend Engineer",
        "location": "Zurich, Switzerland",
        "published": "2026-10-18T10:00:00Z",
        "expired": None,
        "apply_url": "https://example.org/apply/7",
        "company": {"name": "Acme AG", "agency": False},
        "salary_min": 120000,
        "salary_max": 140000,
        "salary_min_est": 1,
        "salary_currency": "CHF",
        "has_remote": False,
        "work_mode": 2,
        "countries": [{"code": "CH", "name": "Switzerland"}],
        "tags": [{"name": "python"}, {"name": "django"}],
        "topics": [{"name": "Backend"}],
        "language": "en",
        "experience_level": "senior",
    }
    route = respx.get("https://foorilla.com/api/v1/hiring/job/").respond(
        json={"results": [job], "count": 1, "pages": 1, "page": 1, "page_size": 200}
    )
    listings = list(FoorillaAdapter().fetch(make_ctx({"country_id": 41})))
    assert route.calls[0].request.headers["Api-Key"] == "k"
    assert route.calls[0].request.url.params["country"] == "41"
    assert listings[0].salary_text == "CHF 120000 - 140000 per year"
    assert listings[0].extra["remote"] == "hybrid"


@respx.mock
def test_source_level_failure_raises(make_ctx):
    respx.get("https://swissdevjobs.ch/api/jobsLight").mock(return_value=httpx.Response(403))
    with pytest.raises(Exception, match="403"):
        list(SwissDevJobsAdapter().fetch(make_ctx()))
