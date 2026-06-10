import argparse

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text

from app.config import get_settings
from app.database import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description="Check and optionally repair repository embedding storage.")
    parser.add_argument("--repair-pgvector", action="store_true", help="Create pgvector extension, embedding column, and HNSW index when using PostgreSQL.")
    args = parser.parse_args()

    settings = get_settings()
    print("Panopticon repository embedding check")
    print("====================================")
    print(f"provider: {settings.repo_embedding_provider}")
    print(f"model: {settings.repo_embedding_model}")
    print(f"dimensions: {settings.repo_embedding_dimensions}")
    print(f"pgvector enabled: {settings.repo_pgvector_enabled}")

    with SessionLocal() as db:
        dialect = db.bind.dialect.name if db.bind is not None else "unknown"
        print(f"database dialect: {dialect}")

        if dialect == "postgresql" and args.repair_pgvector:
            try:
                _repair_pgvector(db, dimensions=settings.repo_embedding_dimensions)
                db.commit()
            except SQLAlchemyError as exc:
                db.rollback()
                print(f"WARN    pgvector repair failed: {exc}")
                print("INFO    Use Cloud SQL PostgreSQL with the vector extension available, then rerun this command.")

        _print_column_state(db, dialect=dialect)
        _print_embedding_counts(db)


def _repair_pgvector(db, *, dimensions: int) -> None:
    print()
    print("Repairing pgvector objects...")
    db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    db.execute(text(f"ALTER TABLE repo_code_chunks ADD COLUMN IF NOT EXISTS embedding_vector vector({int(dimensions)})"))
    db.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_repo_code_chunks_embedding_vector_hnsw "
            "ON repo_code_chunks USING hnsw (embedding_vector vector_cosine_ops)"
        )
    )
    print("OK      pgvector extension, column, and index are present")


def _print_column_state(db, *, dialect: str) -> None:
    print()
    print("Storage")
    print("-------")
    if dialect != "postgresql":
        print("INFO    pgvector column check skipped outside PostgreSQL")
        return

    has_extension = bool(db.execute(text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")).scalar())
    has_column = bool(
        db.execute(
            text(
                "SELECT EXISTS ("
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'repo_code_chunks' AND column_name = 'embedding_vector'"
                ")"
            )
        ).scalar()
    )
    has_index = bool(
        db.execute(
            text(
                "SELECT EXISTS ("
                "SELECT 1 FROM pg_indexes "
                "WHERE tablename = 'repo_code_chunks' AND indexname = 'ix_repo_code_chunks_embedding_vector_hnsw'"
                ")"
            )
        ).scalar()
    )
    print(f"{'OK' if has_extension else 'MISSING'} vector extension")
    print(f"{'OK' if has_column else 'MISSING'} repo_code_chunks.embedding_vector")
    print(f"{'OK' if has_index else 'MISSING'} HNSW cosine index")


def _print_embedding_counts(db) -> None:
    print()
    print("Chunk Embeddings")
    print("----------------")
    try:
        rows = db.execute(
            text(
                "SELECT embedding_provider, embedding_status, COUNT(*) "
                "FROM repo_code_chunks "
                "GROUP BY embedding_provider, embedding_status "
                "ORDER BY embedding_provider, embedding_status"
            )
        ).all()
    except Exception as exc:
        print(f"ERROR   could not read repo_code_chunks: {exc}")
        return

    if not rows:
        print("INFO    no repository chunks indexed yet")
        return
    for provider, status, count in rows:
        print(f"{count:6} {provider or 'unknown':18} {status or 'unknown'}")


if __name__ == "__main__":
    main()
