from lakshya.scrapers.public_pages import PublicPageScraper


class NaukriScraper(PublicPageScraper):
    name = "naukri"
    domains = ("naukri.com",)
    link_patterns = ("/job-listings-",)
