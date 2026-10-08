import logging
from typing import Any
from urllib.parse import quote

from lakshya.models import Job
from lakshya.scrapers.base import BaseScraper, normalized_job
from lakshya.scrapers.boards import employer_boards


class AshbyScraper(BaseScraper):
    name = "ashby"

    async def collect(self) -> list[Job]:
        jobs = []
        for board in employer_boards(self.settings, self.name):
            try:
                response = await self.http.get(
                    f"https://api.ashbyhq.com/posting-api/job-board/{quote(board, safe='')}",
                    {"includeCompensation": "true"},
                )
                rows = [r for r in response.json().get("jobs", []) if r.get("isListed", True)]
                jobs.extend(
                    self.normalize_rows(rows, lambda row, board=board: self.parse(row, board))
                )
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "Ashby board %s failed: %s", board, type(exc).__name__
                )
        return self.limit_jobs(jobs)

    def parse(self, row: dict[str, Any], board: str) -> Job:
        workplace = (
            row.get("workplaceType") or ("Remote" if row.get("isRemote") else "Unknown")
        ).lower()
        return normalized_job(
            self.name,
            row["id"],
            row["title"],
            board,
            row.get("location", "Unknown"),
            row.get("descriptionPlain", row.get("descriptionHtml", "")),
            row["applyUrl"],
            row.get("publishedAt"),
            workplace if workplace in {"remote", "hybrid", "onsite"} else "unknown",
            (row.get("compensation") or {}).get("compensationTierSummary"),
            basis="last_published",
        )
