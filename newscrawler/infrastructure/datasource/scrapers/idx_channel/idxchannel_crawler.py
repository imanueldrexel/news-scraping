import logging
import re
from typing import List, Dict

from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.core.utils.utils import (
    preprocess_text,
)

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class IdxChannelCrawler(Crawler):
    # SRC-45 (#155): IDXCHANNEL files ordinary reporting under two sections
    # named after a medium. `foto` is full articles -- "Komisi V DPR Setujui
    # Anggaran Kemendes PDT Rp2,785 Triliun untuk 2027" (597 chars), "Cilandak
    # Timur Jaksel Dilanda Kekeringan, BPBD Distribusikan Air Bersih" (842) --
    # and `infografis` is macro-policy news ("Utang Baru Rp781,86 Triliun Masuk
    # RAPBN 2026", "China Larang Perusahaan Gunakan Chip Nvidia"). Both
    # measured through this crawler's own _get_whole_text on 2026-09-23.
    #
    # `video` is NOT here and is dropped: its pages are captions on a player,
    # 205 and 198 chars, at or below MIN_ARTICLE_CHARS. This is the half of
    # SRC-35's "video/foto on IDXCHANNEL are finance posts with bodies" note
    # that re-measurement did not support.
    #
    # `foto` is the load-bearing entry -- it is in SOFT_BRANCH_WORDS and would
    # otherwise drop. `infografis` is not in the vocabulary today and is listed
    # defensively, so that adding it later on another source's evidence cannot
    # silently take this desk with it.
    SOFT_BRANCH_EXCEPTIONS = frozenset({"foto", "infografis"})
    def __init__(self):
        super(IdxChannelCrawler, self).__init__()
        self.website_name = WebsiteName.IDXCHANNEL.value
        self.website_url = URL.IDXCHANNEL.value

    @staticmethod
    def _get_branches(soup) -> Dict[str, str]:
        branches = {}
        sitemaps = soup.find_all("sitemap")
        for sitemap in sitemaps:
            link = sitemap.find("loc")
            if link:
                link = link.get_text(" ").strip()
                if link:
                    branch_name = re.sub(
                        r"(https://www.idxchannel.com/)(.*)(/sitemap.xml)", r"\2", link
                    )
                    branch_name = branch_name.strip()
                    branches[branch_name] = link.strip()
        return branches

    @staticmethod
    def _get_whole_text(soup) -> List[str]:
        article = soup.find("div", {"class": "content"})
        if article:
            texts = []
            sentences = article.find_all("p")
            for sentence in sentences:
                sentence = preprocess_text(sentence.get_text(" ").strip())
                texts.append(sentence)
            return texts

    def _get_reporter_from_text(self, soup) -> List[str]:
        # SRC-10 (#65): the byline is an <a class="text-body--2 creator"> tag, not
        # a <div>. `soup.find("div", {"class": "text-body--2"})` matched the
        # timestamp <div> that shares the "text-body--2" class instead -- confirmed
        # live across 5 categories (banking/economics/news/syariah/milenomic),
        # "creator" uniquely identifies the byline in every case.
        reporters = []
        layer = soup.find(class_="creator")
        if layer:
            reporter = layer.get_text(" ").strip()
            if reporter:
                reporters.append(reporter)
        return reporters
