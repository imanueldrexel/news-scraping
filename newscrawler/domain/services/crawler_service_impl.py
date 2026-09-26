import collections
import dataclasses
import logging
import math
from typing import List, Optional
from newscrawler.core.chunker import HierarchicalChunker
from newscrawler.core.crawler_dict_list import CRAWLER_DICT
from newscrawler.core.crawler_url_list import WEB_URL_DICT
from newscrawler.core.constants import SITEMAP_SOURCE_FAILURE_MIN, SITEMAP_SOURCE_FAILURE_RATIO, SOFT_THRESHOLD
from newscrawler.core.importance_filter import SemanticImportanceFilter, category_gate
from newscrawler.core.importance_probe import build_check_text
from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.domain.repositories.data_flow_repository.data_flow_repository import (
    DataFlowRepository,
)
from newscrawler.domain.services.crawler_service import CrawlerService

from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class CrawlerServiceImpl(CrawlerService):
    def __init__(
        self,
        data_flow_repo: DataFlowRepository,
        chunker: Optional[HierarchicalChunker] = None,
        limit: int = 1000,
    ):
        self.crawler_dict = CRAWLER_DICT
        self.web_url_dict = WEB_URL_DICT
        self.data_flow_repo = data_flow_repo
        self.newsdetails_limit = limit
        self.chunker = chunker or HierarchicalChunker()

        # SYS-37: the probe (newscrawler/core/models/) and the encoder its
        # sidecar names. A missing or mismatched artifact raises here -- the
        # service must not start with a filter that accepts or rejects all.
        logger.info("Initializing Semantic Filter...")
        self.semantic_filter = SemanticImportanceFilter(soft_threshold=SOFT_THRESHOLD)

    def crawl_sitemaps(self, website_name: str) -> List[SitemapDTO]:
        log_id = self.data_flow_repo.log_crawl_start(website_name, "sitemap")
        try:
            web_crawler: Crawler = self.crawler_dict.get(website_name)
            raw_sitemaps  = web_crawler.get_news_in_bulk()
            sitemaps_dtos = web_crawler.batch_crawling_sitemap(raw_sitemaps, website_name)
            # SYS-32: entries with no usable publication date (neither
            # news:publication_date nor lastmod) never became a SitemapDTO --
            # captured before save_scraped_data replaces sitemaps_dtos below.
            skipped_no_date = getattr(sitemaps_dtos, "skipped_no_date", 0)

            # SYS-07: log the number of newly-inserted rows, not "entries listed" --
            # a healthy source re-lists most of its sitemap on every run, so the old
            # len(sitemaps_dtos) told you nothing about whether new articles showed up.
            new_count = 0
            if sitemaps_dtos:
                sitemaps_dtos = self.save_scraped_data(sitemaps_dtos)
                new_count = getattr(sitemaps_dtos, "new_count", len(sitemaps_dtos))
                logger.info(f"Saved {len(sitemaps_dtos)} sitemaps. IDs populated.")
            if skipped_no_date:
                logger.warning(f"{website_name}: {skipped_no_date} sitemap entries skipped (no publication date)")

            self.data_flow_repo.log_crawl_complete(log_id, new_count)
            return sitemaps_dtos
        except Exception as e:
            self.data_flow_repo.log_crawl_failed(log_id, str(e))
            raise

    def crawl_newsdetails(self, website_name: str, specific_sitemaps: List[SitemapDTO] = None):
        log_id = self.data_flow_repo.log_crawl_start(website_name, "full_text")
        # OPS-16 (c): `_record_fetch_failures` decides whether this run was a
        # source-wide failure, and that verdict has to outlive the log line. The
        # crawl_log row for such a run used to read status='completed',
        # article_count=0, error_msg=NULL -- byte-identical to "1,000 pages
        # fetched fine, all off-topic" -- and logging.basicConfig() has no file
        # handler, so under Task Scheduler the ERROR line was gone too.
        self._source_failure_verdict = None
        try:
            total_saved = self._crawl_newsdetails_inner(website_name, specific_sitemaps)
            self.data_flow_repo.log_crawl_complete(log_id, total_saved, note=self._source_failure_verdict)
        except Exception as e:
            self.data_flow_repo.log_crawl_failed(log_id, str(e))
            raise

    def _crawl_newsdetails_inner(self, website_name: str, specific_sitemaps: List[SitemapDTO] = None) -> int:
        # DBT-10 (#45): one vector-store save per source run, not one per batch.
        with self.data_flow_repo.deferred_embeddings(website_name):
            return self._crawl_newsdetails_batches(website_name, specific_sitemaps)

    def _crawl_newsdetails_batches(self, website_name: str, specific_sitemaps: List[SitemapDTO] = None) -> int:
        web_crawler: Crawler = self.crawler_dict.get(website_name)
        if specific_sitemaps:
            target_news = specific_sitemaps
        else:
            target_news = self.data_flow_repo.load_sitemap_data(website=website_name, n_limit=self.newsdetails_limit)

        logger.info(f"Found {len(target_news)} news to crawl for {website_name}")

        # SYS-50 (#165): `deny` is decided from sitemaps.category alone, which is
        # known before the page is fetched, so a denied row is settled here
        # instead of costing a full fetch + extraction just to be rejected on
        # information we already had (MEDIAINDONESIA's queue was 48% denied).
        # Same function, same terminal status, same per-gate counter as the
        # post-fetch gate, which stays as the backstop. The source scopes
        # SRC-50's per-source leaves exactly as the live filter does.
        target_news, pre_denied_ids = self._split_denied_by_category(website_name, target_news)
        gate_counts = collections.Counter()
        if pre_denied_ids:
            self.data_flow_repo.mark_sitemaps_status(pre_denied_ids, "rejected_filter")
            gate_counts["deny"] += len(pre_denied_ids)
            logger.info(f"{website_name}: {len(pre_denied_ids)} sitemap(s) rejected by category before "
                        f"fetching (SYS-50); {len(target_news)} left to fetch")

        # Calculate batch size so that we have at most 10 batches
        batch_size = max(1, math.ceil(len(target_news) / 10))

        # SYS-04: track the funnel so crawl_log.article_count reflects reality and
        # the extracted/attempted ratio is visible per source -- the single most
        # useful "is this scraper rotting" signal. SYS-50: `attempted` counts the
        # rows actually FETCHED. It is the denominator of OPS-16's source-wide
        # ratio, and counting the pre-denied rows would make a 100% fetch outage
        # on MEDIAINDONESIA read as ~52% and never trip the guard.
        attempted = len(target_news)
        extracted_total = 0
        passed_filter_total = 0
        saved_total = 0
        # OPS-15: sitemap_id -> reason for every sitemap this run fetched nothing
        # for. Recorded to the DB only at the end of the run (see below), because
        # "did the whole source fail?" cannot be answered per batch.
        run_failures = {}
        # SYS-54: every sitemap the filter settled as rejected_filter this run.
        settled_rejected = set()
        # SYS-35 (#118, fix 4) / SYS-45 (#140): per-run filter telemetry.
        # `gate_counts` says how each decision was made; `allow_total`/
        # `allow_score_passed` count, per news category, how many articles the
        # PROBE kept of those the category gate would once have saved
        # unconditionally -- the probe's rejects on news desks are the
        # precision SYS-45 bought, and a drop in this ratio is a recall
        # regression visible per run. SYS-37 fix 4: `uncertain` counts the
        # decisions with P(soft) in the band -- the size of a possible
        # LLM tie-break, not filed until the number exists.
        allow_total = collections.Counter()
        allow_score_passed = collections.Counter()
        uncertain = 0
        # SYS-34 (#115, fix c): (source, category) pairs that have ever produced
        # a saved article. The first save under a pair not in here is a WARNING
        # -- a new source's vocabulary (IDNTIMES `hype`/`korea`/`fiction`)
        # becomes visible the day it first leaks, not at the next audit.
        known_saved_pairs = self._load_known_saved_pairs(website_name)

        for i in range(0, min(len(target_news), batch_size * 10), batch_size):
            logger.info(f"Processing batch {i//batch_size+1} for {website_name}")
            batch = target_news[i:i+batch_size]
            # Extract Articles from the batch
            newsdetails: List[NewsDetailsDTO] = web_crawler.batch_crawling_details(news=batch, website_name=website_name)

            # SYS-09: a sitemap in `batch` with no matching NewsDetailsDTO is exactly
            # the sitemaps whose fetch/extraction failed this run (soup was None, or
            # _get_news_details raised) -- mark_sitemaps_attempted below only covers
            # the successes, so without this a permanently-dead URL was never marked
            # at all and kept consuming a retry slot on every single run forever.
            # OPS-15: batch_crawling_details now says WHY (NewsDetailsBatch.failures);
            # a crawler mock or older return type without it gets the generic text.
            extracted_ids = {n.sitemap_id for n in newsdetails} if newsdetails else set()
            reasons = getattr(newsdetails, "failures", None) or {}
            for s in batch:
                if s.sitemap_id not in extracted_ids:
                    run_failures[s.sitemap_id] = reasons.get(s.sitemap_id, "fetch or extraction produced no result")

            if not newsdetails:
                continue

            extracted_total += len(newsdetails)
            logger.info(f"                  Batch {i//batch_size+1} has {len(newsdetails)} articles extracted.")

            # Bug B fix: mark every successfully-extracted sitemap as attempted so it is
            # not re-crawled until the cooldown elapses. Extraction failures are not in
            # `newsdetails`; SYS-09 counts them in sitemaps.fetch_failures at the end of
            # the run (also stamping the cooldown), and load_all_sitemaps stops
            # offering a sitemap once it reaches SITEMAP_MAX_FETCH_FAILURES -- so a
            # failure is retried after the cooldown, at most that many times. A
            # source-wide failure (OPS-15/OPS-16, _record_fetch_failures) still
            # counts per-URL reasons and cooldown-stamps the rest.
            self.data_flow_repo.mark_sitemaps_attempted([n.sitemap_id for n in newsdetails])

            # SYS-33 (#114): a lastmod-only source (TIRTO, TEMPO) stored the
            # URL slug as its headline; the crawler just read the real
            # og:title off the page. Write it back for every fetched page --
            # rejected rows too, since their headline is what SYS-38's
            # re-score and SYS-36's gold set read -- before the filter runs.
            self._write_back_page_headlines(website_name, newsdetails)

            # Build sitemap lookup so the filter and the chunker both get
            # source/category metadata for this batch.
            sitemap_by_id = {s.sitemap_id: s for s in batch}

            # --- Semantic Filtering ---
            important_newsdetails = []
            # SYS-16: a rejection is either permanent (real text, but off-topic --
            # the same headline/body gets the same verdict from the same probe)
            # or transient (no extractor produced usable text this run -- a layout
            # fix or a later attempt could still succeed). Only the former should
            # stop being re-queued; the latter keeps the normal cooldown retry.
            rejected_filter_ids = []
            empty_extraction_ids = []
            for news in newsdetails:
                try:
                    # Construct text for checking (Title + Content Snippet)
                    title = news.meta_data.get('title', '')
                    # Clean/prepare text snippet
                    full_text = " ".join(news.extracted_text) if isinstance(news.extracted_text, list) else str(news.extracted_text)
                    sitemap_meta = sitemap_by_id.get(news.sitemap_id)
                    category = sitemap_meta.category if sitemap_meta else None

                    # SYS-35: an article with no extracted body is an extraction
                    # failure whatever its category says. Before the category
                    # allow-set existed a bare title still had to clear the
                    # score; now it would be waved through and chunk to
                    # nothing, leaving the row `attempted` instead of the
                    # transient `empty_extraction` it actually is.
                    if not full_text.strip():
                        empty_extraction_ids.append(news.sitemap_id)
                        gate_counts["empty"] += 1
                        continue

                    check_text = build_check_text(title, full_text)
                    decision = self.semantic_filter.classify(check_text, category=category, source=website_name)
                    gate_counts[decision.gate] += 1
                    if decision.gate == "allow":
                        allow_total[category] += 1
                        if decision.score_passed:
                            allow_score_passed[category] += 1
                    if getattr(decision, "in_uncertain_band", False):
                        uncertain += 1

                    if decision.is_important:
                        # SYS-37 fix 3: the topic rides on the DTO to articles.topic.
                        if getattr(decision, "topic", None):
                            news = dataclasses.replace(news, topic=decision.topic,
                                                       topic_confidence=decision.topic_confidence)
                        important_newsdetails.append(news)
                    else:
                        rejected_filter_ids.append(news.sitemap_id)
                except Exception as e:
                    logger.warning(f"Error filtering news {news.sitemap_id}: {e}")

            passed_filter_total += len(important_newsdetails)
            logger.info(f"                  Filtered: {len(newsdetails) - len(important_newsdetails)} unimportant articles.")
            logger.info(f"                  Remaining: {len(important_newsdetails)} important articles.")

            if rejected_filter_ids:
                self.data_flow_repo.mark_sitemaps_status(rejected_filter_ids, "rejected_filter")
                settled_rejected.update(rejected_filter_ids)
            if empty_extraction_ids:
                self.data_flow_repo.mark_sitemaps_status(empty_extraction_ids, "empty_extraction")

            if important_newsdetails:
                try:
                    all_chunks = []
                    for news in important_newsdetails:
                        sitemap_meta = sitemap_by_id.get(news.sitemap_id)
                        all_chunks.extend(self.chunker.chunk(news, sitemap_meta))

                    embedded_sitemap_ids = self.data_flow_repo.save_chunk_data(all_chunks)

                    if embedded_sitemap_ids:
                        logger.info(f"Embedded {len(embedded_sitemap_ids)} articles as chunks, batch {i//batch_size+1}")
                        to_save = [n for n in important_newsdetails if n.sitemap_id in set(embedded_sitemap_ids)]
                        # SYS-04: drive both the count and the 'saved' stamp from what
                        # actually committed, not from what was handed to persistence
                        # -- save_newsdetails_data can commit fewer rows than to_save
                        # (a per-row savepoint failure, or on_conflict_do_nothing for
                        # a sitemap that already has an article).
                        committed_sitemap_ids = list(self.save_scraped_data(to_save) or [])
                        if committed_sitemap_ids:
                            self.data_flow_repo.mark_sitemaps_status(committed_sitemap_ids, "saved")
                            self._warn_on_unseen_categories(
                                website_name, committed_sitemap_ids, sitemap_by_id, known_saved_pairs
                            )
                        saved_total += len(committed_sitemap_ids)
                        logger.info(
                            f"Saved batch {i//batch_size+1} for {website_name}: "
                            f"{len(committed_sitemap_ids)}/{len(to_save)} rows actually committed"
                        )
                except Exception as e:
                    logger.error(f"Error saving batch {i//batch_size+1} for {website_name}: {e}")
                    continue

        self._source_failure_verdict = self._record_fetch_failures(website_name, attempted, run_failures)
        self._discard_terminal_embeddings(website_name, set(pre_denied_ids) | settled_rejected | set(run_failures))
        self._log_filter_stats(website_name, gate_counts, allow_total, allow_score_passed, uncertain)

        logger.info(
            f"Full-text crawl finished for {website_name}: "
            f"pre_denied={len(pre_denied_ids)} attempted={attempted} extracted={extracted_total} "
            f"passed_filter={passed_filter_total} saved={saved_total}"
        )
        return saved_total

    def _discard_terminal_embeddings(self, website_name: str, candidates) -> None:
        """SYS-54 (#185): the sitemaps this run settled for good (rejected, or a
        fetch failure that reached the cap) lose any vectors and chunk rows they
        already had. Runs inside the source's deferred block, so the deletions
        are flushed with its adds. A failure here costs nothing the store check
        does not report, so it is logged, not raised: the source's articles were
        saved."""
        if not candidates:
            return
        try:
            deleted = self.data_flow_repo.discard_terminal_embeddings(candidates)
        except Exception as e:  # noqa: BLE001
            logger.error(f"{website_name}: could not remove the vectors of settled sitemaps (SYS-54): {e!r}; "
                         f"check_store_consistency will report them and repair_store_consistency removes them")
            return
        if deleted:
            logger.info(f"{website_name}: removed {deleted} vector(s) of sitemaps settled terminal this run (SYS-54)")

    @staticmethod
    def _split_denied_by_category(website_name: str, sitemaps):
        """SYS-50: (rows to fetch, sitemap_ids the category gate denies). Pure. A
        category that is not a string (None: no category) is never denied here;
        the post-fetch gate decides it as before."""
        to_fetch, denied = [], []
        for s in sitemaps:
            category = getattr(s, "category", None)
            if isinstance(category, str) and category_gate(category, website_name) == "deny":
                denied.append(s.sitemap_id)
            else:
                to_fetch.append(s)
        return to_fetch, denied

    def _write_back_page_headlines(self, website_name: str, newsdetails) -> None:
        """SYS-33: persist the page title the crawler preferred over a
        placeholder headline (`meta_data["headline_from_page"]`). Failure here
        must not fail the batch -- the DTO still carries the real title for the
        filter, the chunker and the article row."""
        headlines = {
            n.sitemap_id: n.meta_data["title"]
            for n in newsdetails
            if n.meta_data and n.meta_data.get("headline_from_page") and n.meta_data.get("title")
        }
        if not headlines:
            return
        try:
            changed = self.data_flow_repo.update_sitemap_headlines(headlines)
        except Exception as e:  # noqa: BLE001 -- see docstring
            logger.warning(f"{website_name}: could not write back {len(headlines)} page headline(s): {e!r}")
            return
        logger.info(f"{website_name}: replaced {changed} URL-slug placeholder headline(s) with the page title")

    def _load_known_saved_pairs(self, website_name: str):
        """SYS-34: the (source, category) pairs that have ever produced a saved
        article for this source, or None when the repository cannot say (a
        repository double without the method, a DB error) -- in which case the
        unseen-category check is skipped rather than warning on everything."""
        getter = getattr(self.data_flow_repo, "get_saved_category_pairs", None)
        if getter is None:
            return None
        try:
            pairs = getter(website_name)
        except Exception as e:  # noqa: BLE001 -- telemetry must never fail the crawl
            logger.warning(f"{website_name}: could not load known saved categories ({e!r}); unseen-category check skipped")
            return None
        if not isinstance(pairs, (set, frozenset, list, tuple)):
            return None
        return set(pairs)

    @staticmethod
    def _warn_on_unseen_categories(website_name, committed_sitemap_ids, sitemap_by_id, known_saved_pairs) -> None:
        """SYS-34 (#115, fix c): WARNING the first time this source saves an
        article under a category it has never saved under before. The deny-list
        is allow-by-default and only knows the vocabulary it was built from; the
        next source's `hype`/`korea`/`fiction` leaks silently otherwise."""
        if known_saved_pairs is None:
            return
        for sitemap_id in committed_sitemap_ids:
            meta = sitemap_by_id.get(sitemap_id)
            category = (meta.category if meta else None) or ""
            pair = (website_name, category.strip().lower())
            if pair in known_saved_pairs:
                continue
            known_saved_pairs.add(pair)
            headline = (meta.headline if meta else "") or ""
            logger.warning(
                f"{website_name}: first article ever saved under category {category!r} "
                f"(never seen before on this source) -- sitemap_id={sitemap_id} {headline[:90]!r}. "
                f"Sample the category's titles: if it is a soft vertical it belongs on the "
                f"deny-list (SYS-34), if it is a news desk on the allow-set (SYS-35)."
            )

    @staticmethod
    def _log_filter_stats(website_name, gate_counts, allow_total, allow_score_passed, uncertain=0) -> None:
        """SYS-35 (#118, fix 4) / SYS-45 / SYS-37: one line per run on how the
        filter decided; the probe's keep rate per news category (its rejects
        there are SYS-45's precision -- a fall in the rate is a recall
        regression on a desk that is news by construction); and the size of
        the uncertain band. The CI gate on the probe artifact is what fails a
        regression; these lines make the numbers readable per run and source."""
        if not gate_counts:
            return
        summary = ", ".join(f"{k}={v}" for k, v in sorted(gate_counts.items()))
        scored = sum(v for k, v in gate_counts.items() if k in ("allow", "score"))
        band = f"; uncertain band P(soft) in [0.35, 0.65]: {uncertain}/{scored}" if scored else ""
        logger.info(f"{website_name}: filter decisions this run: {summary}{band}")
        if not allow_total:
            return
        parts = []
        for category, total in sorted(allow_total.items(), key=lambda kv: -kv[1]):
            passed = allow_score_passed.get(category, 0)
            rate = passed / total if total else 0.0
            parts.append(f"{category}={passed}/{total} ({rate:.0%})")
        logger.info(
            f"{website_name}: probe keep rate on news categories (SYS-45: the rest are rejects on a news desk): "
            f"{', '.join(parts)}"
        )

    # OPS-16 (#87): a failure reason that is a fact about THE URL, not about the
    # source. A 404 or a soft-404 means that page is gone whether 3 of 3 or 1,000
    # of 1,000 came back that way, so it must still count toward SYS-09's cap --
    # otherwise a window of dead URLs is re-fetched on every run forever and the
    # queue behind it is never reached. Everything else (403, 5xx, connection,
    # TLS, timeouts, an extractor regression) is a statement about the source.
    PER_URL_FAILURE_MARKERS = ("http 404", "http 410", "soft-404")

    @classmethod
    def _is_per_url_failure(cls, reason: str) -> bool:
        text = (reason or "").strip().lower()
        return any(marker in text for marker in cls.PER_URL_FAILURE_MARKERS)

    def _record_fetch_failures(self, website_name: str, attempted: int, run_failures: dict):
        """OPS-15/OPS-16: turn this run's fetch failures into sitemaps.fetch_failures.

        SYS-09's cap exists to retire individually dead URLs. A site blocking
        article pages, a TLS/DNS problem, or a regression in _get_news_details
        fails every URL at once; counting those would retire up to 1,000 sitemaps
        per run per source. OPS-15 handled that with a pure ratio and no persisted
        output, which broke three ways (OPS-16):

          1. No minimum count. With 3 rows left and all 3 dead, every run was
             100% ⇒ "source-wide" ⇒ nothing counted AND no cooldown stamped, so
             they were re-fetched on every run forever -- worse than before
             OPS-15, when they at least retired after 3 runs. BISNIS's eligible
             queue is 3 rows and BISNIS is 403-blocked.
          2. A dead top-1,000 window stalled the whole queue: `load_all_sitemaps`
             is ORDER BY posted_at DESC LIMIT 1000, so the same dead rows were
             handed to every run and the 10,000+ behind them were never reached.
          3. No trace but stderr. The crawl_log row was
             status='completed', article_count=0, error_msg=NULL -- identical to
             "1,000 pages fetched fine, all off-topic".

        Now: the floor (SITEMAP_SOURCE_FAILURE_MIN) must be cleared as well as the
        ratio; per-URL reasons are counted even in a source-wide run; the
        source-level remainder gets its cooldown stamped so the window rotates;
        and the verdict is returned for the caller to persist on the crawl_log row.

        Returns the verdict string to record, or None when there is nothing
        remarkable to say.
        """
        if not run_failures:
            return None
        failed = len(run_failures)
        ratio = failed / attempted if attempted else 0.0
        by_reason = {}
        for sitemap_id, reason in run_failures.items():
            by_reason.setdefault(reason, []).append(sitemap_id)
        reason_summary = ", ".join(f"{r!r}: {len(ids)}" for r, ids in sorted(by_reason.items(), key=lambda kv: -len(kv[1])))

        source_wide = ratio >= SITEMAP_SOURCE_FAILURE_RATIO and failed >= SITEMAP_SOURCE_FAILURE_MIN

        if source_wide:
            # Per-URL facts still count; only the source-level reasons are spared.
            per_url = {r: ids for r, ids in by_reason.items() if self._is_per_url_failure(r)}
            source_level = {r: ids for r, ids in by_reason.items() if not self._is_per_url_failure(r)}
            for reason, ids in per_url.items():
                self.data_flow_repo.increment_fetch_failures(ids, error_msg=reason)
            spared = [sid for ids in source_level.values() for sid in ids]
            if spared:
                # OPS-16 (b): stamp the cooldown even though nothing was counted,
                # so a blocked source is not re-hammered 1,000 requests per run
                # and a dead window rotates out of the LIMIT 1000.
                try:
                    self.data_flow_repo.mark_sitemaps_attempted(spared)
                except Exception as e:  # noqa: BLE001 -- telemetry must not fail the crawl
                    logger.warning(f"{website_name}: could not stamp cooldown on {len(spared)} spared sitemap(s): {e!r}")
            verdict = (
                f"source-wide fetch failure: {failed}/{attempted} ({ratio:.0%}); "
                f"{sum(len(i) for i in per_url.values())} counted as per-URL, "
                f"{len(spared)} spared and cooldown-stamped. Reasons: {reason_summary}"
            )
            logger.error(f"{website_name}: {verdict}")
            return verdict

        if ratio >= SITEMAP_SOURCE_FAILURE_RATIO:
            # Ratio met but below the floor: explicitly NOT source-wide (OPS-16 a).
            logger.warning(
                f"{website_name}: {failed}/{attempted} sitemaps failed ({ratio:.0%}) but that is below "
                f"SITEMAP_SOURCE_FAILURE_MIN={SITEMAP_SOURCE_FAILURE_MIN}, so this is {failed} dead URL(s), "
                f"not a source-wide failure: counting them individually. Reasons: {reason_summary}"
            )
        elif ratio >= 0.5:
            logger.warning(
                f"{website_name}: {failed}/{attempted} sitemaps failed to fetch/extract this run "
                f"({ratio:.0%}, below SITEMAP_SOURCE_FAILURE_RATIO={SITEMAP_SOURCE_FAILURE_RATIO}); "
                f"counting them individually. Reasons: {reason_summary}"
            )
        for reason, ids in by_reason.items():
            self.data_flow_repo.increment_fetch_failures(ids, error_msg=reason)

    # OPS-11 (#67): the two website-agnostic tasks get the same crawl_log
    # bracketing the crawl tasks have had since Phase 5, under website="ALL",
    # so "did extraction/the newsletter run today, and did it do anything" is
    # answerable from the runbook's own table. A run in which every Gemini
    # call failed without a response is recorded as status='failed' with the
    # first error -- OPS-09 made those failures leave no other trace.
    def extract_knowledge(self) -> int:
        logger.info("Starting knowledge extraction phase...")
        log_id = self.data_flow_repo.log_crawl_start("ALL", "extract_knowledge")
        try:
            result = self.data_flow_repo.extract_knowledge()
        except Exception as e:
            self.data_flow_repo.log_crawl_failed(log_id, str(e)[:500])
            raise
        count = int(result)
        if getattr(result, "all_calls_failed", False):
            msg = (f"all {result.attempted} Gemini calls failed without a response: "
                   f"{result.first_transient_error}")
            self.data_flow_repo.log_crawl_failed(log_id, msg[:500])
            logger.error(f"Knowledge extraction FAILED: {msg}")
            return count
        self.data_flow_repo.log_crawl_complete(log_id, count)
        logger.info(f"Knowledge extraction complete. Processed {count} articles.")
        return count

    def generate_newsletter(self, target_date=None):
        logger.info(f"Starting newsletter generation for {target_date or 'today'}...")
        log_id = self.data_flow_repo.log_crawl_start("ALL", "newsletter")
        try:
            path = self.data_flow_repo.generate_newsletter(target_date)
        except Exception as e:
            self.data_flow_repo.log_crawl_failed(log_id, str(e)[:500])
            raise
        self.data_flow_repo.log_crawl_complete(log_id, 1 if path else 0)
        logger.info(f"Newsletter generated: {path}")
        return path

    def save_scraped_data(self, scraped_data):
        if not scraped_data:
            return []
        if isinstance(scraped_data[0], SitemapDTO):
            return self.data_flow_repo.save_sitemap_data(scraped_data)  # add return
        elif isinstance(scraped_data[0], NewsDetailsDTO):
            # SYS-04: return what was actually committed (a list of sitemap_ids),
            # not the input DTOs -- callers need to know what landed, not what was
            # attempted.
            return self.data_flow_repo.save_newsdetails_data(scraped_data)

