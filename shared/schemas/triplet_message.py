"""Schema for triplet extraction messages from Extraction Engine to Entity Resolver."""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional
from enum import Enum
import uuid
import json


class EntityType(str, Enum):
    """Valid entity types for knowledge graph."""

    PERSON = "PERSON"
    COMPANY = "COMPANY"
    ORGANIZATION = "ORGANIZATION"
    GOVERNMENT = "GOVERNMENT"
    LOCATION = "LOCATION"
    FINANCIAL_INSTRUMENT = "FINANCIAL_INSTRUMENT"
    AMOUNT = "AMOUNT"
    DATE = "DATE"
    EVENT = "EVENT"


class RelationType(str, Enum):
    """Valid relationship types for knowledge graph."""

    # Employment & Position
    WORKS_FOR = "WORKS_FOR"
    APPOINTED_AS = "APPOINTED_AS"
    RESIGNED_FROM = "RESIGNED_FROM"
    LEADS = "LEADS"

    # Ownership & Investment
    OWNED_BY = "OWNED_BY"
    OWNS = "OWNS"
    INVESTED_IN = "INVESTED_IN"
    RAISED_FUNDING = "RAISED_FUNDING"
    ACQUIRED = "ACQUIRED"

    # Business Relations
    PARTNERED_WITH = "PARTNERED_WITH"
    COMPETES_WITH = "COMPETES_WITH"
    SUPPLIES_TO = "SUPPLIES_TO"

    # Location
    LOCATED_IN = "LOCATED_IN"
    HEADQUARTERED_IN = "HEADQUARTERED_IN"
    OPERATES_IN = "OPERATES_IN"

    # General
    MENTIONED_IN = "MENTIONED_IN"
    ANNOUNCED = "ANNOUNCED"
    RELATED_TO = "RELATED_TO"


class Triplet(BaseModel):
    """A single subject-predicate-object triplet."""

    subject: str = Field(..., description="Subject entity name")
    subject_type: EntityType = Field(..., description="Type of subject entity")
    predicate: RelationType = Field(..., description="Relationship type")
    object: str = Field(..., description="Object entity name")
    object_type: EntityType = Field(..., description="Type of object entity")
    confidence: float = Field(
        ..., ge=0, le=1, description="Extraction confidence score"
    )
    source_chunk_id: int = Field(..., description="Which chunk this was extracted from")


class TripletExtractionMessage(BaseModel):
    """
    Message containing extracted triplets from an article.
    Sent from Extraction Engine to Entity Resolver.
    """

    message_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="UUID for message tracing",
    )
    original_message_id: str = Field(
        ..., description="Original message ID from preprocessor"
    )
    url: str = Field(..., description="Source URL")
    source: str = Field(..., description="News source identifier")
    headline: str = Field(..., description="Article headline")
    category: Optional[str] = Field(None, description="Article category")
    sitemap_id: Optional[int] = Field(None, description="Database ID reference")
    published_at: Optional[datetime] = Field(None, description="Publication timestamp")

    # Extracted triplets
    triplets: List[Triplet] = Field(
        default_factory=list, description="Extracted triplets"
    )

    # Extraction metadata
    extraction_model: str = Field(
        default="qwen2.5:7b-instruct", description="Model used for extraction"
    )
    chunks_processed: int = Field(
        default=0, description="Number of chunks processed"
    )
    extracted_at: datetime = Field(
        default_factory=datetime.utcnow, description="Extraction timestamp"
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat() if v else None}

    def to_redis_dict(self) -> dict:
        """Convert to dictionary suitable for Redis Streams."""
        data = self.model_dump()

        # Convert datetime to string
        for field in ["published_at", "extracted_at"]:
            if data.get(field):
                data[field] = data[field].isoformat()

        # Convert triplets to JSON
        if data.get("triplets"):
            triplets_data = []
            for t in data["triplets"]:
                t_dict = dict(t) if isinstance(t, dict) else t
                # Convert enums to strings
                if hasattr(t_dict.get("subject_type"), "value"):
                    t_dict["subject_type"] = t_dict["subject_type"].value
                if hasattr(t_dict.get("object_type"), "value"):
                    t_dict["object_type"] = t_dict["object_type"].value
                if hasattr(t_dict.get("predicate"), "value"):
                    t_dict["predicate"] = t_dict["predicate"].value
                triplets_data.append(t_dict)
            data["triplets"] = json.dumps(triplets_data)

        return {k: str(v) if v is not None else "" for k, v in data.items()}

    @classmethod
    def from_redis_dict(cls, data: dict) -> "TripletExtractionMessage":
        """Create instance from Redis Streams dictionary."""
        from dateutil import parser

        # Parse datetime fields
        for field in ["published_at", "extracted_at"]:
            if data.get(field) and data[field]:
                try:
                    data[field] = parser.parse(data[field])
                except:
                    data[field] = None

        # Parse triplets JSON
        if data.get("triplets"):
            try:
                triplets_data = json.loads(data["triplets"])
                data["triplets"] = [Triplet(**t) for t in triplets_data]
            except:
                data["triplets"] = []

        # Parse numeric fields (handle empty strings from Redis)
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

        if data.get("chunks_processed"):
            try:
                data["chunks_processed"] = int(data["chunks_processed"])
            except:
                data["chunks_processed"] = 0

        return cls(**data)
