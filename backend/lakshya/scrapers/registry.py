from lakshya.scrapers.adzuna import AdzunaScraper
from lakshya.scrapers.ashby import AshbyScraper
from lakshya.scrapers.greenhouse import GreenhouseScraper
from lakshya.scrapers.himalayas import HimalayasScraper
from lakshya.scrapers.indeed import IndeedScraper
from lakshya.scrapers.lever import LeverScraper
from lakshya.scrapers.linkedin import LinkedInScraper
from lakshya.scrapers.naukri import NaukriScraper
from lakshya.scrapers.recruitee import RecruiteeScraper
from lakshya.scrapers.remoteok import RemoteOKScraper
from lakshya.scrapers.remotive import RemotiveScraper
from lakshya.scrapers.wwr import WWRScraper

REGISTRY = {
    cls.name: cls
    for cls in (
        AdzunaScraper,
        AshbyScraper,
        GreenhouseScraper,
        HimalayasScraper,
        IndeedScraper,
        LeverScraper,
        LinkedInScraper,
        NaukriScraper,
        RecruiteeScraper,
        RemoteOKScraper,
        RemotiveScraper,
        WWRScraper,
    )
}
