"""Seed the products table: ``python -m scripts.seed [--force]``."""
from __future__ import annotations

import sys

from sqlmodel import Session

from app.db import get_engine, init_db
from app.services.seed_data import seed_products


def main() -> None:
    init_db()
    with Session(get_engine()) as session:
        n = seed_products(session, force="--force" in sys.argv)
    print(f"Inserted {n} product(s).")


if __name__ == "__main__":
    main()
