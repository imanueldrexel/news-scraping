from typing import List, Optional

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
        min_tokens: int = 80,
        max_tokens: int = 450,
        overlap_tokens: int = 50,
    ):
        self.min_tokens = min_tokens
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens

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
