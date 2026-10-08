from xml.etree import ElementTree as ET

import httpx
import pytest
from lakshya.applier import provider
from lakshya.matcher import location_allowed, required_years
from lakshya.scrapers.recruitee import RecruiteeScraper

FEED = """<offers><offer><id>123</id><slug>ai-engineer</slug><title>AI Engineer</title>
<company_name>Employer</company_name><description><![CDATA[<p>Python and SQL</p>]]></description>
<requirements><![CDATA[<p>1-2 years of experience required</p>]]></requirements>
<published_at>2026-10-07 01:00:00 UTC</published_at><updated_at>2026-10-08 01:00:00 UTC</updated_at>
<remote>true</remote><locations><location><city>Pune</city><country>India</country>
<country_code>IN</country_code></location><location><city>Bangalore</city><country>India</country>
<country_code>IN</country_code></location></locations></offer></offers>"""


@pytest.mark.asyncio
async def test_public_xml_feed_preserves_requirements_publication_and_locations(settings):
    class HTTP:
        async def get(self, url):
            assert url == "https://employer.recruitee.com/api/feeds/offers.xml"
            return httpx.Response(200, content=FEED)

    settings.boards = {"recruitee": ["employer"]}
    jobs = await RecruiteeScraper(settings, HTTP()).collect()
    job = jobs[0]
    assert len(jobs) == 1 and job.id == "recruitee:employer:123"
    assert str(job.apply_url) == "https://employer.recruitee.com/o/ai-engineer/c/new"
    assert job.posted_at.day == 7 and job.date_basis == "published"
    assert job.location_restrictions == ["IN"]
    assert "Pune" in job.location and "Bangalore" in job.location
    assert required_years(job.description) == 1 and location_allowed(job, settings)


def test_unknown_date_and_restricted_remote_country_do_not_become_auto_eligible(settings):
    row = ET.fromstring(FEED).find("offer")
    row.find("published_at").text = ""
    for loc in row.findall("locations/location"):
        loc.find("country_code").text = "US"
        loc.find("country").text = "United States"
    job = RecruiteeScraper(settings, None).parse(row, "employer")
    assert job.posted_at is None and job.date_basis == "unknown"
    assert not location_allowed(job, settings)


def test_closed_listing_excluded_and_custom_employer_link_preserved(settings):
    row = ET.fromstring(FEED).find("offer")
    ET.SubElement(row, "apply_url").text = "https://employer.example/o/ai/c/new"
    scraper = RecruiteeScraper(settings, None)
    assert provider(str(scraper.parse(row, "employer").apply_url)) == "generic"
    ET.SubElement(row, "close_at").text = "2020-01-01 00:00:00 UTC"
    assert scraper.parse(row, "employer") is None


@pytest.mark.asyncio
async def test_invalid_board_is_never_requested_and_xml_entities_rejected(settings):
    calls = []

    class HTTP:
        async def get(self, url):
            calls.append(url)
            return httpx.Response(
                200, content='<!DOCTYPE offers [<!ENTITY test "expanded">]><offers/>'
            )

    settings.boards = {"recruitee": ["127.0.0.1/path", "employer"]}
    assert await RecruiteeScraper(settings, HTTP()).collect() == []
    assert calls == ["https://employer.recruitee.com/api/feeds/offers.xml"]


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://metyisag.recruitee.com/o/ai/c/new", "recruitee"),
        ("https://recruitee.com/", "generic"),
        ("https://docs.recruitee.com/reference/offers", "generic"),
        ("https://api.recruitee.com/", "generic"),
        ("https://metyisag.recruitee.com.attacker.example/", "generic"),
    ],
)
def test_only_hosted_recruitee_tenants_classified(url, expected):
    assert provider(url) == expected
