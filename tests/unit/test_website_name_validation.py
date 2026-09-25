"""DBT-12 (#47): the website name is bound, not interpolated -- and validated.

`load_all_sitemaps` built its predicate with `website = f"'{website}'"`, and the
value arrives from `event["website"]` / `CRAWL_WEBSITES`, i.e. from a scheduler
config an operator edits. The audit's proof:

    ds.load_all_sitemaps(website="KOMPAS' OR '1'='1", n_limit=5)
    -> sources returned: ['WARTAEKONOMI']     # rows from another source came back
"""
import pytest

from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_sitemap_data_source import (
    SQLAlchemySitemapDataSource,
    validate_website_name,
)


class TestValidateWebsiteName:
    def test_accepts_every_registered_name(self):
        for w in WebsiteName:
            assert validate_website_name(w.value) == w.value

    def test_strips_surrounding_whitespace(self):
        assert validate_website_name("  KOMPAS  ") == "KOMPAS"

    @pytest.mark.parametrize("bad", [
        "KOMPAS' OR '1'='1",          # the audit's payload
        "KOMPAS'; DROP TABLE sitemaps; --",
        "kompas",                      # case matters: the column stores upper-case
        "NOPE", "", "   ", None,
    ])
    def test_rejects_anything_else(self, bad):
        with pytest.raises(ValueError):
            validate_website_name(bad)

    def test_the_error_names_the_offender_and_the_known_set(self):
        with pytest.raises(ValueError) as e:
            validate_website_name("NOPE")
        assert "NOPE" in str(e.value) and "KOMPAS" in str(e.value)


class TestLoadAllSitemapsUsesBoundParameters:
    def test_no_runtime_value_is_interpolated_into_the_sql(self):
        """The query text must carry placeholders, not values."""
        captured = {}

        class _Session:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def execute(self, statement, params=None):
                captured["sql"] = str(statement)
                captured["params"] = params
                return []

        class _Client:
            def get_session(self): return _Session()

        SQLAlchemySitemapDataSource(_Client()).load_all_sitemaps(website="KOMPAS", n_limit=7)
        sql, params = captured["sql"], captured["params"]
        for placeholder in (":website", ":cooldown_days", ":max_fetch_failures", ":n_limit"):
            assert placeholder in sql, placeholder
        assert "'KOMPAS'" not in sql, "the website name is still interpolated"
        assert params["website"] == "KOMPAS" and params["n_limit"] == 7
        assert isinstance(params["cooldown_days"], int) and isinstance(params["max_fetch_failures"], int)

    def test_an_injection_payload_is_bound_not_interpolated(self):
        """The datasource deliberately does NOT validate: it is also driven by
        integration tests and ad-hoc tooling with synthetic source names, and
        validating domain names in a low-level datasource couples it to the enum.
        The injection fix is the binding -- the payload becomes a literal value
        that matches no row, not a predicate."""
        captured = {}

        class _Session:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def execute(self, statement, params=None):
                captured["sql"], captured["params"] = str(statement), params
                return []

        class _Client:
            def get_session(self): return _Session()

        payload = "KOMPAS' OR '1'='1"
        SQLAlchemySitemapDataSource(_Client()).load_all_sitemaps(website=payload, n_limit=5)
        assert captured["params"]["website"] == payload
        assert "OR '1'='1" not in captured["sql"], "the payload reached the SQL text"

    def test_the_dispatch_boundary_rejects_an_unknown_name(self):
        """DBT-12: this is where operator input enters -- the event's website list
        or CRAWL_WEBSITES. A typo used to reach load_all_sitemaps, return 0 rows,
        and only crash later on `NoneType has no batch_crawling_details`."""
        from unittest.mock import patch
        from newscrawler.application.api.lambda_function import lambda_handler

        with patch.object(lambda_handler, "init_crawler") as init:
            with pytest.raises(ValueError, match="unknown website name"):
                lambda_handler.process_event({"task": "sitemap", "website": "KOMPAS,NOPE"}, None)
            init.return_value.crawl_websites_in_batch.assert_not_called()

    def test_the_dispatch_boundary_accepts_a_valid_list(self):
        from unittest.mock import patch
        from newscrawler.application.api.lambda_function import lambda_handler

        with patch.object(lambda_handler, "init_crawler") as init:
            lambda_handler.process_event({"task": "sitemap", "website": "KOMPAS, DETIK"}, None)
        init.return_value.crawl_websites_in_batch.assert_called_once_with(
            website_names=["KOMPAS", "DETIK"], task="sitemap")
