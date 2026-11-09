"""SRC-29 (#111): keep each INEWS article's one live copy, retire its mirror
duplicates, and never infer from a failure that is not a per-URL fact."""
import importlib.util
import os
from types import SimpleNamespace

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "retire_inews_mirror_duplicates.py",
)
_spec = importlib.util.spec_from_file_location("retire_inews_mirror_duplicates", _SCRIPT)
rim = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rim)


def row(sid, host, aid="716996", slug="hutan-bambu-di-tenjo-bogor-terbakar", saved=False):
    return SimpleNamespace(sitemap_id=sid, link="https://%s.inews.id/read/%s/%s?page=all" % (host, aid, slug),
                           fetch_failures=0, has_article=saved)


class Fetch:
    """Live only for `live` hosts; `errors` maps host -> a non-404 reason."""

    def __init__(self, live=(), errors=None):
        self.live, self.errors, self.calls = set(live), errors or {}, []

    def __call__(self, link):
        host = rim.parse(link)[0]
        self.calls.append(host)
        if host in self.errors:
            return self.errors[host]
        return None if host in self.live else "HTTP 404"


def test_the_live_copy_is_kept_and_every_other_copy_retired():
    copies = [row(1, "gowa"), row(2, "bogor"), row(3, "subang")]
    p = rim.plan_for_id("716996", copies, Fetch(live={"bogor"}))
    assert p["keep"] == 2 and sorted(p["retire"]) == [1, 3] and p["status"] == "found"


def test_a_host_named_in_the_slug_is_tried_first_so_it_costs_one_fetch():
    copies = [row(1, "gowa"), row(2, "ambon"), row(3, "bogor")]
    f = Fetch(live={"bogor"})
    p = rim.plan_for_id("716996", copies, f)
    assert f.calls == ["bogor"] and p["fetches"] == 1


def test_a_copy_that_already_produced_an_article_is_the_keeper_without_fetching():
    copies = [row(1, "gowa"), row(2, "mamuju", saved=True), row(3, "subang")]
    f = Fetch()
    p = rim.plan_for_id("717055", copies, f)
    assert f.calls == [] and p["keep"] == 2 and sorted(p["retire"]) == [1, 3]


def test_a_non_per_url_failure_leaves_the_whole_id_alone():
    """A timeout or 403 says nothing about the URL; nothing may be inferred."""
    copies = [row(1, "ambon"), row(2, "bogor"), row(3, "gowa")]
    p = rim.plan_for_id("716996", copies, Fetch(live={"gowa"}, errors={"ambon": "ReadTimeout after 5 retries"}))
    assert p["status"] == "unresolved" and p["retire"] == [] and p["keep"] is None


def test_no_live_copy_retires_every_copy():
    copies = [row(1, "gowa"), row(2, "bogor")]
    p = rim.plan_for_id("716996", copies, Fetch())
    assert p["status"] == "none_live" and sorted(p["retire"]) == [1, 2] and p["fetches"] == 2


def test_only_regional_article_links_are_parsed():
    assert rim.parse("https://bogor.inews.id/read/716996/x?page=all") == ("bogor", "716996", "x")
    assert rim.parse("https://www.inews.id/read/716996/x") is None
    assert rim.parse("https://www.inews.id/finance/bisnis/x") is None
    assert rim.parse("https://ramadan.inews.id/resep?page=all") is None


def test_build_plan_groups_by_article_id():
    rows = [row(1, "gowa", aid="1"), row(2, "bogor", aid="1"), row(3, "gowa", aid="2", slug="gowa-news")]
    plans = {p["id"]: p for p in rim.build_plan(rows, Fetch(live={"bogor", "gowa"}), workers=1)}
    assert plans["1"]["keep"] in (1, 2) and len(plans["1"]["retire"]) == 1
    assert plans["2"]["keep"] == 3 and plans["2"]["retire"] == []


def test_the_markers_match_the_service():
    from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl
    assert tuple(rim.PER_URL_MARKERS) == tuple(CrawlerServiceImpl.PER_URL_FAILURE_MARKERS)
