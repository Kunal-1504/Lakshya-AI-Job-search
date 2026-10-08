from lakshya.models import Job
from lakshya.scrapers.base import BaseScraper, normalized_job


class RemotiveScraper(BaseScraper):
    name = "remotive"

    async def collect(self) -> list[Job]:
        response = await self.http.get("https://remotive.com/api/remote-jobs")
        return self.normalize_rows(
            response.json().get("jobs", []),
            lambda row: normalized_job(
                self.name,
                row["id"],
                row["title"],
                row["company_name"],
                row.get("candidate_required_location", "Unknown"),
                row.get("description", ""),
                row["url"],
                row.get("publication_date"),
                "remote",
                row.get("salary"),
            ),
        )
