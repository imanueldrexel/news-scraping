"""
Unit tests for KnowledgeExtractor (Phase 2): JSON parsing, entity processing, the
daily-limit guard, and SYS-19's poison-pill handling -- a failed extraction must
record an attempt (so it eventually drops out of the pending query) instead of being
silently retried forever, and a partial failure mid-article must roll back instead of
leaving some mentions committed.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from newscrawler.core.knowledge_extractor import KnowledgeExtractor
from newscrawler.core.entity_normalizer import EntityNormalizer

_FENCE = chr(96) * 3  # triple backtick


def _make(ds=None, client=None, daily_limit=1400, batch_size=50):
    kx = KnowledgeExtractor.__new__(KnowledgeExtractor)
    kx.ds = ds or _mock_ds()
    kx._client = client
    kx.model_name = "gemini-test"
    kx.daily_limit = daily_limit
    kx.batch_size = batch_size
    kx.normalizer = EntityNormalizer()
    kx.alias_map = {}
    return kx


def _mock_ds():
    """A MagicMock whose atomic_extraction_session() behaves like a real context
    manager (MagicMock supports __enter__/__exit__ automatically)."""
    ds = MagicMock()
    return ds


def _resp(text):
    return SimpleNamespace(text=text)


class TestCallGemini:
    def test_parses_fenced_json(self):
        fenced = _FENCE + "json" + chr(10) + '{"persons": []}' + chr(10) + _FENCE
        client = MagicMock()
        client.models.generate_content.return_value = _resp(fenced)
        kx = _make(client=client)
        assert kx._call_gemini("article") == {"persons": []}

    def test_parses_bare_json(self):
        client = MagicMock()
        client.models.generate_content.return_value = _resp('{"event_type": "earnings"}')
        kx = _make(client=client)
        assert kx._call_gemini("article")["event_type"] == "earnings"

    def test_invalid_json_returns_none(self):
        client = MagicMock()
        client.models.generate_content.return_value = _resp("not json at all")
        kx = _make(client=client)
        assert kx._call_gemini("article") is None

    def test_prose_prefix_before_json_returns_none_without_raising(self):
        """SYS-19's own repro: Gemini prefixing prose before the JSON."""
        client = MagicMock()
        client.models.generate_content.return_value = _resp("Here is the JSON you asked for: {not json")
        kx = _make(client=client)
        assert kx._call_gemini("article") is None

    def test_response_text_none_returns_none_without_raising(self):
        """SYS-19: a safety-blocked response has response.text is None -- must not
        crash with AttributeError on .strip()."""
        client = MagicMock()
        client.models.generate_content.return_value = _resp(None)
        kx = _make(client=client)
        assert kx._call_gemini("article") is None

    def test_api_error_returns_none(self):
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError("503")
        kx = _make(client=client)
        assert kx._call_gemini("article") is None

    def test_requests_json_mime_type(self):
        client = MagicMock()
        client.models.generate_content.return_value = _resp('{}')
        kx = _make(client=client)
        kx._call_gemini("article")
        _, kwargs = client.models.generate_content.call_args
        assert kwargs["config"]["response_mime_type"] == "application/json"


class TestInferSubtype:
    def test_ticker_means_emiten(self):
        assert KnowledgeExtractor._infer_subtype({"ticker": "BBCA"}) == "emiten"

    def test_bank(self):
        assert KnowledgeExtractor._infer_subtype({"type": "Bank BUMN"}) == "bank"

    def test_ministry(self):
        assert KnowledgeExtractor._infer_subtype({"type": "Kementerian Keuangan"}) == "ministry"

    def test_other_none(self):
        assert KnowledgeExtractor._infer_subtype({"type": "startup"}) is None


