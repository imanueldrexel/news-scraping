"""
SYS-08: NewsDetailsModel.reporter was typed `List[str] = None` -- a Python default
value, not an Optional type. Pydantic v2 rejects an actual None for a non-Optional
field, so any crawler whose _get_reporter_from_text returned None (the unenforced
abstract base method's implicit return -- VIVA never overrode it) crashed model
construction inside save_newsdetails' per-row try/except on every single article,
forever, with 0 visible symptom beyond a per-row log line.
"""
import pytest
from pydantic import ValidationError

from newscrawler.infrastructure.datasource.dataflow.model.news_details_model import (
    NewsDetailsModel,
)


class TestReporterAcceptsNone:
    def test_reporter_none_no_longer_raises(self):
        model = NewsDetailsModel(sitemap_id=1, extracted_text=["text"], reporter=None)
        assert model.reporter is None

    def test_reporter_omitted_defaults_to_none_without_raising(self):
        model = NewsDetailsModel(sitemap_id=1, extracted_text=["text"])
        assert model.reporter is None

    def test_reporter_empty_list_still_works(self):
        model = NewsDetailsModel(sitemap_id=1, extracted_text=["text"], reporter=[])
        assert model.reporter == []

    def test_reporter_populated_list_still_works(self):
        model = NewsDetailsModel(sitemap_id=1, extracted_text=["text"], reporter=["Jane Doe"])
        assert model.reporter == ["Jane Doe"]

    def test_reporter_wrong_type_still_rejected(self):
        """Optional[List[str]] should still reject a non-list, non-None value --
        confirms the fix widened nullability, not type-checking generally."""
        with pytest.raises(ValidationError):
            NewsDetailsModel(sitemap_id=1, extracted_text=["text"], reporter="not a list")
