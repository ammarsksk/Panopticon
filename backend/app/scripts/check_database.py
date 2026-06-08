from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.database import SessionLocal


def main() -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        row = db.execute(
            text(
                """
                select
                    current_database() as database_name,
                    current_user as user_name,
                    inet_server_addr()::text as server_addr,
                    version() as version
                """
            )
        ).mappings().one()
        alembic_version = _alembic_version(db)
        print(f"database_url_type={_url_type(settings.database_url)}")
        print(f"database={row['database_name']}")
        print(f"user={row['user_name']}")
        print(f"server_addr={row['server_addr'] or 'cloud-sql-socket-or-local'}")
        print(f"alembic_version={alembic_version or 'missing'}")
        print(f"postgres_version={str(row['version']).split(',', 1)[0]}")
    finally:
        db.close()


def _url_type(database_url: str) -> str:
    if "host=/cloudsql/" in database_url:
        return "cloud_sql_unix_socket"
    if "127.0.0.1" in database_url or "localhost" in database_url:
        return "local_or_proxy_postgres"
    if database_url.startswith("postgresql"):
        return "postgres"
    if database_url.startswith("sqlite"):
        return "sqlite"
    return "unknown"


def _alembic_version(db) -> str:
    try:
        return str(db.execute(text("select version_num from alembic_version limit 1")).scalar_one_or_none() or "missing")
    except SQLAlchemyError:
        return "missing"


if __name__ == "__main__":
    main()
