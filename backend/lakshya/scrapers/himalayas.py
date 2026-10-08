from typing import Any

from lakshya.models import Job
from lakshya.scrapers.base import BaseScraper, normalized_job


class HimalayasScraper(BaseScraper):
    name = "himalayas"

    async def collect(self) -> list[Job]:
        jobs = []
        seen: set[str] = set()
        for role in self.settings.target_roles:
            for page in range(1, self.settings.max_pages + 1):
                response = await self.http.get(
                    "https://himalayas.app/jobs/api/search",
                    {"q": role, "country": "IN", "sort": "recent", "page": page},
                )
                rows = self.normalize_rows(response.json().get("jobs", []), self.parse)
                fresh = [job for job in rows if job.id not in seen]
                if not fresh:
                    break
                jobs.extend(fresh)
                seen.update(job.id for job in fresh)
                if len(rows) < 20 or len(jobs) >= self.settings.max_jobs_per_source:
                    break
            if len(jobs) >= self.settings.max_jobs_per_source:
                break
        return jobs[: self.settings.max_jobs_per_source]

    def parse(self, row: dict[str, Any]) -> Job:
        locations = row.get("locationRestrictions") or []
        # Empty restrictions mean worldwide according to this feed's schema.
        salary = " ".join(str(row.get(k) or "") for k in ("currency", "minSalary", "maxSalary"))
        return normalized_job(
            self.name,
            row["guid"],
            row["title"],
            row["companyName"],
            ", ".join(locations) if locations else "Worldwide",
            row.get("description", ""),
            row["applicationLink"],
            row.get("pubDate"),
            "remote",
            salary.strip(),
            restrictions=locations,
            source_url=row["guid"] if str(row["guid"]).startswith("http") else None,
        )
