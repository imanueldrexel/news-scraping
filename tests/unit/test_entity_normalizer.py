"""Unit tests for EntityNormalizer (Phase 2 entity KB)."""
from newscrawler.core.entity_normalizer import EntityNormalizer

N = EntityNormalizer()


class TestNormalize:
    def test_lowercases(self):
        assert N.normalize("Bank Central Asia") == "bank central asia"

    def test_strips_punctuation_keeps_hyphen(self):
        assert N.normalize("PT. Bank-Mandiri, Tbk!") == "pt bank-mandiri tbk"

    def test_collapses_whitespace(self):
        assert N.normalize("  Perry   Warjiyo  ") == "perry warjiyo"

    def test_empty(self):
        assert N.normalize("") == ""


class TestResolveAlias:
    def test_hit(self):
        alias_map = {"bca": 7}
        assert N.resolve_alias("BCA", alias_map) == 7

    def test_miss_returns_none(self):
        assert N.resolve_alias("Unknown Co", {"bca": 7}) is None


class TestContextSnippet:
    def test_found_centers_on_entity(self):
        text = "x" * 300 + " Prabowo Subianto " + "y" * 300
        snip = N.extract_context_snippet(text, "Prabowo Subianto", window=50)
        assert "Prabowo Subianto" in snip
        assert snip.startswith("...") and snip.endswith("...")

    def test_not_found_returns_none(self):
        assert N.extract_context_snippet("some text", "Nonexistent") is None

    def test_case_insensitive_match(self):
        assert N.extract_context_snippet("the BANK indonesia rate", "bank indonesia") is not None
