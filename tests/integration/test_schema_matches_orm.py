"""
DBT-11 (#46): the ORM (table.py + knowledge_table.py) and the real schema
(scripts/migrate_*.sql applied to newsaggregator_test) must agree on every
table and every column, in both directions, with a type family that matches.
CLAUDE.md's rule "keep them in sync by hand" now has this to sync against:
a column present in exactly one of {DB, ORM} fails here unless it is in the
explicit allow-list (DB_OWNED_COLUMNS / TOOLING_TABLES in table.py).
"""
import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import inspect  # noqa: E402
from sqlalchemy import types as satypes  # noqa: E402

from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy import knowledge_table  # noqa: E402,F401  (registers its tables on Base)
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.table import (  # noqa: E402
    DB_OWNED_COLUMNS, TOOLING_TABLES, Base,
)


def _family(t) -> str:
    """Coarse type family so bigint vs integer vs smallint all count as
    'integer' (the DatatypeMismatch outages were int-vs-bool, text-vs-json),
    while bool/text/json/timestamp/date/float stay distinct."""
    if isinstance(t, satypes.Boolean):
        return "bool"
    if isinstance(t, (satypes.BigInteger, satypes.SmallInteger, satypes.Integer)):
        return "integer"
    if isinstance(t, (satypes.Float, satypes.Numeric)):
        return "float"
    if isinstance(t, satypes.JSON):
        return "json"
    if isinstance(t, satypes.DateTime):
        return "timestamp"
    if isinstance(t, satypes.Date):
        return "date"
    if isinstance(t, (satypes.String, satypes.Text)):
        return "text"
    return type(t).__name__.lower()


@pytest.fixture(scope="module")
def inspector():
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    c = SQLAlchemyClient()
    try:
        with c.get_session() as s:
            engine = s.get_bind()
            insp = inspect(engine)
            insp.get_table_names()
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    return insp


class TestSchemaMatchesOrm:
    def test_every_db_table_has_a_model_and_vice_versa(self, inspector):
        db_tables = set(inspector.get_table_names()) - TOOLING_TABLES
        orm_tables = set(Base.metadata.tables)
        assert db_tables - orm_tables == set(), f"tables in the DB with no ORM model: {sorted(db_tables - orm_tables)}"
        assert orm_tables - db_tables == set(), f"ORM models with no table in the DB: {sorted(orm_tables - db_tables)}"

    def test_every_column_exists_on_both_sides(self, inspector):
        drift = []
        for name, table in Base.metadata.tables.items():
            db_cols = {c["name"]: c for c in inspector.get_columns(name)}
            orm_cols = {c.name: c for c in table.columns}
            for col in sorted(set(db_cols) - set(orm_cols)):
                if (name, col) not in DB_OWNED_COLUMNS:
                    drift.append(f"{name}.{col}: in DB, not in ORM")
            for col in sorted(set(orm_cols) - set(db_cols)):
                drift.append(f"{name}.{col}: in ORM, not in DB (missing migration?)")
        assert drift == [], "\n".join(drift)

    def test_column_type_families_agree(self, inspector):
        drift = []
        for name, table in Base.metadata.tables.items():
            db_cols = {c["name"]: c["type"] for c in inspector.get_columns(name)}
            for col in table.columns:
                if col.name in db_cols and _family(col.type) != _family(db_cols[col.name]):
                    drift.append(f"{name}.{col.name}: ORM {type(col.type).__name__} vs DB {db_cols[col.name]}")
        assert drift == [], "\n".join(drift)

    def test_allow_list_entries_are_real(self, inspector):
        # An allow-list entry for a column that no longer exists is stale.
        for table, col in DB_OWNED_COLUMNS:
            assert col in {c["name"] for c in inspector.get_columns(table)}, f"{table}.{col} allow-listed but absent"
        for table in TOOLING_TABLES:
            assert table in inspector.get_table_names(), f"{table} allow-listed but absent"
