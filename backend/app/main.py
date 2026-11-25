"""RoomCraft 3D FastAPI application."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select

from .config import get_settings
from .db import get_engine, init_db
from .models import Product
from .routers import clip, floorplans, generation, products, projects
from .services.seed_data import seed_products

log = logging.getLogger("roomcraft")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.floorplans_dir.mkdir(parents=True, exist_ok=True)
    settings.models_dir.mkdir(parents=True, exist_ok=True)
    init_db()
    with Session(get_engine()) as session:
        # A server restart kills in-flight background generations: reset them so they can be retried.
        stuck = session.exec(select(Product).where(Product.model_status == "generating")).all()
        for p in stuck:
            p.model_status = "none"
            session.add(p)
        if stuck:
            session.commit()
        n = seed_products(session)  # no-op unless the table is empty
        if n:
            log.info("Seeded %d products", n)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    settings.floorplans_dir.mkdir(parents=True, exist_ok=True)
    settings.models_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="RoomCraft 3D API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health():
        s = get_settings()
        return {"status": "ok", "image_to_3d_provider": s.image_to_3d_provider}

    app.include_router(clip.router)
    app.include_router(products.router)
    app.include_router(generation.router)
    app.include_router(projects.router)
    app.include_router(floorplans.router)
    app.mount("/static", StaticFiles(directory=str(settings.storage_path)), name="static")
    return app


app = create_app()
