"""Read published offers from an employer's public Recruitee XML feed."""

import logging
import re
from datetime import UTC, datetime
from urllib.parse import quote, urlparse
from xml.etree import ElementTree as ET

from lakshya.models import Job
from lakshya.scrapers.base import BaseScraper, normalized_job
from lakshya.scrapers.boards import employer_boards
from lakshya.utils import parse_date

log = logging.getLogger(__name__)


class RecruiteeScraper(BaseScraper):
    name = "recruitee"

    async def collect(self) -> list[Job]:
        jobs = []
        for board in employer_boards(self.settings, self.name):
            # A tenant name, never an arbitrary URL or private-network destination.
            if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", board):
                log.warning("Recruitee: skipped invalid company board")
                continue
            try:
                response = await self.http.get(
                    f"https://{board}.recruitee.com/api/feeds/offers.xml"
                )
                if len(response.content) > 5_000_000 or b"<!DOCTYPE" in response.content.upper():
                    raise ValueError("Unexpected XML feed size or document type")
                root = ET.fromstring(response.content)
                if root.tag != "offers":
                    raise ValueError("Unexpected Recruitee feed format")
                for row in root.findall("offer"):
                    try:
                        job = self.parse(row, board)
                        if job:
                            jobs.append(job)
                    except (ValueError, TypeError, KeyError):
                        log.warning("Recruitee: skipped malformed listing")
            except Exception as exc:
                log.warning("Recruitee board %s failed: %s", board, type(exc).__name__)
        return self.limit_jobs(jobs)

    def parse(self, row: ET.Element, board: str) -> Job | None:
        def text(key: str) -> str:
            return (row.findtext(key) or "").strip()

        if text("status") not in {"", "published"}:
            return None
        # Recruitee uses an explicit UTC suffix rather than ISO 8601 in this feed.
        closed = parse_date(text("close_at").replace(" UTC", "+00:00"))
        if closed and closed <= datetime.now(UTC):
            return None
        slug = text("slug")
        if not slug or not text("id") or not text("title"):
            raise ValueError("Missing job identity")
        # Preserve the advertised link (including custom employer domains). Only
        # reviewed hosted forms qualify for auto mode; a custom domain needs help.
        url = text("apply_url") or f"https://{board}.recruitee.com/o/{quote(slug, safe='')}/c/new"
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Invalid employer application URL")
        locations = row.findall("locations/location")
        location = (
            "; ".join(
                ", ".join(filter(None, (loc.findtext("city"), loc.findtext("country"))))
                for loc in locations
            )
            or text("location")
            or ", ".join(filter(None, (text("city"), text("country"))))
        )
        remote = (
            "remote"
            if text("remote") == "true"
            else "hybrid"
            if text("hybrid") == "true"
            else "onsite"
            if text("on_site") == "true"
            else "unknown"
        )
        restrictions = list(
            dict.fromkeys(
                (loc.findtext("country_code") or loc.findtext("country") or "").strip()
                for loc in locations
            )
        )
        restrictions = [value for value in restrictions if value]
        if not restrictions and (text("country_code") or text("country")):
            restrictions = [text("country_code") or text("country")]
        return normalized_job(
            self.name,
            f"{board}:{text('id')}",
            text("title"),
            text("company_name") or board,
            location,
            text("description") + "\n" + text("requirements"),
            url,
            text("published_at").replace(" UTC", "+00:00") or None,
            remote,
            basis="published",
            restrictions=restrictions if remote == "remote" else [],
            source_url=text("careers_url") or url,
        )
