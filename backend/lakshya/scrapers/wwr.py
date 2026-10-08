from typing import Any

import feedparser

from lakshya.models import Job
from lakshya.scrapers.base import BaseScraper, normalized_job


class WWRScraper(BaseScraper):
    name = "wwr"

    async def collect(self) -> list[Job]:
        response = await self.http.get("https://weworkremotely.com/remote-jobs.rss")
        feed = feedparser.parse(response.text)
        if feed.bozo and not feed.entries:
            raise ValueError("Invalid WWR RSS feed")
        return self.normalize_rows(feed.entries, self.parse)

    def parse(self, row: dict[str, Any]) -> Job:
        company, separator, title = row["title"].partition(":")
        return normalized_job(
            self.name,
            row.get("id", row["link"]),
            title.strip() if separator else company,
            company.strip() if separator else "Unknown",
            row.get("region", "Unknown"),
            row.get("summary", ""),
            row["link"],
            row.get("published"),
            "remote",
        )
