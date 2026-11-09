"""SYS-52 (#178): the scheduled worker died natively in lxml while PIKIRANRAKYAT's
pages all went through the trafilatura fallback on up to 32 fetch threads. The
fallbacks' lxml parse is serialised; the fetch is not."""
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import ModuleType

from bs4 import BeautifulSoup

from newscrawler.infrastructure.datasource.scrapers import crawler as crawler_mod
from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler


class _Concurrency:
    def __init__(self):
        self.now = self.peak = 0
        self.lock = threading.Lock()

    def enter(self):
        with self.lock:
            self.now += 1
            self.peak = max(self.peak, self.now)

    def leave(self):
        with self.lock:
            self.now -= 1


def test_trafilatura_extract_never_runs_on_two_threads_at_once(monkeypatch):
    seen = _Concurrency()

    def extract(html):
        seen.enter()
        time.sleep(0.01)
        seen.leave()
        return "Paragraf satu.\n\nParagraf dua."

    fake = ModuleType("trafilatura")
    fake.extract = extract
    monkeypatch.setitem(sys.modules, "trafilatura", fake)
    soup = BeautifulSoup("<html><body><p>x</p></body></html>", "html.parser")
    with ThreadPoolExecutor(max_workers=16) as ex:
        results = list(ex.map(lambda _: Crawler._trafilatura_fallback(soup), range(64)))
    assert all(r == ["Paragraf satu.", "Paragraf dua."] for r in results)
    assert seen.peak == 1, "trafilatura.extract ran on %d threads at once" % seen.peak


def test_newspaper_downloads_in_parallel_but_parses_one_at_a_time(monkeypatch):
    downloads, parses = _Concurrency(), _Concurrency()

    class _Article:
        text = "Isi artikel."

        def __init__(self, url):
            pass

        def download(self):
            downloads.enter()
            time.sleep(0.02)
            downloads.leave()

        def parse(self):
            parses.enter()
            time.sleep(0.01)
            parses.leave()

    monkeypatch.setattr(crawler_mod, "Article", _Article)
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda i: Crawler._newspaper_fallback("http://e.com/%d" % i), range(32)))
    assert parses.peak == 1
    assert downloads.peak > 1, "the network fetch must stay parallel"