class TestProcessExtraction:
    def _meta(self):
        return {"article_id": 1, "sitemap_id": 2, "posted_at": 20260101,
                "source": "WARTAEKONOMI", "extracted_text": "Prabowo di Jakarta dari BCA"}

    def test_upserts_all_entity_types(self):
        ds = MagicMock()
        ds.upsert_entity.side_effect = [10, 11, 12]
        ds.get_l1_chunk_id_for_article.return_value = None
        kx = _make(ds=ds)
        extraction = {
            "persons": [{"name": "Prabowo", "role": "Presiden"}],
            "organizations": [{"name": "BCA", "type": "Bank", "ticker": "BBCA"}],
            "locations": [{"name": "Jakarta", "type": "city"}],
            "event_type": "policy",
        }
        session = MagicMock()
        kx._process_extraction(extraction, self._meta(), session)
        types = [c.args[0].entity_type for c in ds.upsert_entity.call_args_list]
        assert types == ["PERSON", "ORGANIZATION", "LOCATION"]
        assert ds.insert_entity_mention.call_count == 3
        # every write must carry the shared session through, not open its own
        for c in ds.upsert_entity.call_args_list + ds.insert_entity_mention.call_args_list:
            assert c.kwargs.get("session") is session

    def test_blank_names_skipped(self):
        ds = MagicMock()
        ds.upsert_entity.return_value = 1
        ds.get_l1_chunk_id_for_article.return_value = None
        kx = _make(ds=ds)
        kx._process_extraction({"persons": [{"name": "  "}]}, self._meta(), MagicMock())
        ds.upsert_entity.assert_not_called()

    def test_non_dict_entities_are_skipped_not_crashed(self):
        """SYS-19: Gemini can return a list of bare strings for one of the three
        entity lists despite still being valid JSON overall -- person.get("name")
        on a str used to raise AttributeError and abort the whole article."""
        ds = MagicMock()
        ds.upsert_entity.return_value = 1
        ds.get_l1_chunk_id_for_article.return_value = None
        kx = _make(ds=ds)
        extraction = {
            "persons": ["Prabowo", "Sri Mulyani"],  # malformed: bare strings
            "organizations": [{"name": "BCA"}],      # well-formed
        }
        kx._process_extraction(extraction, self._meta(), MagicMock())  # must not raise
        assert ds.upsert_entity.call_count == 1
        assert ds.upsert_entity.call_args.args[0].entity_type == "ORGANIZATION"


class TestExtractAllGuards:
    def test_no_client_returns_zero(self):
        assert _make(client=None).extract_all() == 0

    def test_daily_limit_blocks_run(self):
        ds = MagicMock()
        ds.get_today_api_call_count.return_value = 1400
        kx = _make(ds=ds, client=MagicMock(), daily_limit=1400)
        assert kx.extract_all() == 0
        ds.get_articles_pending_extraction.assert_not_called()

    def test_failed_extraction_not_marked_and_attempt_recorded(self):
        ds = MagicMock()
        ds.get_today_api_call_count.return_value = 0
        ds.load_alias_map.return_value = {}
        ds.get_articles_pending_extraction.return_value = [
            {"article_id": 9, "sitemap_id": 2, "posted_at": 20260101,
             "source": "S", "extracted_text": "x"}
        ]
        kx = _make(ds=ds, client=MagicMock())
        kx._call_gemini = lambda text: None
        assert kx.extract_all() == 0
        ds.mark_article_extracted.assert_not_called()
        ds.increment_api_call_count.assert_called()
        # SYS-19: must record the failed attempt so this article eventually drops
        # out of get_articles_pending_extraction instead of retrying forever.
        ds.record_extraction_failure.assert_called_once()
        assert ds.record_extraction_failure.call_args.args[0] == 9

    def test_successful_extraction_marks_article(self):
        ds = MagicMock()
        ds.get_today_api_call_count.return_value = 0
        ds.load_alias_map.return_value = {}
        ds.get_articles_pending_extraction.return_value = [
            {"article_id": 9, "sitemap_id": 2, "posted_at": 20260101,
             "source": "S", "extracted_text": "x"}
        ]
        ds.upsert_entity.return_value = 1
        ds.get_l1_chunk_id_for_article.return_value = None
        kx = _make(ds=ds, client=MagicMock())
        kx._call_gemini = lambda text: {"persons": [{"name": "Prabowo"}], "event_type": "x"}
        assert kx.extract_all() == 1
        ds.mark_article_extracted.assert_called_once()
        assert ds.mark_article_extracted.call_args.args[0] == 9
        assert ds.mark_article_extracted.call_args.kwargs.get("session") is not None
        ds.record_extraction_failure.assert_not_called()

    def test_process_extraction_raising_records_failure_and_rolls_back(self):
        """SYS-19: a mid-article crash (e.g. a malformed entity that still slips
        past _valid_dicts, or a DB error) must record the attempt via the outer
        except, and mark_article_extracted must not have been called."""
        ds = MagicMock()
        ds.get_today_api_call_count.return_value = 0
        ds.load_alias_map.return_value = {}
        ds.get_articles_pending_extraction.return_value = [
            {"article_id": 9, "sitemap_id": 2, "posted_at": 20260101,
             "source": "S", "extracted_text": "x"}
        ]
        ds.upsert_entity.side_effect = RuntimeError("DB exploded")
        kx = _make(ds=ds, client=MagicMock())
        kx._call_gemini = lambda text: {"persons": [{"name": "Prabowo"}]}
        assert kx.extract_all() == 0
        ds.mark_article_extracted.assert_not_called()
        ds.record_extraction_failure.assert_called_once()
        assert ds.record_extraction_failure.call_args.args[0] == 9
        assert "DB exploded" in ds.record_extraction_failure.call_args.args[1]
