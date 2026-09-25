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

    def test_an_unknown_name_raises_before_any_query_runs(self):
        class _Client:
            def get_session(self):
                raise AssertionError("a query was attempted for an unvalidated website name")

        with pytest.raises(ValueError):
            SQLAlchemySitemapDataSource(_Client()).load_all_sitemaps(website="KOMPAS' OR '1'='1", n_limit=5)
