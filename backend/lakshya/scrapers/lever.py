import logging
from typing import Any
from urllib.parse import quote

from lakshya.models import Job
from lakshya.scrapers.base import BaseScraper, normalized_job
from lakshya.scrapers.boards import employer_boards


class LeverScraper(BaseScraper):
    name = "lever"

    async def collect(self) -> list[Job]:
        jobs = []
        for board in employer_boards(self.settings, self.name):
            try:
                for page in range(self.settings.max_pages):
                    response = await self.http.get(
                        f"https://api.lever.co/v0/postings/{quote(board, safe='')}",
                        {"mode": "json", "skip": page * 100, "limit": 100},
                    )
                    rows = response.json()
                    jobs.extend(
                        self.normalize_rows(rows, lambda row, board=board: self.parse(row, board))
                    )
                    if len(rows) < 100 or len(jobs) >= self.settings.max_jobs_per_source:
                        break
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "Lever board %s failed: %s", board, type(exc).__name__
                )
        return self.limit_jobs(jobs)

    def parse(self, row: dict[str, Any], board: str) -> Job:
        description = row.get("descriptionPlain", row.get("description", ""))
        description += "\n" + "\n".join(
            item.get("text", "") + " " + item.get("content", "") for item in row.get("lists", [])
        )
        description += "\n" + row.get("additionalPlain", "")
        workplace = (row.get("workplaceType") or "unknown").lower()
        return normalized_job(
            self.name,
            row["id"],
            row["text"],
            board,
            row.get("categories", {}).get("location", "Unknown"),
            description,
            str(row.get("applyUrl") or row.get("hostedUrl") or ""),
            row.get("publishedAt"),
            workplace if workplace in {"remote", "hybrid", "onsite"} else "unknown",
        )
