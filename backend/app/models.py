"""SQLModel database tables. All dimensions are centimeters."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel

CATEGORIES = [
    "sofa",
    "armchair",
    "tv_unit",
    "coffee_table",
    "dining_table",
    "chair",
    "bed",
    "wardrobe",
    "storage",
    "desk",
    "appliance",
    "lighting",
    "decor",
    "other",
]
MODEL_STATUSES = ["none", "generating", "ready", "failed"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Product(SQLModel, table=True):
    __tablename__ = "products"

    id: Optional[int] = Field(default=None, primary_key=True)
    store_name: str = ""
    product_url: str = Field(index=True, unique=True)
    title: str
    category: str = "other"
    price_ils: float = 0.0
    width_cm: float = 50.0
    depth_cm: float = 50.0
    height_cm: float = 50.0
    image_url: str = ""
    model_3d_url: Optional[str] = None
    model_status: str = "none"
    model_error: Optional[str] = None
    updated_at: datetime = Field(default_factory=utcnow)


class Project(SQLModel, table=True):
    __tablename__ = "projects"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = "פרויקט חדש"
    floorplan_image_url: Optional[str] = None
    pixels_per_cm: Optional[float] = None
    scene_json: str = Field(
        default='{"ceilingHeightCm":270,"walls":[],"openings":[],"placedItems":[]}'
    )
    updated_at: datetime = Field(default_factory=utcnow)
