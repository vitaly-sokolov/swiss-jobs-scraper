from __future__ import annotations

from decimal import Decimal

import pytest

from jobscraper.adapters.base import RawListing
from jobscraper.normalize import Normalizer, dedupe_key
from jobscraper.normalize.employment import employment_type
from jobscraper.normalize.filter import TechFilter, geography_ok
from jobscraper.normalize.language import detect_language
from jobscraper.normalize.location import Locator, remote_mode
from jobscraper.normalize.salary import parse_salary
from jobscraper.normalize.seniority import seniority
from jobscraper.normalize.tags import Tagger
from jobscraper.normalize.text import html_to_text, normalize_title


@pytest.mark.parametrize(
    ("text", "lo", "hi", "currency", "period"),
    [
        ("CHF 110000 - 130000 per year", 110000, 130000, "CHF", "year"),
        ("CHF 110'000 – 130'000 pro Jahr", 110000, 130000, "CHF", "year"),
        ("120k-140k CHF", 120000, 140000, "CHF", "year"),
        ("CHF 9'500 / Monat", 9500, 9500, "CHF", "month"),
        ("EUR 85.000 brutto p.a.", 85000, 85000, "EUR", "year"),
        ("CHF 120/h", 120, 120, "CHF", "hour"),
        ("Fr. 950 par jour", 950, 950, "CHF", "day"),
        ("CHF 130 000 – 110 000", 110000, 130000, "CHF", "year"),
    ],
)
def test_parse_salary(text, lo, hi, currency, period):
    s = parse_salary(text)
    assert (s.min, s.max, s.currency, s.period) == (Decimal(lo), Decimal(hi), currency, period)


@pytest.mark.parametrize("text", [None, "", "attractive salary", "competitive", "CHF 5", "100%"])
def test_parse_salary_unparseable(text):
    s = parse_salary(text)
    assert s.min is None and s.max is None


@pytest.fixture(scope="module")
def locator(vocab):
    return Locator(vocab.locations)


@pytest.mark.parametrize(
    ("text", "canton", "country"),
    [
        ("Zürich", "ZH", "CH"),
        ("8022 Zürich", "ZH", "CH"),
        ("Freienbach SZ", "SZ", "CH"),
        ("Le Mont-sur-Lausanne", "VD", "CH"),
        ("Genève", "GE", "CH"),
        ("Geneva", "GE", "CH"),
        ("St.Gallen", "SG", "CH"),
        ("St. Gallen", "SG", "CH"),
        ("6343 Rotkreuz", "ZG", "CH"),
        ("1212 Grand-Lancy", "GE", "CH"),
        ("Neckarsulmstrasse 41, 2540 Grenchen", "SO", "CH"),
        ("6900 Somewhere", "TI", "CH"),
        ("Region Bern", "BE", "CH"),
        ("Lörrach", None, "DE"),
        ("Annemasse, France", None, "FR"),
        ("Vaduz", None, "LI"),
        ("Atlantis", None, None),
    ],
)
def test_locate(locator, text, canton, country):
    place = locator.locate(text)
    assert (place.canton, place.country) == (canton, country)


def test_locate_border_flag(locator):
    assert locator.locate("Konstanz").border is True
    assert locator.locate("Rheinfelden").canton == "AG"
    assert locator.locate("Rheinfelden (Baden)").country == "DE"


def test_locate_country_hint(locator):
    assert locator.locate("Berlin", "Germany").country == "DE"
    assert locator.locate("Zürich", "CH").canton == "ZH"


@pytest.mark.parametrize(
    ("hint", "title", "location", "body", "expected"),
    [
        ("hybrid", None, None, None, "hybrid"),
        ("office", None, None, None, "onsite"),
        ("remote", None, None, None, "remote"),
        (None, "Backend Engineer (Remote)", None, None, "remote"),
        (None, None, "Remote, Switzerland", None, "remote"),
        (None, None, None, "Fully remote within Switzerland", "remote"),
        (None, None, None, "2 Tage Home-Office pro Woche möglich", "hybrid"),
        (None, None, None, "Télétravail possible, bureaux sur site à Genève", "hybrid"),
        (None, None, None, "Hybrid work model", "hybrid"),
        (None, None, None, "You will work on-site in our lab", "onsite"),
        (None, None, None, "Our office in Zug", "unknown"),
    ],
)
def test_remote_mode(hint, title, location, body, expected):
    assert remote_mode(hint, title, location, body) == expected


@pytest.mark.parametrize(
    ("title", "hint", "expected"),
    [
        ("Senior Backend Engineer", None, "senior"),
        ("Lead AI Engineer", None, "lead"),
        ("Junior Python Entwickler", None, "junior"),
        ("Teamleiter Softwareentwicklung", None, "lead"),
        ("Développeur confirmé Java", None, "senior"),
        ("Backend Engineer", None, "unknown"),
        ("Backend Engineer", "Regular", "mid"),
        ("Backend Engineer", "Senior", "senior"),
    ],
)
def test_seniority(title, hint, expected):
    assert seniority(title, hint) == expected


