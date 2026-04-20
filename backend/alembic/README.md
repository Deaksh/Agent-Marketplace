Alembic migrations live in `backend/alembic/versions/`.

For now, the app still supports lightweight SQLite schema evolution in `app/db/session.py` for quick dev.
When moving to Postgres+pgvector in production, prefer Alembic migrations for schema changes.

