"""Conservative fuzzy identity matching without conflating distinct job levels."""

import re

from rapidfuzz.fuzz import ratio, token_sort_ratio

from lakshya.models import Job
from lakshya.platforms import AUTO_PLATFORMS
from lakshya.utils import normalize


def company_key(company: str) -> str:
    value = normalize(company)
    return re.sub(
        r"\b(?:pvt|private|limited|ltd|inc|incorporated|llc|corp|corporation)\b", "", value
    ).strip()


def application_key(job: Job) -> str:
    return company_key(job.company) + "|" + normalize(job.title)


def level(title: str) -> str:
    found = re.findall(
        r"\b(?:senior|sr|junior|jr|lead|staff|principal|intern|ii|iii|iv|[1-4])\b", normalize(title)
    )
    aliases = {"sr": "senior", "jr": "junior"}
    return " ".join(aliases.get(x, x) for x in found)


def same_job(a: Job, b: Job) -> bool:
    if a.company.lower() == "unknown" or b.company.lower() == "unknown":
        return str(a.apply_url) == str(b.apply_url)
    if level(a.title) != level(b.title):
        return False
    return (
        ratio(company_key(a.company), company_key(b.company)) >= 92
        and token_sort_ratio(normalize(a.title), normalize(b.title)) >= 93
        and token_sort_ratio(normalize(a.location), normalize(b.location)) >= 90
    )


def deduplicate(jobs: list[Job]) -> list[Job]:
    result: list[Job] = []
    # Favor direct employer links, then descriptions with more evidence.
    ordered = sorted(
        jobs,
        key=lambda j: (j.source in AUTO_PLATFORMS, len(j.description)),
        reverse=True,
    )
    for job in ordered:
        if not any(
            job.id == old.id or str(job.apply_url) == str(old.apply_url) or same_job(job, old)
            for old in result
        ):
            result.append(job)
    return result
