"""Write the current catalog to the committed snapshot: ``python -m scripts.export_catalog``."""
from __future__ import annotations

from sqlmodel import Session

from app.config import get_settings
from app.db import get_engine, init_db
from app.services.catalog_snapshot import export_catalog


def main() -> None:
    init_db()
    path = get_settings().catalog_snapshot_path
    with Session(get_engine()) as session:
        n = export_catalog(session, path)
    print(f"Exported {n} products to {path} ({path.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
