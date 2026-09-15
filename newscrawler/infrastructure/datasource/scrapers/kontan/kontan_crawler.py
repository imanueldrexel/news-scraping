import logging
import re
from typing import Dict, List

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.core.utils.utils import (
    preprocess_text,
)

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class KontanCrawler(Crawler):
    def __init__(self):
        super(KontanCrawler, self).__init__()
        self.website_name = WebsiteName.KONTAN.value
        self.website_url = URL.KONTAN.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            avoided_keyword = [
                "insight",
                "edsus",
                "exportexpert",
                "kilaskementerian",
                "kilaskorporasi",
                "pialaeropa",
            ]
            link = sitemap.find("loc")
            if link:
                link = link.get_text(" ").strip()
                continue_sentence = 0
                for keyword in avoided_keyword:
                    if keyword in link:
                        continue_sentence = 1
                if continue_sentence:
                    continue
                if "/news/" in link:
                    branch_name = re.sub(r"(.*)(//)(.*)(.kontan)(.*)", r"\3", link)
                    if branch_name == "www":
                        branch_name = re.sub(
                            r"(https://www.kontan.co.id/)(.*)(/news/sitemap.xml)",
                            r"\2",
                            link,
                        )
                        branch_name = branch_name.strip()
                    branches[branch_name] = link.strip()
        return branches

    # @staticmethod
    # def _get_whole_text(soup):
    #     layer = soup.find(
    #         "div",
    #         attrs={
    #             "itemprop": ["articleBody"],
    #             "class": ["tmpt-desk-kon", "ctn", None],
    #         },
    #     )
    #     if layer:
    #         sentences = layer.find_all("p")
    #         texts = []
    #         for sentence in sentences:
    #             avoided_keyword = [
    #                 "Baca Juga",
    #                 "Baca juga",
    #                 "Lihat Juga",
    #                 "Lihat juga",
    #                 "Selanjutnya",
    #                 "Penulis:",
    #                 "Penulis :",
    #                 "Reporter:",
    #             ]
    #             continue_sentence = 0
    #             for keyword in avoided_keyword:
    #                 if keyword in sentence.get_text(" "):
    #                     continue_sentence = 1
    #             if continue_sentence:
    #                 continue
    #             if not sentence.find("div"):
    #                 sentence = preprocess_text(sentence.get_text(" ").strip())
    #                 if sentence:
    #                     texts.append(sentence)
    #         return texts

    @staticmethod
    def _get_whole_text(soup):
        """
        Extract key elements from HTML content
        
        Args:
            html_content (str): The raw HTML content
            
        Returns:
            dict: Dictionary containing extracted metadata
        """        
        # Extract article content (using common article containers)
        article_content = ""
        article_containers = [
            soup.find('article'),
            soup.find(class_=re.compile(r'article|post|content|entry')),
            soup.find(id=re.compile(r'article|post|content|entry')),
            soup.find('div', class_=re.compile(r'article|post|content|entry'))
        ]
        
        # Use the first non-None container found
        container = next((c for c in article_containers if c is not None), None)
        if container:
            # Get all paragraphs from the container
            paragraphs = container.find_all('p')
            article_content = '\n\n'.join([p.get_text().strip() for p in paragraphs])
        else:
            # Fallback: get all paragraphs from the body
            paragraphs = soup.find_all('p')
            article_content = '\n\n'.join([p.get_text().strip() for p in paragraphs])
        
        # Clean up the extracted content
        article_content = re.sub(r'\n{3,}', '\n\n', article_content)  # Replace multiple newlines with double newlines

        return article_content.strip()

    def _get_reporter_from_text(self, soup) -> List[str]:
        reporters = []
        layer = soup.find(
            "div",
            attrs={
                "itemprop": ["articleBody"],
                "class": ["tmpt-desk-kon", "ctn", None],
            },
        )
        if layer:
            sentences = layer.find("p")
            if sentences:
                reporter = sentences.get_text(" ").strip()
                if reporter:
                    for r in reporter.split("|"):
                        r = r.replace("Reporter:", "")
                        r = r.replace("Editor:", "")
                        r = r.strip()
                        reporters.append(r)
                    return reporters
