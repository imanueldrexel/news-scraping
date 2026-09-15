"""Schema for resolved entity messages from Entity Resolver to Graph Store."""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional
import uuid
import json


class ResolvedEntity(BaseModel):
    """An entity with normalized name and aliases."""

    canonical_name: str = Field(..., description="Normalized/canonical entity name")
    original_name: str = Field(..., description="Name as found in text")
    entity_type: str = Field(..., description="Entity type (PERSON, COMPANY, etc.)")
    aliases: List[str] = Field(
        default_factory=list, description="Known aliases for this entity"
    )
    neo4j_id: Optional[str] = Field(
        None, description="Neo4j node ID if entity exists"
    )


class ResolvedRelation(BaseModel):
    """A relationship between two resolved entities."""

    subject: ResolvedEntity = Field(..., description="Subject entity")
    predicate: str = Field(..., description="Relationship type")
    object: ResolvedEntity = Field(..., description="Object entity")
    confidence: float = Field(..., ge=0, le=1, description="Confidence score")
    article_url: str = Field(..., description="Source article URL")
    article_headline: str = Field(..., description="Source article headline")


class ResolvedEntitiesMessage(BaseModel):
    """
    Message with normalized entities and relations ready for Neo4j.
    Sent from Entity Resolver to Graph Store.
    """

    message_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="UUID for message tracing",
    )
    original_message_id: str = Field(
        ..., description="Original message ID from extraction"
    )
    url: str = Field(..., description="Source article URL")
    source: str = Field(..., description="News source identifier")
    headline: str = Field(..., description="Article headline")
    sitemap_id: Optional[int] = Field(None, description="Database ID reference")
    published_at: Optional[datetime] = Field(None, description="Publication timestamp")

    # Resolved data
    entities: List[ResolvedEntity] = Field(
        default_factory=list, description="All resolved entities from article"
    )
    relations: List[ResolvedRelation] = Field(
        default_factory=list, description="Resolved relations between entities"
    )

    resolved_at: datetime = Field(
        default_factory=datetime.utcnow, description="Resolution timestamp"
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat() if v else None}

    def to_redis_dict(self) -> dict:
        """Convert to dictionary suitable for Redis Streams."""
        data = self.model_dump()

        # Convert datetime to string
        for field in ["published_at", "resolved_at"]:
            if data.get(field):
                data[field] = data[field].isoformat()

        # Convert complex types to JSON
        if data.get("entities"):
            data["entities"] = json.dumps(
                [e if isinstance(e, dict) else e for e in data["entities"]]
            )
        if data.get("relations"):
            data["relations"] = json.dumps(
                [r if isinstance(r, dict) else r for r in data["relations"]]
            )

        return {k: str(v) if v is not None else "" for k, v in data.items()}

    @classmethod
    def from_redis_dict(cls, data: dict) -> "ResolvedEntitiesMessage":
        """Create instance from Redis Streams dictionary."""
        from dateutil import parser

        # Parse datetime fields
        for field in ["published_at", "resolved_at"]:
            if data.get(field) and data[field]:
                try:
                    data[field] = parser.parse(data[field])
                except:
                    data[field] = None

        # Parse entities JSON
        if data.get("entities"):
            try:
                entities_data = json.loads(data["entities"])
                data["entities"] = [ResolvedEntity(**e) for e in entities_data]
            except:
                data["entities"] = []

        # Parse relations JSON
        if data.get("relations"):
            try:
                relations_data = json.loads(data["relations"])
                data["relations"] = [ResolvedRelation(**r) for r in relations_data]
            except:
                data["relations"] = []

        # Parse numeric fields (handle empty strings from Redis)
        sitemap_id = data.get("sitemap_id")
        if sitemap_id and sitemap_id != "" and sitemap_id != "None":
            try:
                data["sitemap_id"] = int(sitemap_id)
            except:
                data["sitemap_id"] = None
        else:
            data["sitemap_id"] = None

        return cls(**data)
