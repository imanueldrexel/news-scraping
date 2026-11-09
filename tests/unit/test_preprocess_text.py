import pytest
from newscrawler.core.utils.utils import preprocess_text


class TestPreprocessText:
    def test_PT01_strips_whitespace(self):
        assert preprocess_text("  hello  ") == "hello"

    def test_PT02_removes_newlines(self):
        assert preprocess_text("hello\nworld") == "helloworld"

    def test_PT03_collapses_multiple_spaces(self):
        assert preprocess_text("hello   world") == "hello world"

    def test_PT04_replaces_nbsp(self):
        assert preprocess_text("hello\xa0world") == "hello world"

    def test_PT05_double_nbsp_collapsed(self):
        assert preprocess_text("hello\xa0\xa0world") == "hello world"

    def test_PT06_strips_and_removes_newlines(self):
        assert preprocess_text("\n\n  hello\n\n") == "hello"

    def test_PT07_empty_string(self):
        assert preprocess_text("") == ""

    def test_PT08_double_nbsp_before_and_after_regex(self):
        #   is replaced BEFORE space-collapse, so double NBSP -> two spaces -> one space
        result = preprocess_text("hello\xa0\xa0world")
        assert result == "hello world"
