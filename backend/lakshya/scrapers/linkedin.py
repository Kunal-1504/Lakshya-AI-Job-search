from lakshya.scrapers.public_pages import PublicPageScraper


class LinkedInScraper(PublicPageScraper):
    name = "linkedin"
    domains = ("linkedin.com",)
    link_patterns = ("/jobs/view/",)
