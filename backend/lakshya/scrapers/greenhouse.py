import logging
from urllib.parse import quote

from lakshya.models import Job
from lakshya.scrapers.base import BaseScraper, normalized_job
from lakshya.scrapers.boards import employer_boards


class GreenhouseScraper(BaseScraper):
    name = "greenhouse"

    async def collect(self) -> list[Job]:
        jobs = []
        for board in employer_boards(self.settings, self.name):
            try:
                response = await self.http.get(
                    f"https://boards-api.greenhouse.io/v1/boards/{quote(board, safe='')}/jobs",
                    {"content": "true"},
                )
                jobs.extend(
                    self.normalize_rows(
                        response.json().get("jobs", []),
                        lambda row, board=board: normalized_job(
                            self.name,
                            row["id"],
                            row["title"],
                            board,
                            row.get("location", {}).get("name", "Unknown"),
                            row.get("content", ""),
                            f"https://job-boards.greenhouse.io/{quote(board, safe='')}/jobs/{row['id']}",
                            row.get("first_published") or row.get("first_published_at"),
                            basis="first_published",
                            source_url=row["absolute_url"],
                        ),
                    )
                )
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "Greenhouse board %s failed: %s", board, type(exc).__name__
                )
        # Never substitute updated_at for posted_at. Unknown dates are filtered by the pipeline.
        return self.limit_jobs(jobs)
