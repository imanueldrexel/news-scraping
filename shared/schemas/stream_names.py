"""Redis Stream names used for inter-service communication."""


class StreamNames:
    """Constants for Redis Stream names."""

    # Ingestion -> Preprocessor
    INGESTED = "stream:ingested"

    # Preprocessor -> Vectorizer, Extraction
    PREPROCESSED = "stream:preprocessed"

    # Vectorizer -> Analyst
    VECTORIZED = "stream:vectorized"

    # Extraction -> Entity Resolver
    TRIPLETS = "stream:triplets"

    # Entity Resolver -> Graph Store
    ENTITIES = "stream:entities"

    # Consumer group names
    GROUP_PREPROCESSOR = "group:preprocessor"
    GROUP_VECTORIZER = "group:vectorizer"
    GROUP_EXTRACTION = "group:extraction"
    GROUP_ENTITY_RESOLVER = "group:entity-resolver"
    GROUP_GRAPH_STORE = "group:graph-store"
    GROUP_ANALYST = "group:analyst"
