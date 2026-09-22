from typing import List, Optional

from newscrawler.core import constants
from newscrawler.domain.dtos.dataflow.details.chunk_dto import ChunkDTO
from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO


def _count(text: str) -> int:
    return len(text.split())


def _split_with_overlap(text: str, max_tokens: int, overlap_tokens: int) -> List[str]:
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + max_tokens, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = end - overlap_tokens
    return chunks


class HierarchicalChunker:
    def __init__(
        self,
        min_tokens: Optional[int] = None,
        max_tokens: Optional[int] = None,
        overlap_tokens: Optional[int] = None,
    ):
        # DBT-13 (#48): the CHUNK_* env vars were parsed in constants.py and
        # never reached this constructor -- every call site used the class
        # defaults, so tuning chunk size via .env did nothing. The defaults
        # now come from constants (read at call time, so a test can patch
        # them); an explicit argument still wins.
        self.min_tokens = constants.CHUNK_MIN_TOKENS if min_tokens is None else min_tokens
        self.max_tokens = constants.CHUNK_MAX_TOKENS if max_tokens is None else max_tokens
        self.overlap_tokens = constants.CHUNK_OVERLAP_TOKENS if overlap_tokens is None else overlap_tokens
        # _split_with_overlap advances by (max - overlap) words per chunk; an
        # overlap >= max never advances and loops forever. Fail here, not there.
        if self.max_tokens <= 0 or self.min_tokens <= 0:
            raise ValueError(f"chunk sizes must be positive (min={self.min_tokens}, max={self.max_tokens})")
        if self.min_tokens > self.max_tokens:
            raise ValueError(f"CHUNK_MIN_TOKENS={self.min_tokens} > CHUNK_MAX_TOKENS={self.max_tokens}")
        if not 0 <= self.overlap_tokens < self.max_tokens:
            raise ValueError(
                f"CHUNK_OVERLAP_TOKENS={self.overlap_tokens} must be >= 0 and < CHUNK_MAX_TOKENS={self.max_tokens} "
                f"(an overlap >= max_tokens would never advance)"
            )

    def chunk(
        self,
        news: NewsDetailsDTO,
        sitemap: Optional[SitemapDTO] = None,
    ) -> List[ChunkDTO]:
        paragraphs = [p.strip() for p in (news.extracted_text or []) if p and p.strip()]
        if not paragraphs:
            return []

        l2_texts = self._build_l2(paragraphs)
        if not l2_texts:
            return []

        sitemap_id = news.sitemap_id
        title = (news.meta_data or {}).get("title", "") if news.meta_data else ""
        source = sitemap.sources if sitemap else ""
        category = sitemap.category if sitemap else None
        posted_at = None
        if sitemap and sitemap.timestamp:
            import datetime as _dt
            ts = sitemap.timestamp
            posted_at = int(ts.strftime("%Y%m%d")) if isinstance(ts, (_dt.datetime, _dt.date)) else int(ts)
        if posted_at is None and news.meta_data:
            posted_at = news.meta_data.get("posted_at")
        reporter = list(news.reporter) if news.reporter else []

        chunk_total = len(l2_texts)
        records: List[ChunkDTO] = []

        l1_text = " ".join(paragraphs[:2])
        records.append(ChunkDTO(
            sitemap_id=sitemap_id,
            chunk_level=1,
            chunk_index=0,
            chunk_total=1,
            is_first_chunk=True,
            is_last_chunk=True,
            text_content=l1_text,
            token_count=_count(l1_text),
            title=title,
            source=source,
            category=category,
            posted_at=posted_at,
            reporter=reporter,
        ))

        for i, text in enumerate(l2_texts):
            records.append(ChunkDTO(
                sitemap_id=sitemap_id,
                chunk_level=2,
                chunk_index=i,
                chunk_total=chunk_total,
                is_first_chunk=(i == 0),
                is_last_chunk=(i == chunk_total - 1),
                text_content=text,
                token_count=_count(text),
                title=title,
                source=source,
                category=category,
                posted_at=posted_at,
                reporter=reporter,
            ))

        return records

    def _build_l2(self, paragraphs: List[str]) -> List[str]:
        result = []
        for para in self._merge_short(paragraphs):
            if _count(para) > self.max_tokens:
                result.extend(_split_with_overlap(para, self.max_tokens, self.overlap_tokens))
            else:
                result.append(para)
        return result

    def _merge_short(self, paragraphs: List[str]) -> List[str]:
        result = []
        buf = ""
        for para in paragraphs:
            if buf and _count(buf) < self.min_tokens:
                buf = buf + " " + para
            else:
                if buf:
                    result.append(buf)
                buf = para
        if buf:
            result.append(buf)
        return result or paragraphs
