import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from dotenv import load_dotenv

from app.models import Base


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "citycity.db"


def _load_env_files() -> None:
    """Load env files in priority order.

    Production deploys should inject environment variables at runtime. Local
    development can use an untracked `.env.development` copied from
    `.env.example`. The legacy `backend/.env` remains a local override.
    """
    candidates = [
        PROJECT_ROOT / ".env.development",
        PROJECT_ROOT / ".env.production",
        Path(__file__).resolve().parents[1] / ".env",
    ]
    for path in candidates:
        if path.is_file():
            load_dotenv(path, override=False)


_load_env_files()


def create_engine_from_env() -> Engine:
    """Create a SQLAlchemy engine from DATABASE_URL.

    Reads `DATABASE_URL` from the environment. When set (EasyLaunch PostgreSQL
    provisioned), connects to PostgreSQL. When unset (local dev without provisioning),
    falls back to a local SQLite file so the project remains runnable offline.
    """
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        if database_url.startswith("sqlite"):
            return create_engine(
                database_url,
                connect_args={"check_same_thread": False},
                future=True,
            )
        # SQLAlchemy 2.0 removed the `postgres://` dialect alias — must be
        # `postgresql://` (or `postgresql+psycopg2://`). EasyLaunch DSNs use
        # `postgres://`, so normalize before handing to create_engine.
        if database_url.startswith("postgres://"):
            database_url = "postgresql://" + database_url[len("postgres://"):]
        return create_engine(database_url, future=True, pool_pre_ping=True)

    DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{DEFAULT_DB_PATH}",
        connect_args={"check_same_thread": False},
        future=True,
    )


def create_sqlite_engine(db_path: str | Path = DEFAULT_DB_PATH) -> Engine:
    """Legacy helper — explicit SQLite path. Prefer create_engine_from_env()."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
        future=True,
    )


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine)
    _run_lightweight_migrations(engine)
    _sync_postgres_sequences(engine)


def _sync_postgres_sequences(engine: Engine) -> None:
    """Sync autoincrement sequences to MAX(id) for all tables.

    PostgreSQL sequences desync when rows are inserted with explicit IDs
    (e.g., during SQLite-to-Postgres data migration). The sequence stays
    at its original value while the table has higher IDs, causing
    UniqueViolation on subsequent inserts.
    """
    if engine.dialect.name != "postgresql":
        return
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text(
            "DO $$\n"
            "DECLARE r RECORD;\n"
            "BEGIN\n"
            "  FOR r IN\n"
            "    SELECT c.relname AS seqname\n"
            "    FROM pg_class c\n"
            "    JOIN pg_namespace n ON n.oid = c.relnamespace\n"
            "    WHERE c.relkind = 'S' AND n.nspname = 'public'\n"
            "  LOOP\n"
            "    BEGIN\n"
            "      EXECUTE format(\n"
            "        'SELECT setval(%L, COALESCE(MAX(id), 0) + 1, false) FROM %I',\n"
            "        r.seqname, replace(r.seqname, '_id_seq', '')\n"
            "      );\n"
            "    EXCEPTION WHEN OTHERS THEN\n"
            "      NULL;\n"
            "    END;\n"
            "  END LOOP;\n"
            "END$$;"
        ))


def _run_lightweight_migrations(engine: Engine) -> None:
    """Add new columns to existing tables that create_all cannot handle.

    create_all only creates missing tables - it does not add columns to
    existing tables. This adds nullable columns introduced after the initial
    schema (user_id on polished_images / image_polish_requests).
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if not inspector.has_table("polished_images"):
        return
    if not inspector.has_table("image_polish_requests"):
        return

    with engine.begin() as conn:
        polished_cols = {col["name"] for col in inspector.get_columns("polished_images")}
        if "user_id" not in polished_cols:
            conn.execute(text("ALTER TABLE polished_images ADD COLUMN user_id VARCHAR(128)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_polished_images_user_id ON polished_images (user_id)"))
        if "created_at" not in polished_cols:
            conn.execute(text("ALTER TABLE polished_images ADD COLUMN created_at TIMESTAMP"))
        if "updated_at" not in polished_cols:
            conn.execute(text("ALTER TABLE polished_images ADD COLUMN updated_at TIMESTAMP"))

        request_cols = {col["name"] for col in inspector.get_columns("image_polish_requests")}
        if "user_id" not in request_cols:
            conn.execute(text("ALTER TABLE image_polish_requests ADD COLUMN user_id VARCHAR(128)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_image_polish_requests_user_id ON image_polish_requests (user_id)"))
        if "created_at" not in request_cols:
            conn.execute(text("ALTER TABLE image_polish_requests ADD COLUMN created_at TIMESTAMP"))
        if "updated_at" not in request_cols:
            conn.execute(text("ALTER TABLE image_polish_requests ADD COLUMN updated_at TIMESTAMP"))

        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_posts_status_created ON posts (status, created_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_post_interactions_post_id ON post_interactions (post_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_places_post_id ON places (post_id)"))


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


engine = create_engine_from_env()