@pytest.mark.parametrize(
    ("text", "title", "expected"),
    [
        ("Festanstellung, 80-100%", "", "full_time"),
        ("Full-Time", "", "full_time"),
        ("Part-Time", "", "part_time"),
        ("Festanstellung, 40-60%", "", "part_time"),
        ("Freelance", "", "contract"),
        ("Temporär", "", "contract"),
        ("Praktikum", "", "internship"),
        (None, "Software Engineering Intern", "internship"),
        (None, "Backend Engineer", "unknown"),
    ],
)
def test_employment_type(text, title, expected):
    assert employment_type(text, title) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Wir suchen eine erfahrene Person für unser Team und bieten dir die Möglichkeit, mit uns zu wachsen.", "de"),
        ("Nous recherchons une personne pour notre équipe et vous offrons un environnement de travail dans la région.", "fr"),
        ("We are looking for an engineer to join our team and you will work with the best people in the industry.", "en"),
        ("Python", None),
        (None, None),
    ],
)
def test_language(text, expected):
    assert detect_language(text) == expected


def test_tags(vocab):
    tagger = Tagger(vocab.tech_tags)
    tags = tagger.tags("Senior Backend Engineer (Python/FastAPI)", "We use PostgreSQL, k8s and C# with .NET Core", provided=["LLM"])
    assert {"python", "fastapi", "postgresql", "kubernetes", "c#", ".net", "llm"} <= set(tags)
    assert "java" not in tagger.tags("JavaScript developer")
    assert "golang" not in tagger.tags("Let's go to Zürich")
    assert "golang" in tagger.tags("", provided=["Go lang"])


def test_html_to_text():
    assert html_to_text("<h1>Title</h1><p>Hello&nbsp;<b>world</b></p><ul><li>a</li></ul>") == "Title\nHello\xa0world\na"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Senior Backend Engineer (m/w/d) - 100%", "senior backend engineer"),
        ("Senior Backend Engineer (f/m/x) 80-100%", "senior backend engineer"),
        ("Développeur Python (H/F)", "developpeur python"),
        ("Softwareentwickler:in .NET", "softwareentwickler .net"),
    ],
)
def test_normalize_title(title, expected):
    assert normalize_title(title) == expected


def test_dedupe_key_ignores_noise():
    a = dedupe_key("Acme AG", "Senior Backend Engineer (m/w/d) 100%", "ZH")
    b = dedupe_key("ACME", "Senior Backend Engineer (f/m/x) 80-100%", "zh")
    assert a == b
    assert a != dedupe_key("Acme AG", "Senior Backend Engineer", "BE")
    # Unknown canton falls back to location text, so different places do not collide.
    assert dedupe_key("Acme", "Engineer", "Atlantis") != dedupe_key("Acme", "Engineer", "Lemuria")


# ------------------------------------------------------------------- filter


@pytest.fixture(scope="module")
def tech_filter(vocab):
    return TechFilter(vocab.tech_keywords)


@pytest.mark.parametrize(
    "title",
    [
        "Senior Backend & AI Engineer (m/w/d) - 100%",
        "Backend Developer Java",
        "Fullstack Engineer (Frontend/Backend)",
        "Software Engineer Python",
        "Softwareentwickler/in Java 80-100%",
        "Applikationsentwickler .NET",
        "Développeur Back-end PHP",
        "Ingénieur logiciel",
        "Machine Learning Engineer",
        "AI Engineer",
        "LLM Engineer",
        "KI-Ingenieur (w/m/d)",
        "Senior Java Developer",
        "Site Reliability Engineer",
    ],
)
def test_filter_keeps(tech_filter, title):
    assert tech_filter.check(title).keep, title


@pytest.mark.parametrize(
    "title",
    [
        "Sales Manager Software",
        "IT Recruiter",
        "IT Support Specialist",
        "1st Level Support",
        "SAP ABAP Developer",
        "Systemadministrator Windows",
        "Frontend Developer React",
        "UX Designer",
        "Lehrstelle Informatiker EFZ",
        "Test Engineer",
        "Elektroingenieur",
        "Product Owner",
        "Buchhalter",
        "Network Engineer",
    ],
)
def test_filter_rejects(tech_filter, title):
    assert not tech_filter.check(title).keep, title


def test_filter_description_evidence(tech_filter):
    title = "Data Platform Engineer"
    assert not tech_filter.check(title, "Wir betreiben Datenbanken.").keep
    assert tech_filter.check(title, "Python, Kafka, PostgreSQL and Kubernetes").keep


def test_filter_company_deny():
    f = TechFilter({"title_allow": ["backend"], "company_deny": [r"\brecruit"]})
    assert not f.check("Backend Engineer", company="Best Recruiters AG").keep


def test_geography():
    assert geography_ok("CH", False, "unknown")
    assert geography_ok(None, False, "unknown")
    assert geography_ok("DE", True, "onsite")
    assert geography_ok("US", False, "remote")
    assert not geography_ok("DE", False, "onsite")


def test_normalizer_end_to_end(vocab):
    raw = RawListing(
        source="swissdevjobs",
        source_job_id="1",
        url="https://example.org/1",
        title="Senior Backend & AI Engineer (m/w/d) - 100%",
        company="SCAIT",
        location_text="6343 Rotkreuz",
        description_html=None,
        posted_at=None,
        salary_text="CHF 110000 - 130000 per year",
        employment_text="Full-Time",
        extra={"workplace": "hybrid", "seniority": "Senior", "technologies": ["Python", "FastAPI"], "country": "CH"},
    )
    n = Normalizer(vocab)
    assert n.prefilter(raw).keep
    job = n.normalize(raw)
    assert (job.canton, job.country, job.remote, job.seniority, job.employment_type) == (
        "ZG", "CH", "hybrid", "senior", "full_time"
    )
    assert (job.salary_min, job.salary_max, job.salary_period) == (Decimal(110000), Decimal(130000), "year")
    assert {"python", "fastapi"} <= set(job.tech_tags)
    assert job.enriched and not job.details_fetched
    assert len(job.dedupe_key) == 64
