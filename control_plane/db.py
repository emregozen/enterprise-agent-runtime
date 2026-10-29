from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from shared.config import get_settings


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


class Base(DeclarativeBase):
    pass


_engine = None
_Session: sessionmaker[Session] | None = None


def get_engine():
    global _engine, _Session
    if _engine is None:
        url = get_settings().database_url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, pool_pre_ping=True, future=True, connect_args=connect_args)
        _Session = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def SessionLocal() -> Session:
    get_engine()
    assert _Session is not None
    return _Session()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def reset_engine() -> None:
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _Session = None


def init_db() -> None:
    from control_plane import models  # noqa: F401

    engine = get_engine()
    Base.metadata.create_all(engine)
    from control_plane.migrate import apply_migrations

    with engine.begin() as conn:
        apply_migrations(conn)
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE OR REPLACE FUNCTION agentrt_forbid_audit_mutation() RETURNS trigger AS $$
                    BEGIN
                      RAISE EXCEPTION 'audit_events is append-only';
                    END;
                    $$ LANGUAGE plpgsql
                    """
                )
            )
            conn.execute(text("DROP TRIGGER IF EXISTS audit_events_no_update ON audit_events"))
            conn.execute(
                text(
                    """
                    CREATE TRIGGER audit_events_no_update
                    BEFORE UPDATE OR DELETE ON audit_events
                    FOR EACH ROW EXECUTE FUNCTION agentrt_forbid_audit_mutation()
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_artifacts_created_at ON artifacts (created_at)"))
    elif engine.dialect.name == "sqlite":
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS audit_events_no_update
                    BEFORE UPDATE ON audit_events
                    BEGIN
                      SELECT RAISE(ABORT, 'audit_events is append-only');
                    END
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
                    BEFORE DELETE ON audit_events
                    BEGIN
                      SELECT RAISE(ABORT, 'audit_events is append-only');
                    END
                    """
                )
            )
