"""Neo4j client for knowledge graph operations."""

import logging
from typing import Dict, List, Optional, Any
from neo4j import GraphDatabase

logger = logging.getLogger(__name__)


class Neo4jClient:
    """Neo4j graph database client."""

    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def is_available(self) -> bool:
        try:
            with self.driver.session() as session:
                session.run("RETURN 1")
            return True
        except Exception:
            return False

    def init_schema(self):
        """Initialize graph schema with constraints and indexes."""
        constraints = [
            "CREATE CONSTRAINT person_name IF NOT EXISTS FOR (p:Person) REQUIRE p.canonical_name IS UNIQUE",
            "CREATE CONSTRAINT company_name IF NOT EXISTS FOR (c:Company) REQUIRE c.canonical_name IS UNIQUE",
            "CREATE CONSTRAINT organization_name IF NOT EXISTS FOR (o:Organization) REQUIRE o.canonical_name IS UNIQUE",
            "CREATE CONSTRAINT government_name IF NOT EXISTS FOR (g:Government) REQUIRE g.canonical_name IS UNIQUE",
            "CREATE CONSTRAINT location_name IF NOT EXISTS FOR (l:Location) REQUIRE l.canonical_name IS UNIQUE",
            "CREATE CONSTRAINT article_url IF NOT EXISTS FOR (a:Article) REQUIRE a.url IS UNIQUE",
        ]

        indexes = [
            "CREATE INDEX person_aliases IF NOT EXISTS FOR (p:Person) ON (p.aliases)",
            "CREATE INDEX article_date IF NOT EXISTS FOR (a:Article) ON (a.published_at)",
            "CREATE INDEX article_source IF NOT EXISTS FOR (a:Article) ON (a.source)",
        ]

        with self.driver.session() as session:
            for constraint in constraints:
                try:
                    session.run(constraint)
                except Exception as e:
                    logger.debug(f"Constraint may exist: {e}")

            for index in indexes:
                try:
                    session.run(index)
                except Exception as e:
                    logger.debug(f"Index may exist: {e}")

        logger.info("Neo4j schema initialized")

    def upsert_entity(
        self,
        entity_type: str,
        canonical_name: str,
        properties: Dict[str, Any],
        aliases: Optional[List[str]] = None,
    ) -> str:
        """Upsert an entity node."""
        label = entity_type.title()
        aliases = aliases or []

        query = f"""
        MERGE (e:{label} {{canonical_name: $canonical_name}})
        ON CREATE SET e += $properties, e.aliases = $aliases, e.mention_count = 1, e.created_at = datetime()
        ON MATCH SET e.mention_count = e.mention_count + 1, e.updated_at = datetime(),
                     e.aliases = [x IN (COALESCE(e.aliases, []) + $aliases) WHERE x IS NOT NULL | x]
        RETURN elementId(e) as node_id
        """

        with self.driver.session() as session:
            result = session.run(
                query,
                canonical_name=canonical_name,
                properties=properties,
                aliases=aliases,
            )
            record = result.single()
            return record["node_id"] if record else None

    def upsert_article(
        self,
        url: str,
        headline: str,
        source: str,
        published_at: Optional[str] = None,
        category: Optional[str] = None,
    ) -> str:
        """Upsert an article node."""
        query = """
        MERGE (a:Article {url: $url})
        ON CREATE SET a.headline = $headline, a.source = $source,
                      a.published_at = $published_at, a.category = $category,
                      a.created_at = datetime()
        ON MATCH SET a.updated_at = datetime()
        RETURN elementId(a) as node_id
        """

        with self.driver.session() as session:
            result = session.run(
                query,
                url=url,
                headline=headline,
                source=source,
                published_at=published_at,
                category=category,
            )
            record = result.single()
            return record["node_id"] if record else None

    def create_relationship(
        self,
        from_type: str,
        from_name: str,
        rel_type: str,
        to_type: str,
        to_name: str,
        properties: Optional[Dict] = None,
    ) -> bool:
        """Create a relationship between entities."""
        from_label = from_type.title()
        to_label = to_type.title()
        properties = properties or {}

        query = f"""
        MATCH (a:{from_label} {{canonical_name: $from_name}})
        MATCH (b:{to_label} {{canonical_name: $to_name}})
        MERGE (a)-[r:{rel_type}]->(b)
        ON CREATE SET r += $properties, r.created_at = datetime()
        ON MATCH SET r.count = COALESCE(r.count, 1) + 1
        RETURN r
        """

        with self.driver.session() as session:
            result = session.run(
                query,
                from_name=from_name,
                to_name=to_name,
                properties=properties,
            )
            return result.single() is not None

    def link_to_article(
        self,
        entity_type: str,
        entity_name: str,
        article_url: str,
    ) -> bool:
        """Link an entity to an article."""
        label = entity_type.title()

        query = f"""
        MATCH (e:{label} {{canonical_name: $entity_name}})
        MATCH (a:Article {{url: $article_url}})
        MERGE (e)-[r:MENTIONED_IN]->(a)
        ON CREATE SET r.created_at = datetime()
        RETURN r
        """

        with self.driver.session() as session:
            result = session.run(
                query, entity_name=entity_name, article_url=article_url
            )
            return result.single() is not None

    def get_stats(self) -> Dict:
        """Get graph statistics."""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (n)
                WITH labels(n) as labels
                UNWIND labels as label
                RETURN label, count(*) as count
                ORDER BY count DESC
            """)
            nodes = {record["label"]: record["count"] for record in result}

            result = session.run("""
                MATCH ()-[r]->()
                RETURN type(r) as type, count(*) as count
                ORDER BY count DESC
            """)
            rels = {record["type"]: record["count"] for record in result}

            return {"nodes": nodes, "relationships": rels}
