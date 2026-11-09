"""Text chunker for splitting articles into processable chunks."""

import logging
from typing import List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TextChunk:
    """A chunk of text with metadata."""

    chunk_id: int
    text: str
    token_count: int
    start_char: int
    end_char: int


class TextChunker:
    """
    Splits text into overlapping chunks for LLM processing.
    Uses tiktoken for accurate token counting.
    """

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        encoding: str = "cl100k_base",
    ):
        """
        Initialize chunker.

        Args:
            chunk_size: Maximum tokens per chunk
            chunk_overlap: Tokens to overlap between chunks
            encoding: Tiktoken encoding to use
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        # Load tokenizer
        try:
            import tiktoken

            self.tokenizer = tiktoken.get_encoding(encoding)
            self._use_tiktoken = True
        except ImportError:
            logger.warning("tiktoken not available, using simple word tokenizer")
            self._use_tiktoken = False
            self.tokenizer = None

    def chunk(self, text: str) -> List[TextChunk]:
        """
        Split text into overlapping chunks.

        Args:
            text: Text to chunk

        Returns:
            List of TextChunk objects
        """
        if not text:
            return []

        if self._use_tiktoken:
            return self._chunk_with_tiktoken(text)
        else:
            return self._chunk_with_words(text)

    def _chunk_with_tiktoken(self, text: str) -> List[TextChunk]:
        """Chunk using tiktoken tokenizer."""
        tokens = self.tokenizer.encode(text)

        if len(tokens) <= self.chunk_size:
            return [
                TextChunk(
                    chunk_id=0,
                    text=text,
                    token_count=len(tokens),
                    start_char=0,
                    end_char=len(text),
                )
            ]

        chunks = []
        start = 0
        chunk_id = 0

        while start < len(tokens):
            end = min(start + self.chunk_size, len(tokens))
            chunk_tokens = tokens[start:end]
            chunk_text = self.tokenizer.decode(chunk_tokens)

            # Calculate character positions
            prefix_text = self.tokenizer.decode(tokens[:start])
            start_char = len(prefix_text)
            end_char = start_char + len(chunk_text)

            chunks.append(
                TextChunk(
                    chunk_id=chunk_id,
                    text=chunk_text,
                    token_count=len(chunk_tokens),
                    start_char=start_char,
                    end_char=end_char,
                )
            )

            chunk_id += 1

            # Move start with overlap
            if end >= len(tokens):
                break

            start = end - self.chunk_overlap

        return chunks

    def _chunk_with_words(self, text: str) -> List[TextChunk]:
        """Chunk using simple word tokenization."""
        words = text.split()

        # Estimate: ~0.75 words per token on average
        words_per_chunk = int(self.chunk_size * 0.75)
        words_overlap = int(self.chunk_overlap * 0.75)

        if len(words) <= words_per_chunk:
            return [
                TextChunk(
                    chunk_id=0,
                    text=text,
                    token_count=len(words),
                    start_char=0,
                    end_char=len(text),
                )
            ]

        chunks = []
        start = 0
        chunk_id = 0
        char_pos = 0

        while start < len(words):
            end = min(start + words_per_chunk, len(words))
            chunk_words = words[start:end]
            chunk_text = " ".join(chunk_words)

            # Calculate character positions
            start_char = char_pos
            end_char = start_char + len(chunk_text)

            chunks.append(
                TextChunk(
                    chunk_id=chunk_id,
                    text=chunk_text,
                    token_count=len(chunk_words),
                    start_char=start_char,
                    end_char=end_char,
                )
            )

            chunk_id += 1

            if end >= len(words):
                break

            # Update character position
            for word in chunk_words[: -words_overlap if words_overlap else None]:
                char_pos += len(word) + 1  # +1 for space

            start = end - words_overlap

        return chunks

    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text.

        Args:
            text: Text to count

        Returns:
            Token count
        """
        if self._use_tiktoken:
            return len(self.tokenizer.encode(text))
        else:
            return len(text.split())

    def chunk_by_paragraphs(
        self, text: str, max_paragraphs: int = 3
    ) -> List[TextChunk]:
        """
        Chunk by paragraphs, respecting token limits.

        Args:
            text: Text to chunk
            max_paragraphs: Maximum paragraphs per chunk

        Returns:
            List of TextChunk objects
        """
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        if not paragraphs:
            return self.chunk(text)

        chunks = []
        current_paragraphs = []
        current_tokens = 0
        chunk_id = 0
        char_pos = 0

        for para in paragraphs:
            para_tokens = self.count_tokens(para)

            # Check if adding this paragraph exceeds limit
            if (
                current_tokens + para_tokens > self.chunk_size
                or len(current_paragraphs) >= max_paragraphs
            ) and current_paragraphs:
                # Save current chunk
                chunk_text = "\n\n".join(current_paragraphs)
                chunks.append(
                    TextChunk(
                        chunk_id=chunk_id,
                        text=chunk_text,
                        token_count=current_tokens,
                        start_char=char_pos,
                        end_char=char_pos + len(chunk_text),
                    )
                )

                chunk_id += 1
                char_pos += len(chunk_text) + 2  # +2 for \n\n

                # Start new chunk with overlap
                if self.chunk_overlap > 0 and current_paragraphs:
                    current_paragraphs = [current_paragraphs[-1]]
                    current_tokens = self.count_tokens(current_paragraphs[0])
                else:
                    current_paragraphs = []
                    current_tokens = 0

            current_paragraphs.append(para)
            current_tokens += para_tokens

        # Add final chunk
        if current_paragraphs:
            chunk_text = "\n\n".join(current_paragraphs)
            chunks.append(
                TextChunk(
                    chunk_id=chunk_id,
                    text=chunk_text,
                    token_count=current_tokens,
                    start_char=char_pos,
                    end_char=char_pos + len(chunk_text),
                )
            )

        return chunks
