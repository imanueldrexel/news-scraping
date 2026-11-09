import os
import logging
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SQLAlchemyClient:
    def __init__(self, isolation_level=None, sent_to_local: bool = False):
        database_host = os.getenv("POSTGRES_DB_HOST", "localhost")
        database_port = os.getenv("POSTGRES_DB_PORT", 5431)
        database_user = os.getenv("POSTGRES_DB_USER", "postgres")
        database_pass = os.getenv("POSTGRES_DB_PASS", "postgres")
        database_name = os.getenv("POSTGRES_DB_NAME", "newsaggregator")
        if sent_to_local:
            database_host = "localhost"
            database_port = 5431
            database_user = "postgres"
            database_pass = "postgres"
            database_name = "newsaggregator"

        self.database_uri = f"postgresql+psycopg2://{database_user}:{database_pass}@{database_host}:{database_port}/{database_name}"

        engine = create_engine(self.database_uri, isolation_level=isolation_level)
        self.Session = sessionmaker(bind=engine)

    @contextmanager
    def get_session(self):
        """Yield a session; roll back on error and re-raise.

        The error must propagate: swallowing it here made a DB outage look like a
        successful crawl with zero rows (SYS-03). Callers that can tolerate a failure
        (crawl_log writes, the web UI) wrap this in their own try/except.
        """
        session = self.Session()

        try:
            yield session

        except Exception as e:
            logger.error(
                f"Database error, rolling back: {type(e).__name__}: {str(e).splitlines()[0][:300]}"
            )
            session.rollback()
            raise
        finally:
            session.close()
