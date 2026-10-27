"""Manual live smoke tests (§13). Run with: pytest -m live -s

Fetches the first listings from each source over the network and checks that
parsing still works. Does not touch the database.
"""

from __future__ import annotations

from itertools import islice

import pytest

from jobscraper.adapters import ADAPTERS
from jobscraper.adapters.base import has_enrich

pytestmark = pytest.mark.live


@pytest.mark.parametrize("name", [n for n in ADAPTERS if n != "foorilla"])
def test_source_live(name, make_ctx, http):
    http.throttle.default_interval = 1.0
    adapter = ADAPTERS[name]()
    ctx = make_ctx({"max_pages": 1})
    listings = list(islice(adapter.fetch(ctx), 5))
    assert listings, f"{name} returned nothing"
    for item in listings:
        assert item.source_job_id and item.title and item.url.startswith("http")
    if has_enrich(adapter):
        enriched = adapter.enrich(ctx, listings[0])
        assert enriched.description_html
    print(name, [(i.title, i.company, i.location_text) for i in listings[:3]])
