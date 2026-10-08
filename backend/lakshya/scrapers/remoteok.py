from lakshya.models import Job
from lakshya.scrapers.base import BaseScraper, normalized_job


class RemoteOKScraper(BaseScraper):
    name = "remoteok"

    async def collect(self) -> list[Job]:
        response = await self.http.get("https://remoteok.com/api")
        rows = [row for row in response.json() if "id" in row and "position" in row]
        return self.normalize_rows(
            rows,
            lambda row: normalized_job(
                self.name,
                row["id"],
                row["position"],
                row["company"],
                row.get("location", "Unknown"),
                row.get("description", ""),
                row["url"],
                row.get("date") or row.get("epoch"),
                "remote",
                row.get("salary_min"),
            ),
        )
