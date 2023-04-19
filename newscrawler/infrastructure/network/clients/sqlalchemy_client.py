import os
import logging
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SQLAlchemyClient:
    def __init__(self, isolation_level=None):
        database_host = os.getenv("POSTGRES_DB_HOST", "localhost")
        database_port = os.getenv("POSTGRES_DB_PORT", 5431)
        database_user = os.getenv("POSTGRES_DB_USER", "postgres")
        database_pass = os.getenv("POSTGRES_DB_PASS", "postgres")
        database_name = os.getenv("POSTGRES_DB_NAME", "newsaggregator")

        self.database_uri = f"postgresql+psycopg2://{database_user}:{database_pass}@{database_host}:{database_port}/{database_name}"

        engine = create_engine(self.database_uri, isolation_level=isolation_level)
        self.Session = sessionmaker(bind=engine)

    @contextmanager
    def get_session(self):
        session = self.Session()

        try:
            yield session

        except Exception as e:  # noqa E722
            logger.error(f"Error occurred when accessing database using SQLAlchemy. Rolling back...\nException: {e}")
            session.rollback()
        finally:
            session.close()
