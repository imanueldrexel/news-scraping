"""Schema for messages from Preprocessor to Vectorizer and Extraction Engine."""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional
import uuid
import json


class TextChunk(BaseModel):
    """A chunk of text with metadata."""

    chunk_id: int = Field(..., description="Sequential chunk identifier")
    text: str = Field(..., description="Chunk text content")
    token_count: int = Field(..., description="Number of tokens in chunk")
    start_char: int = Field(..., description="Start character position in original text")
    end_char: int = Field(..., description="End character position in original text")


class PreprocessedContentMessage(BaseModel):
    """
    Message after HTML cleaning, relevance checking, and chunking.
    Sent to both Vectorizer and Extraction Engine.
    """

    message_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="UUID for message tracing",
    )
    original_message_id: str = Field(
        ..., description="Original message ID from ingestion"
    )
    url: str = Field(..., description="Source URL")
    source: str = Field(..., description="News source identifier")
    headline: str = Field(..., description="Article headline")
    category: Optional[str] = Field(None, description="Article category")
    published_at: Optional[datetime] = Field(None, description="Publication timestamp")
    sitemap_id: Optional[int] = Field(None, description="Database ID reference")

    # Cleaned content
    clean_text: str = Field(..., description="Full cleaned article text")
    summary: str = Field(
        ..., description="First 2-3 sentences as summary for embedding"
    )
    reporter: Optional[List[str]] = Field(None, description="Reporter/author names")

    # Chunked content for LLM processing
    chunks: List[TextChunk] = Field(..., description="Text chunks for processing")

    # Relevance assessment
    relevance_score: float = Field(
        ..., ge=0, le=1, description="Relevance score 0-1"
    )
    is_relevant: bool = Field(
        ..., description="Whether article passed relevance threshold"
    )

    processed_at: datetime = Field(
        default_factory=datetime.utcnow, description="Processing timestamp"
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat() if v else None}

    def to_redis_dict(self) -> dict:
        """Convert to dictionary suitable for Redis Streams."""
        data = self.model_dump()

        # Convert datetime to string
        for field in ["published_at", "processed_at"]:
            if data.get(field):
                data[field] = data[field].isoformat()

        # Convert complex types to JSON
        if data.get("reporter"):
            data["reporter"] = json.dumps(data["reporter"])
        if data.get("chunks"):
            data["chunks"] = json.dumps([c.model_dump() if hasattr(c, 'model_dump') else c for c in data["chunks"]])

        # Convert boolean
        data["is_relevant"] = "1" if data["is_relevant"] else "0"

        return {k: str(v) if v is not None else "" for k, v in data.items()}

    @classmethod
    def from_redis_dict(cls, data: dict) -> "PreprocessedContentMessage":
        """Create instance from Redis Streams dictionary."""
        from dateutil import parser

        # Parse datetime fields
        for field in ["published_at", "processed_at"]:
            if data.get(field) and data[field]:
                try:
                    data[field] = parser.parse(data[field])
                except:
                    data[field] = None

        # Parse JSON fields
        if data.get("reporter"):
            try:
                data["reporter"] = json.loads(data["reporter"])
            except:
                data["reporter"] = None

        if data.get("chunks"):
            try:
                chunks_data = json.loads(data["chunks"])
                data["chunks"] = [TextChunk(**c) for c in chunks_data]
            except:
                data["chunks"] = []

        # Parse numeric and boolean fields (handle empty strings from Redis)
        sitemap_id = data.get("sitemap_id")
        if sitemap_id and sitemap_id != "" and sitemap_id != "None":
            try:
                data["sitemap_id"] = int(sitemap_id)
            except:
                data["sitemap_id"] = None
        else:
            data["sitemap_id"] = None

        # Handle empty category
        if data.get("category") == "" or data.get("category") == "None":
            data["category"] = None

        if data.get("relevance_score"):
            data["relevance_score"] = float(data["relevance_score"])

        data["is_relevant"] = data.get("is_relevant") == "1"

        return cls(**data)
