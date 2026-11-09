"""NEWS_L1 as the story arcs' `search` (SYS-147 #337): read-only.

`l1_search(vs)` wraps a loaded LangChain FAISS store (L1: one vector per article,
title + first two paragraphs) in the callable `thread_finder.find_thread` takes:
    search(vector, k) -> [(sitemap_id, posted_at yyyymmdd int, cosine)]
Cosine is 1 - d/2 of FAISS's squared L2 distance between normalized vectors
(SYS-110). Documents without a sitemap_id (the index's "init" dummy) or a
readable yyyymmdd date are left out. Nothing here saves the index.
"""
from typing import Callable, List, Sequence, Tuple


def posted_at_int(value):
    """yyyymmdd as an int from the metadata's int or string, or None."""
    try:
        text = str(value).strip()
        return int(text[:8]) if len(text) >= 8 and text[:8].isdigit() else None
    except (TypeError, ValueError):
        return None


def l1_search(vs) -> Callable[[Sequence[float], int], List[Tuple[int, int, float]]]:
    def search(vector: Sequence[float], k: int) -> List[Tuple[int, int, float]]:
        hits = vs.similarity_search_with_score_by_vector([float(x) for x in vector], k=k)
        out = []
        for doc, distance in hits:
            sitemap_id, posted_at = doc.metadata.get("sitemap_id"), posted_at_int(doc.metadata.get("posted_at"))
            if sitemap_id is None or posted_at is None:
                continue
            out.append((int(sitemap_id), posted_at, 1.0 - float(distance) / 2.0))
        return out
    return search
