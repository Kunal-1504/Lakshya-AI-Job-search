from lakshya.scrapers.public_pages import PublicPageScraper


class IndeedScraper(PublicPageScraper):
    name = "indeed"
    domains = (
        "indeed.com",
        "indeed.co.in",
    )
    link_patterns = ("/viewjob",)
