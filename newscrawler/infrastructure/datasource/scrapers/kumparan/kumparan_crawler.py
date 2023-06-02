import logging
import re
from typing import List, Dict

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class KumparanCrawler(Crawler):
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
                    branch_name = re.sub(r"(https://kumparan.com/sitemap_channel_)(.*)(.xml)", r"\2", link)
                    branch_name = branch_name.strip()
                    branches[branch_name] = link.strip()
        return branches

    @staticmethod
    def _get_whole_text(soup):
        sentences = soup.find_all(
            "span",
            attrs={
                "data-qa-id": "story-paragraph",
            },
        )
        texts = []
        for sentence in sentences:
            sentence = sentence.get_text(" ").strip()
            if sentence:
                texts.append(sentence)
        return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = []
        scripts = soup.find_all("script", attrs={"data-rh":"true","type":"application/ld+json"})
        for script in scripts:
            try:
                script = str(script).replace('<script data-rh="true" type="application/ld+json">', '')
                script = script.replace('</script>', '')
                script = eval(script)
                try:
                    author = script['author']['name']
                    reporters.append(author)
                    break
                except KeyError:
                    continue
            except BaseException as e:
                logger.info(f'Error while getting reporter on  {self.website_name}. Reason: {e}')
        return reporters
