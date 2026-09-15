"""
Integration test configuration.
CRITICAL: Forces all DB connections to the TEST database, never to production.
"""
import os

# Force-override regardless of what is in the shell environment or .env.
# This ensures integration tests never touch the production newsaggregator DB.
os.environ["POSTGRES_DB_NAME"]      = "newsaggregator_test"
os.environ["POSTGRES_TEST_DB_NAME"] = "newsaggregator_test"
os.environ["POSTGRES_DB_PASS"]      = "postgres"
os.environ["POSTGRES_DB_PORT"]      = "5431"
os.environ["POSTGRES_DB_HOST"]      = "localhost"
os.environ["POSTGRES_DB_USER"]      = "postgres"
