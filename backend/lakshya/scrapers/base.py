import asyncio
import logging
import random
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from lakshya.config import Settings
from lakshya.models import Job
from lakshya.utils import parse_date, plain

log = logging.getLogger(__name__)
USER_AGENTS = [
    "Lakshya/0.1 (+personal job search; public read-only collector)",
    "Lakshya/0.1 (+RSS and public careers reader)",
]


class BlockedSource(RuntimeError):
    pass


class RateLimiter:
    """Serialize requests per domain, shared across all source instances."""

    def __init__(self, minimum: float = 3, maximum: float = 6) -> None:
        self.minimum, self.maximum = minimum, maximum
        self.locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.next_at: dict[str, float] = defaultdict(float)

    async def wait(self, url: str) -> None:
        host = urlparse(url).netloc.casefold()
        async with self.locks[host]:
            await asyncio.sleep(max(0, self.next_at[host] - time.monotonic()))
            self.next_at[host] = time.monotonic() + random.uniform(self.minimum, self.maximum)


class HTTP:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
        trace: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.trace = trace
        self.client = client or httpx.AsyncClient(
            timeout=settings.http_timeout, follow_redirects=False
        )
        self.limiter = RateLimiter(settings.request_delay_min, settings.request_delay_max)
        self.robots: dict[str, RobotFileParser | None] = {}
        self.robot_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        if urlparse(url).scheme != "https":
            raise ValueError("Collectors require HTTPS URLs")
        for attempt in range(3):
            await self.limiter.wait(url)
            try:
                started = time.perf_counter()
                parsed = urlparse(url)
                if self.trace:
                    self.trace(
                        {
                            "method": "GET",
                            "url": f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
                            "event": "started",
                            "attempt": attempt + 1,
                        }
                    )
                response = await self.client.get(
                    url,
                    params=params,
                    headers={
                        "User-Agent": random.choice(USER_AGENTS),
                        "Accept": "application/json, text/html, */*",
                    },
                )
                if self.trace:
                    self.trace(
                        {
                            "method": "GET",
                            "url": f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
                            "status": response.status_code,
                            "duration_ms": (time.perf_counter() - started) * 1000,
                            "bytes": len(response.content),
                            "event": "completed",
                        }
                    )
                if response.status_code in {401, 403}:
                    raise BlockedSource("Site refused public access; collector stopped")
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < 2:
                        retry = response.headers.get("Retry-After", "")
                        delay = min(60, float(retry)) if retry.isdigit() else 2 ** (attempt + 1)
                        await asyncio.sleep(delay)
                        continue
                response.raise_for_status()
                if 300 <= response.status_code < 400:
                    raise BlockedSource(
                        "Redirected endpoint; inspect configuration rather than bypass it"
                    )
                return response
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** (attempt + 1))
        raise RuntimeError("Request retries exhausted")

    async def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        async with self.robot_locks[root]:
            if root not in self.robots:
                try:
                    response = await self.get(root + "/robots.txt")
                    parser = RobotFileParser()
                    parser.parse(response.text.splitlines())
                    self.robots[root] = parser
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 404:
                        parser = RobotFileParser()
                        parser.parse([])
                        self.robots[root] = parser
                    else:
                        self.robots[root] = None
                except Exception:
                    self.robots[root] = None
        cached_parser = self.robots[root]
        return cached_parser is not None and all(
            cached_parser.can_fetch(ua, url) for ua in USER_AGENTS
        )

    async def close(self) -> None:
        await self.client.aclose()


def normalized_job(
    source: str,
    row_id: Any,
    title: str,
    company: str,
    location: str,
    description: str,
    url: str,
    posted: Any = None,
    remote: str = "unknown",
    salary: Any = None,
    basis: str = "published",
    restrictions: list[str] | None = None,
    source_url: str | None = None,
) -> Job:
    return Job(
        id=f"{source}:{row_id}",
        title=title,
        company=company,
        location=location or "Unknown",
        description=plain(description),
        apply_url=url,
        posted_at=parse_date(posted),
        source=source,
        remote_type=remote,
        salary=str(salary) if salary else None,
        date_basis=basis if posted is not None else "unknown",
        location_restrictions=restrictions or [],
        source_url=source_url or url,
    )


class BaseScraper(ABC):
    name: str

    def __init__(self, settings: Settings, http: HTTP) -> None:
        self.settings, self.http = settings, http

    @abstractmethod
    async def collect(self) -> list[Job]:
        """Return normalized jobs; orchestration isolates source failures."""

    def normalize_rows(self, rows: list[dict[str, Any]], parser: Any) -> list[Job]:
        jobs = []
        for row in rows:
            try:
                job = parser(row)
                if job:
                    jobs.append(job)
            except (ValueError, TypeError, KeyError):
                log.warning("%s: skipped malformed listing", self.name)
        return self.limit_jobs(jobs)

    def limit_jobs(self, jobs: list[Job]) -> list[Job]:
        from lakshya.matcher import location_allowed, required_years, role_allowed
        from lakshya.utils import is_fresh

        def priority(job: Job) -> tuple[bool, bool, float]:
            years = required_years(job.description)
            relevant = (
                role_allowed(job, self.settings)
                and location_allowed(job, self.settings)
                and (years is None or years <= self.settings.max_experience_years)
            )
            return (
                relevant,
                is_fresh(job, self.settings.freshness_hours),
                job.posted_at.timestamp() if job.posted_at else 0,
            )

        return sorted(jobs, key=priority, reverse=True)[: self.settings.max_jobs_per_source]
