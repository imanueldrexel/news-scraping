"""Schema for messages from Ingestion Service to Preprocessor."""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List
import uuid


class IngestedContentMessage(BaseModel):
    """
    Message pushed to Redis Streams after ingestion.
    Contains raw HTML and metadata from news article.
    """

    message_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="UUID for message tracing",
    )
    url: str = Field(..., description="Source URL of the article")
    html: str = Field(..., description="Raw HTML content")
    source: str = Field(
        ..., description="News source identifier (e.g., BISNIS, KONTAN)"
    )
    headline: str = Field(..., description="Article headline/title")
    category: Optional[str] = Field(None, description="Article category if available")
    keywords: Optional[List[str]] = Field(
        None, description="Keywords extracted from sitemap"
    )
    published_at: Optional[datetime] = Field(
        None, description="Article publication timestamp"
    )
    scraped_at: datetime = Field(
        default_factory=datetime.utcnow, description="When the article was scraped"
    )
    sitemap_id: Optional[int] = Field(
        None, description="ID from sitemaps table if stored"
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat() if v else None}

    def to_redis_dict(self) -> dict:
        """Convert to dictionary suitable for Redis Streams."""
        data = self.model_dump()
        # Convert datetime to string for Redis
        if data.get("published_at"):
            data["published_at"] = data["published_at"].isoformat()
        if data.get("scraped_at"):
            data["scraped_at"] = data["scraped_at"].isoformat()
        # Convert list to JSON string for Redis
        if data.get("keywords"):
            import json

            data["keywords"] = json.dumps(data["keywords"])
        return {k: str(v) if v is not None else "" for k, v in data.items()}

    @classmethod
    def from_redis_dict(cls, data: dict) -> "IngestedContentMessage":
        """Create instance from Redis Streams dictionary."""
        import json
        from dateutil import parser

        # Helper to check for empty/null values from Redis
        def is_empty(val):
            return val is None or val == "" or val == "None"

        # Parse datetime fields
        published_at = data.get("published_at")
        if not is_empty(published_at):
            try:
                data["published_at"] = parser.parse(published_at)
            except:
                data["published_at"] = None
        else:
            data["published_at"] = None

        scraped_at = data.get("scraped_at")
        if not is_empty(scraped_at):
            try:
                data["scraped_at"] = parser.parse(scraped_at)
            except:
                data["scraped_at"] = datetime.utcnow()
        else:
            data["scraped_at"] = datetime.utcnow()

        # Parse keywords JSON
        keywords = data.get("keywords")
        if not is_empty(keywords):
            try:
                data["keywords"] = json.loads(keywords)
            except json.JSONDecodeError:
                data["keywords"] = None
        else:
            data["keywords"] = None

        # Handle empty category
        if is_empty(data.get("category")):
            data["category"] = None

        # Parse sitemap_id
        sitemap_id = data.get("sitemap_id")
        if not is_empty(sitemap_id):
            try:
                data["sitemap_id"] = int(sitemap_id)
            except ValueError:
                data["sitemap_id"] = None
        else:
            data["sitemap_id"] = None

        return cls(**data)
