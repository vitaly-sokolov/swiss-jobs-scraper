from jobscraper.adapters.base import SourceAdapter
from jobscraper.adapters.foorilla import FoorillaAdapter
from jobscraper.adapters.ictcareer import IctCareerAdapter
from jobscraper.adapters.ictjobs import IctJobsAdapter
from jobscraper.adapters.jobcloud import JobsChAdapter, JobupAdapter
from jobscraper.adapters.swissdevjobs import SwissDevJobsAdapter

ADAPTERS: dict[str, type[SourceAdapter]] = {
    a.name: a
    for a in (
        SwissDevJobsAdapter,
        JobsChAdapter,
        JobupAdapter,
        IctJobsAdapter,
        IctCareerAdapter,
        FoorillaAdapter,
    )
}
