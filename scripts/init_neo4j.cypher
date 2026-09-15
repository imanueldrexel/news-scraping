// Neo4j Schema Initialization Script
// Run this after Neo4j container starts

// ============================================
// CONSTRAINTS
// ============================================

// Entity constraints (unique canonical names)
CREATE CONSTRAINT person_name IF NOT EXISTS
FOR (p:Person) REQUIRE p.canonical_name IS UNIQUE;

CREATE CONSTRAINT company_name IF NOT EXISTS
FOR (c:Company) REQUIRE c.canonical_name IS UNIQUE;

CREATE CONSTRAINT organization_name IF NOT EXISTS
FOR (o:Organization) REQUIRE o.canonical_name IS UNIQUE;

CREATE CONSTRAINT government_name IF NOT EXISTS
FOR (g:Government) REQUIRE g.canonical_name IS UNIQUE;

CREATE CONSTRAINT location_name IF NOT EXISTS
FOR (l:Location) REQUIRE l.canonical_name IS UNIQUE;

CREATE CONSTRAINT article_url IF NOT EXISTS
FOR (a:Article) REQUIRE a.url IS UNIQUE;

// ============================================
// INDEXES
// ============================================

// Entity indexes for search
CREATE INDEX person_aliases IF NOT EXISTS
FOR (p:Person) ON (p.aliases);

CREATE INDEX company_aliases IF NOT EXISTS
FOR (c:Company) ON (c.aliases);

CREATE INDEX company_sector IF NOT EXISTS
FOR (c:Company) ON (c.sector);

// Article indexes
CREATE INDEX article_date IF NOT EXISTS
FOR (a:Article) ON (a.published_at);

CREATE INDEX article_source IF NOT EXISTS
FOR (a:Article) ON (a.source);

CREATE INDEX article_category IF NOT EXISTS
FOR (a:Article) ON (a.category);

// Full-text search index (optional)
// CREATE FULLTEXT INDEX entity_names IF NOT EXISTS
// FOR (n:Person|Company|Organization) ON EACH [n.canonical_name, n.aliases];

// ============================================
// SAMPLE QUERIES FOR TESTING
// ============================================

// Count nodes by label
// MATCH (n) RETURN labels(n)[0] as label, count(*) ORDER BY count DESC;

// Find all relationships for an entity
// MATCH (p:Person {canonical_name: "Joko Widodo"})-[r]->(n) RETURN p, r, n;

// Find connected entities through articles
// MATCH (p1:Person)-[:MENTIONED_IN]->(a:Article)<-[:MENTIONED_IN]-(p2:Person)
// WHERE p1.canonical_name = "Joko Widodo" AND p1 <> p2
// RETURN p2.canonical_name, count(a) as shared_articles ORDER BY shared_articles DESC;

// Get entity network
// MATCH path = (e1)-[*1..2]-(e2)
// WHERE e1.canonical_name = "PT Bank Central Asia Tbk"
// RETURN path LIMIT 50;
