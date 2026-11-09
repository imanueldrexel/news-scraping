"""
One-time script to populate entity_aliases with known Indonesian emiten and institutions.
Run after migrate_phase2.sql has been executed.

Usage:
    python scripts/seed_entity_aliases.py
"""

import sys
import os

# Allow running from project root without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from newscrawler.core.alias_seed_data import ENTITY_SEED_DATA
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_knowledge_data_source import (
    SQLAlchemyKnowledgeDataSource,
)
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient


def main():
    client     = SQLAlchemyClient()
    datasource = SQLAlchemyKnowledgeDataSource(client)

    print(f"Seeding {len(ENTITY_SEED_DATA)} entities and their aliases...")
    datasource.seed_aliases(ENTITY_SEED_DATA)
    print("Done.")


if __name__ == "__main__":
    main()
