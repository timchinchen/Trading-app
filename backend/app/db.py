from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import settings

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


# foreign_keys is per-connection in SQLite, not a database attribute, so
# setting it once at init_db() is lost on every subsequent connection. We
# attach a connect listener instead so every pooled connection gets the
# pragma when it's first opened. WAL + synchronous are durable DB-level
# settings, handled separately in _apply_sqlite_pragmas().
if engine.url.get_backend_name().startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_per_connection_pragmas(dbapi_conn, _):  # pragma: no cover
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


# ----------------------------------------------------------------------------
# Simple additive SQLite migration:
# Base.metadata.create_all only creates missing *tables*. When we add a column
# to an existing model, older SQLite files end up missing that column and
# every query that SELECTs it blows up with "no such column". For small local
# apps we don't want Alembic overhead, so we just diff the live schema against
# the model metadata and ALTER TABLE ADD COLUMN for anything new. This is
# safe because we only *add* nullable/default columns; we never drop or
# rename. Anything more complex should be handled manually.
# ----------------------------------------------------------------------------
def _sync_missing_columns() -> None:
    if not engine.url.get_backend_name().startswith("sqlite"):
        return
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # create_all will make it
            live_cols = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in live_cols:
                    continue
                col_type = col.type.compile(dialect=engine.dialect)
                default_sql = ""
                if col.default is not None and getattr(col.default, "is_scalar", False):
                    # Literal scalar default (e.g. 0, "x"). SQLAlchemy datetime
                    # defaults are callables and can't be translated to SQL;
                    # we skip those and rely on the ORM to fill in at insert.
                    val = col.default.arg
                    if isinstance(val, (int, float)):
                        default_sql = f" DEFAULT {val}"
                    elif isinstance(val, str):
                        default_sql = f" DEFAULT '{val}'"
                null_sql = "" if col.nullable else " NOT NULL"
                stmt = f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col_type}{default_sql}{null_sql}'
                try:
                    conn.execute(text(stmt))
                    print(f"[db-migrate] added {table.name}.{col.name}")
                except Exception as e:
                    # NOT NULL without a safe default fails on existing rows;
                    # fall back to allowing NULL so the app keeps running.
                    if null_sql:
                        fallback = f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col_type}{default_sql}'
                        try:
                            conn.execute(text(fallback))
                            print(
                                f"[db-migrate] added {table.name}.{col.name} "
                                f"(relaxed NOT NULL): {e}"
                            )
                            continue
                        except Exception as e2:
                            print(f"[db-migrate] failed to add {table.name}.{col.name}: {e2}")
                    else:
                        print(f"[db-migrate] failed to add {table.name}.{col.name}: {e}")


def _apply_sqlite_pragmas() -> None:
    """Flip the SQLite file into WAL + lower-durability-sync mode.

    WAL lets readers (Agent UI polling) proceed while the scheduler writes
    digest/agent_run rows, fixing the intermittent `database is locked`
    stalls on laptop-grade hardware. synchronous=NORMAL is safe with WAL
    and noticeably faster for our write pattern. These are durable DB-
    level pragmas (they persist between connections) so we only set them
    once here; foreign_keys is per-connection and lives in the connect
    listener on `engine` above.
    """
    if not engine.url.get_backend_name().startswith("sqlite"):
        return
    try:
        with engine.begin() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA synchronous=NORMAL"))
        print("[db] sqlite pragmas applied (journal=WAL, synchronous=NORMAL, foreign_keys=ON per-conn)")
    except Exception as e:
        print(f"[db] pragma setup failed: {e}")


def init_db() -> None:
    from . import models  # noqa: F401  ensure models registered
    _apply_sqlite_pragmas()
    Base.metadata.create_all(bind=engine)
    _sync_missing_columns()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
