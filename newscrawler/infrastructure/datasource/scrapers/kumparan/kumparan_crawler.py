import json
import logging
import re
from typing import List, Dict, Optional
from urllib.parse import urlparse

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class KumparanCrawler(Crawler):
    # DBT-05 (#24): this source's site selector had been dead for months (trafilatura
    # produced every saved article); trafilatura is its extractor by design.
    PRIMARY_EXTRACTOR = "trafilatura"

    # SRC-60 (#279): the newsroom publishes under desk accounts (kumparan.com/kumparannews/...,
    # /kumparanbisnis/, /kumparanoto/, /kumparantekno/). The same sitemaps list readers' blog
    # posts under the writer's own handle ("Tulisan dari ... tidak mewakili pandangan dari redaksi
    # kumparan": 321 of 1,878 stored articles on 2026-10-08, 0 under a desk account) and a few
    # partner accounts. From a 3-title sample of each other account with stored articles:
    # `pandangan-jogja` is a partner newsroom (local reporting by its own reporters) and is kept;
    # `TDA` (an entrepreneurs' community's own press releases) and `daily-tech-science` (unsigned
    # rewrites of wire tech news) are not news by this outlet.
    _DESK_ACCOUNT = re.compile(r"^kumparan[a-z]*$")
    PARTNER_NEWSROOMS = frozenset({"pandangan-jogja"})

    def __init__(self):
        super(KumparanCrawler, self).__init__()
        self.website_name = WebsiteName.KUMPARAN.value
        self.website_url = URL.KUMPARAN.value

    def _get_branches(self, soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            link = sitemap.find("loc")
            if link:
                link = link.get_text(" ").strip()
                if "sitemap_channel_" in link:
                    branch_name = re.sub(
                        r"(https://kumparan.com/sitemap_channel_)(.*)(.xml)",
                        r"\2",
                        link,
                    )
                    branch_name = branch_name.strip()
                    branches[branch_name] = link.strip()
        return branches

    def out_of_scope_reason(self, link: Optional[str]) -> Optional[str]:
        account = urlparse(link or "").path.strip("/").split("/")[0].lower()
        if self._DESK_ACCOUNT.match(account) or account in self.PARTNER_NEWSROOMS:
            return None
        return "not a kumparan newsroom account (reader post)"

    def _get_reporter_from_text(self, soup) -> List[str]:
        # SRC-11 (#68): the page's JSON-LD is third-party content; parse it as
        # JSON, never eval() it. eval only worked by accident (JSON object/
        # array/string/number syntax is valid Python) and broke on any
        # true/false/null literal. `.string`, not `.get_text()`: bs4 >= 4.9
        # deliberately skips <script> contents in get_text().
        scripts = soup.find_all(
            "script", attrs={"data-rh": "true", "type": "application/ld+json"}
        )
        for script in scripts:
            raw = script.string
            if not raw or not raw.strip():
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                logger.info(
                    f"Unparseable ld+json on {self.website_name}: {e}"
                )
                continue
            names = self._author_names(data)
            if names:
                return names
        return []

    @staticmethod
    def _author_names(data) -> List[str]:
        """schema.org `author` is a Person/Organization object or a list of
        them; a bare string is also seen in the wild. Only NewsArticle-shaped
        blocks carry it -- a BreadcrumbList on the same page has none."""
        if not isinstance(data, dict):
            return []
        author = data.get("author")
        if isinstance(author, dict):
            author = [author]
        elif isinstance(author, str):
            return [author.strip()] if author.strip() else []
        if not isinstance(author, list):
            return []
        names = []
        for entry in author:
            if isinstance(entry, dict):
                name = entry.get("name")
            else:
                name = entry
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
        return names
