#!/usr/bin/env python3
"""Initialize ChromaDB collections."""

import chromadb
from chromadb.config import Settings


def initialize_chromadb(host: str = "localhost", port: int = 8000):
    """Initialize ChromaDB collections for news scraper."""

    print(f"Connecting to ChromaDB at {host}:{port}...")

    client = chromadb.HttpClient(
        host=host,
        port=port,
        settings=Settings(anonymized_telemetry=False),
    )

    # Main news collection
    print("Creating 'indonesian_news' collection...")
    client.get_or_create_collection(
        name="indonesian_news",
        metadata={
            "hnsw:space": "cosine",
            "hnsw:construction_ef": 200,
            "hnsw:search_ef": 100,
            "description": "Indonesian news article embeddings",
        },
    )

    # Entity embeddings collection (for semantic entity matching)
    print("Creating 'entity_embeddings' collection...")
    client.get_or_create_collection(
        name="entity_embeddings",
        metadata={
            "hnsw:space": "cosine",
            "description": "Entity name embeddings for fuzzy matching",
        },
    )

    print("ChromaDB collections initialized successfully!")

    # Print collection info
    collections = client.list_collections()
    print(f"\nAvailable collections: {len(collections)}")
    for col in collections:
        count = col.count()
        print(f"  - {col.name}: {count} documents")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Initialize ChromaDB")
    parser.add_argument("--host", default="localhost", help="ChromaDB host")
    parser.add_argument("--port", type=int, default=8000, help="ChromaDB port")

    args = parser.parse_args()
    initialize_chromadb(args.host, args.port)
