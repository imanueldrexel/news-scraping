import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Init path to allow imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl
from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO

class TestCrawlerServiceImpl(unittest.TestCase):
    def setUp(self):
        # Start patching the class
        self.top_patcher = patch('newscrawler.domain.services.crawler_service_impl.SemanticImportanceFilter')
        self.MockFilterClass = self.top_patcher.start()
        
        # Mock Repositories and Dependencies
        self.mock_repo = MagicMock()
        
        # When Service is initialized, it will call MockFilterClass(...)
        self.service = CrawlerServiceImpl(data_flow_repo=self.mock_repo)
        
        # The service stores the instance returned by the class
        self.mock_filter_instance = self.service.semantic_filter
        
        # Mock the Crawler DI container
        self.mock_crawler = MagicMock()
        self.service.crawler_dict = {"TEST_SITE": self.mock_crawler}

    def tearDown(self):
        self.top_patcher.stop()

    def test_crawl_newsdetails_filtering(self):
        # --- Arrange ---
        website_name = "TEST_SITE"
        
        # 1. Mock 'load_sitemap_data' to return 1 dummy sitemap item (forces 1 batch)
        self.mock_repo.load_sitemap_data.return_value = [MagicMock(sitemap_id=1, headline="Test")]
        
        # 2. Mock 'batch_crawling_details' to return 2 scraped articles
        article_important = NewsDetailsDTO(
            sitemap_id=1,
            extracted_text=["Important economic news."],
            meta_data={"title": "Economy Booms"},
            reporter=["Reporter A"]
        )
        article_unimportant = NewsDetailsDTO(
            sitemap_id=2,
            extracted_text=["Celebrity gossip."],
            meta_data={"title": "Gossip"},
            reporter=["Reporter B"]
        )
        self.mock_crawler.batch_crawling_details.return_value = [article_important, article_unimportant]

        # 3. Mock Semantic Filter logic on the INSTANCE
        def side_effect_is_important(text):
            return "Economy" in text
            
        self.mock_filter_instance.is_important.side_effect = side_effect_is_important

        # 4. Mock 'save_embedding_data' to return successful IDs
        self.mock_repo.save_chunk_data.return_value = [1]

        # --- Act ---
        self.service.crawl_newsdetails(website_name)

        # --- Assert ---
        # 1. Verify filtering
        self.assertEqual(self.mock_filter_instance.is_important.call_count, 2)
        
        # 2. Verify 'save_embedding_data' was called ONLY with the important article
        self.mock_repo.save_chunk_data.assert_called()
        args, _ = self.mock_repo.save_chunk_data.call_args
        saved_list = args[0]
        # save_chunk_data receives ChunkDTO objects (L1 + L2 per article), not articles.
        # Assert all chunks belong to the important article (sitemap_id=1).
        self.assertGreater(len(saved_list), 0, "Expected at least one chunk")
        for chunk in saved_list:
            self.assertEqual(chunk.sitemap_id, 1, f"Chunk sitemap_id should be 1, got {chunk.sitemap_id}") 
        
        # 3. Verify 'save_newsdetails_data' was called ONLY with the important embedded article
        self.mock_repo.save_newsdetails_data.assert_called()
        args_saved, _ = self.mock_repo.save_newsdetails_data.call_args
        saved_details_list = args_saved[0]
        self.assertEqual(len(saved_details_list), 1)
        self.assertEqual(saved_details_list[0].sitemap_id, 1)

        # 4. Bug B: every extracted sitemap (important AND filtered-out) is marked
        #    attempted so it is not re-crawled until the cooldown elapses.
        self.mock_repo.mark_sitemaps_attempted.assert_called()
        marked = self.mock_repo.mark_sitemaps_attempted.call_args[0][0]
        self.assertEqual(set(marked), {1, 2})

    def test_crawl_newsdetails_already_embedded_still_saves_article(self):
        """Bug A end-to-end: when the FAISS layer reports an article as already embedded,
        save_chunk_data still returns its sitemap_id, so the article must still be saved."""
        website_name = "TEST_SITE"
        self.mock_repo.load_sitemap_data.return_value = [MagicMock(sitemap_id=99, headline="Test")]

        already_embedded = NewsDetailsDTO(
            sitemap_id=99,
            extracted_text=["Important economic news about banking."],
            meta_data={"title": "Bank Indonesia raises rate"},
            reporter=["Reporter X"],
        )
        self.mock_crawler.batch_crawling_details.return_value = [already_embedded]
        self.mock_filter_instance.is_important.return_value = True

        # FAISS dedup hit: save_chunk_data returns the sitemap_id (Bug A fix behaviour)
        self.mock_repo.save_chunk_data.return_value = [99]

        self.service.crawl_newsdetails(website_name)

        self.mock_repo.save_newsdetails_data.assert_called()
        saved = self.mock_repo.save_newsdetails_data.call_args[0][0]
        self.assertEqual([n.sitemap_id for n in saved], [99])

        print("\nTest crawl_newsdetails_filtering PASSED: Successfully filtered 1 unimportant article.")

    def test_crawl_newsdetails_loads_from_db_when_no_specific_sitemaps(self):
        """
        Scenario 1: When crawl_newsdetails is called directly (without specific_sitemaps),
        it should call load_sitemap_data with limit=1000 to get latest unscraped articles.
        """
        # --- Arrange ---
        website_name = "TEST_SITE"
        
        # Mock load_sitemap_data to return dummy sitemaps
        mock_sitemaps = [MagicMock(sitemap_id=i) for i in range(1, 6)]  # 5 sitemaps
        self.mock_repo.load_sitemap_data.return_value = mock_sitemaps
        
        # Mock crawler to return empty (we just want to verify load_sitemap_data call)
        self.mock_crawler.batch_crawling_details.return_value = []
        
        # --- Act ---
        self.service.crawl_newsdetails(website_name)
        
        # --- Assert ---
        # 1. Verify load_sitemap_data was called with correct parameters
        self.mock_repo.load_sitemap_data.assert_called_once()
        call_args = self.mock_repo.load_sitemap_data.call_args
        
        # Check that it was called with the website name and limit 1000
        self.assertEqual(call_args.kwargs.get('website') or call_args[1].get('website'), website_name)
        limit_used = call_args.kwargs.get('n_limit') or call_args[1].get('n_limit')
        self.assertEqual(limit_used, 1000, f"Expected n_limit=1000, got {limit_used}")
        
        # 2. Verify crawler's batch_crawling_details was called with the loaded sitemaps
        self.mock_crawler.batch_crawling_details.assert_called()

        print("\nTest crawl_newsdetails_loads_from_db_when_no_specific_sitemaps PASSED.")

    def test_crawl_newsdetails_uses_specific_sitemaps_when_provided(self):
        """
        Scenario 2: When crawl_newsdetails is called with specific_sitemaps,
        it should use those directly and NOT call load_sitemap_data.
        """
        # --- Arrange ---
        website_name = "TEST_SITE"
        
        # Create specific sitemaps to pass
        from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
        from datetime import datetime
        
        specific_sitemaps = [
            SitemapDTO(
                headline="Test 1",
                link="http://example.com/1",
                sources="TEST_SITE",
                sitemap_id=101
            ),
            SitemapDTO(
                headline="Test 2",
                link="http://example.com/2",
                sources="TEST_SITE",
                sitemap_id=102
            )
        ]
        
        # Mock crawler to return empty (we just want to verify specific_sitemaps is used)
        self.mock_crawler.batch_crawling_details.return_value = []
        
        # --- Act ---
        self.service.crawl_newsdetails(website_name, specific_sitemaps=specific_sitemaps)
        
        # --- Assert ---
        # 1. Verify load_sitemap_data was NOT called
        self.mock_repo.load_sitemap_data.assert_not_called()
        
        # 2. Verify crawler's batch_crawling_details was called with the specific sitemaps
        #    Due to batching, it may be called multiple times. Collect all sitemaps processed.
        self.mock_crawler.batch_crawling_details.assert_called()
        
        # Collect all news items across all batch calls
        all_processed_sitemaps = []
        for call in self.mock_crawler.batch_crawling_details.call_args_list:
            news_arg = call.kwargs.get('news') or (call[1].get('news') if len(call) > 1 else call[0][0])
            all_processed_sitemaps.extend(news_arg)
        
        # Since we passed 2 sitemaps, both should have been processed across all batches
        self.assertEqual(len(all_processed_sitemaps), 2, 
                         f"Expected 2 total sitemaps processed, got {len(all_processed_sitemaps)}")
        processed_ids = [s.sitemap_id for s in all_processed_sitemaps]
        self.assertIn(101, processed_ids)
        self.assertIn(102, processed_ids)

        print("\nTest crawl_newsdetails_uses_specific_sitemaps_when_provided PASSED.")

if __name__ == '__main__':
    unittest.main()
