"""Apply schema.sql and seed demo data: python -m hub.initdb (needs DATABASE_URL)."""
from . import demo
from .config import get_settings, load_env
from .db import open_store


def main():
    load_env()
    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is empty. Set it in backend/.env first, e.g.\n"
                         "DATABASE_URL=postgresql://postgres:password@localhost:5432/complaints")
    store = open_store(settings.database_url)
    demo.seed(store, settings.author_salt)
    print(f"Database ready. Complaints: {store.overview()['total']}, runs: {store.list_runs()[1]}")


if __name__ == "__main__":
    main()
