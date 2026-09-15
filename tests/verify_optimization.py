
import sys
import os
sys.path.append(os.getcwd())

from unittest.mock import MagicMock
from newscrawler.application.api.crawler_api import CrawlerAPI

def test_optimization():
    # Mock Service
    mock_service = MagicMock()
    
    # Init API
    api = CrawlerAPI(mock_service)
    
    # Setup mock return
    mock_sitemaps = ["sitemap1", "sitemap2"]
    mock_service.crawl_sitemaps.return_value = mock_sitemaps

    # Call with task="all"
    print("Testing task='all'...")
    api.crawl_website("TEST_SITE", "all")
    
    # Verify calls
    mock_service.crawl_sitemaps.assert_called_once_with(website_name="TEST_SITE")
    mock_service.crawl_newsdetails.assert_called_once_with(website_name="TEST_SITE", specific_sitemaps=mock_sitemaps)
    
    print("SUCCESS: Sitemaps passed from crawl_sitemaps to crawl_newsdetails.")

if __name__ == "__main__":
    test_optimization()
