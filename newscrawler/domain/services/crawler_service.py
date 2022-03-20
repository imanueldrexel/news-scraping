from abc import abstractmethod

from newscrawler.domain.entities.extraction.extracted_data import ExtractedData


class CrawlerService:
    @abstractmethod
    def crawl_url(self, website_name: str) -> ExtractedData:
        raise NotImplementedError
