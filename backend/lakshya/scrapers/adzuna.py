import logging
import os
from typing import Any

from lakshya.models import Job
from lakshya.scrapers.base import BaseScraper, normalized_job


class AdzunaScraper(BaseScraper):
    name = "adzuna"

    async def collect(self) -> list[Job]:
        app_id, app_key = os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")
        if not app_id or not app_key:
            logging.getLogger(__name__).info("Adzuna disabled: no environment credentials")
            return []
        jobs = []
        for role in self.settings.target_roles:
            for page in range(1, self.settings.max_pages + 1):
                response = await self.http.get(
                    f"https://api.adzuna.com/v1/api/jobs/in/search/{page}",
                    {
                        "app_id": app_id,
                        "app_key": app_key,
                        "what": role,
                        "results_per_page": 50,
                        "sort_by": "date",
                        "max_days_old": 1,
                        "content-type": "application/json",
                    },
                )
                rows = response.json().get("results", [])
                jobs.extend(self.normalize_rows(rows, self.parse))
                if not rows or len(jobs) >= self.settings.max_jobs_per_source:
                    break
            if len(jobs) >= self.settings.max_jobs_per_source:
                break
        return jobs[: self.settings.max_jobs_per_source]

    def parse(self, row: dict[str, Any]) -> Job:
        return normalized_job(
            self.name,
            row["id"],
            row["title"],
            row.get("company", {}).get("display_name", "Unknown"),
            row.get("location", {}).get("display_name", "India"),
            row.get("description", ""),
            row["redirect_url"],
            row.get("created"),
            "unknown",
            row.get("salary_min"),
            basis="feed_created",
        )
