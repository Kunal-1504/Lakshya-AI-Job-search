"""Opt-in, read-only browser collection. Refuse robots denial, login walls and CAPTCHAs."""

import json
import logging
import random
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from lakshya.models import Job
from lakshya.scrapers.base import USER_AGENTS, BaseScraper, BlockedSource, normalized_job

log = logging.getLogger(__name__)
BLOCK_MARKERS = (
    "verify you are human",
    "unusual traffic",
    "access denied",
    "security check",
    "sign in to view",
    "log in to continue",
    "captcha challenge",
)


def jsonld_jobs(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    result = []

    def walk(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            kinds = value.get("@type", [])
            if kinds == "JobPosting" or isinstance(kinds, list) and "JobPosting" in kinds:
                result.append(value)
            else:
                for child in value.values():
                    if isinstance(child, (list, dict)):
                        walk(child)

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            walk(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError):
            continue
    return result


class PublicPageScraper(BaseScraper):
    domains: tuple[str, ...] = ()
    link_patterns: tuple[str, ...] = ()

    def accepted(self, url: str) -> bool:
        host = urlparse(url).hostname or ""
        return urlparse(url).scheme == "https" and any(
            host == d or host.endswith("." + d) for d in self.domains
        )

    async def collect(self) -> list[Job]:
        urls = list(self.settings.public_search.get(self.name, []))
        if not urls:
            return []
        jobs = []
        visited: set[str] = set()
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS), service_workers="block"
            )

            async def read_only(route: Any) -> None:
                request = route.request
                if request.method not in {"GET", "HEAD"}:
                    await route.abort()
                elif request.is_navigation_request():
                    if not self.accepted(request.url) or not await self.http.allowed(request.url):
                        await route.abort()
                    else:
                        await self.http.limiter.wait(request.url)
                        await route.continue_()
                else:
                    await route.continue_()

            await context.route("**/*", read_only)
            page = await context.new_page()
            try:
                while urls and len(visited) < self.settings.max_pages:
                    url = urls.pop(0)
                    if url in visited or not self.accepted(url):
                        continue
                    visited.add(url)
                    if not await self.http.allowed(url):
                        raise BlockedSource(
                            "robots.txt disallows collection or could not be verified"
                        )
                    # Each navigation, including redirects, is rate limited by the route handler.
                    response = None
                    for attempt in range(3):
                        response = await page.goto(
                            url, wait_until="domcontentloaded", timeout=30000
                        )
                        if (
                            response
                            and (response.status == 429 or response.status >= 500)
                            and attempt < 2
                        ):
                            import asyncio

                            await asyncio.sleep(2 ** (attempt + 1))
                            continue
                        break
                    if response and response.status >= 400:
                        raise BlockedSource(f"Public page returned {response.status}")
                    text = (await page.locator("body").inner_text()).lower()
                    challenges = page.locator(
                        'iframe[src*="captcha"], iframe[src*="challenge"], .g-recaptcha, .h-captcha'
                    )
                    if any(marker in text for marker in BLOCK_MARKERS) or await challenges.count():
                        raise BlockedSource(
                            "CAPTCHA, login wall or anti-bot block; stopped without bypass"
                        )
                    if any(
                        term in urlparse(page.url).path.lower()
                        for term in ("login", "signin", "authwall", "checkpoint")
                    ):
                        raise BlockedSource("Login wall detected")
                    html = await page.content()
                    jobs.extend(
                        self.normalize_rows(
                            jsonld_jobs(html), lambda row: self.parse(row, page.url)
                        )
                    )
                    soup = BeautifulSoup(html, "html.parser")
                    for anchor in soup.select("a[href]"):
                        link = urljoin(page.url, str(anchor["href"]))
                        if (
                            self.accepted(link)
                            and any(p in link for p in self.link_patterns)
                            and link not in visited
                        ):
                            urls.append(link)
                    if len(jobs) >= self.settings.max_jobs_per_source:
                        break
            finally:
                await browser.close()
        return jobs[: self.settings.max_jobs_per_source]

    def parse(self, row: dict[str, Any], page_url: str) -> Job:
        locations = row.get("jobLocation", [])
        locations = locations if isinstance(locations, list) else [locations]
        addresses = [loc.get("address", {}) for loc in locations]
        location = ", ".join(
            " ".join(
                str(a.get(k, "")) for k in ("addressLocality", "addressRegion", "addressCountry")
            ).strip()
            for a in addresses
        )
        restrictions = row.get("applicantLocationRequirements", [])
        restrictions = restrictions if isinstance(restrictions, list) else [restrictions]
        countries = [r.get("name", "") for r in restrictions if isinstance(r, dict)]
        company = row.get("hiringOrganization", {})
        identifier = row.get("identifier", page_url)
        if isinstance(identifier, dict):
            identifier = identifier.get("value", page_url)
        remote = "remote" if row.get("jobLocationType") == "TELECOMMUTE" else "unknown"
        return normalized_job(
            self.name,
            identifier,
            row["title"],
            company.get("name", "Unknown"),
            ", ".join(countries) or location or "Unknown",
            row.get("description", ""),
            row.get("url") or page_url,
            row.get("datePosted"),
            remote,
            restrictions=countries,
        )
