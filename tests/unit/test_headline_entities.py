"""SYS-88 (#249): headlines arrive HTML-escaped from some sitemaps -- once
("Jatim &amp; Kalsel") or twice ("&amp;amp;", DETIK) -- and were stored and shown
that way. A headline is unescaped where it enters (the sitemap entry, the page
title), and where the newsletter reads the rows stored before the fix."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from bs4 import BeautifulSoup

from newscrawler.core.newsletter_generator import NewsletterGenerator
from newscrawler.core.utils.utils import unescape_headline
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_newsletter_data_source import (
    SQLAlchemyNewsletterDataSource,
)
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler


@pytest.mark.parametrize("stored,shown", [
    ("Jatim &amp;amp; Kalsel", "Jatim & Kalsel"),                    # escaped twice
    ("Buka Ruang Berkarya &amp; Kemandirian", "Buka Ruang Berkarya & Kemandirian"),
    ("D&#039;Masiv &quot;Cinta&quot;", "D'Masiv \"Cinta\""),
    ("Rp&nbsp;2 juta", "Rp 2 juta"),
    ("Harga &#163;10", "Harga £10"),
    ("AT&T dan B&B", "AT&T dan B&B"),                                 # a bare & is text, not an entity
    ("", ""), (None, None),
])
def test_unescape_headline(stored, shown):
    assert unescape_headline(stored) == shown


def test_a_sitemap_entry_is_stored_unescaped():
    entry = dict(headline="Jatim &amp;amp; Kalsel, D&#039;Masiv", link="http://ex.com/a", sources="DETIK",
                 category="news", timestamp=datetime(2026, 10, 4, tzinfo=timezone.utc), keywords=None)
    assert Crawler._get_sitemap(entry).headline == "Jatim & Kalsel, D'Masiv"


def test_a_page_title_is_unescaped():
    soup = BeautifulSoup('<meta property="og:title" content="Jatim &amp;amp; Kalsel">', "html.parser")
    assert Crawler._get_page_title(soup) == "Jatim & Kalsel"


def test_the_newsletter_reads_stored_rows_unescaped():
    client, session = MagicMock(), MagicMock()
    client.get_session.return_value.__enter__.return_value = session
    session.execute.return_value.fetchall.return_value = [SimpleNamespace(
        sitemap_id=1, headline="Buka Ruang Berkarya &amp; Kemandirian", sources="PERTAMINA", category="news",
        link="http://x/1", posted_at=20261003, topic="energy", l1_text="isi")]
    (article,) = SQLAlchemyNewsletterDataSource(client).get_articles_for_date(20261003)
    assert article["headline"] == "Buka Ruang Berkarya & Kemandirian"
    label = NewsletterGenerator._link_label({"source": "KONTAN", "headline": article["headline"], "link": "x"})
    assert label == "Kontan: Buka Ruang Berkarya & Kemandirian"
