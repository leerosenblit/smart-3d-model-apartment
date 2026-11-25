"""Pydantic request/response models."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from .models import CATEGORIES

ModelStatus = Literal["none", "generating", "ready", "failed"]


class ProductBase(BaseModel):
    store_name: str = ""
    product_url: str
    title: str
    category: str = "other"
    price_ils: float = Field(default=0.0, ge=0)
    width_cm: float = Field(default=50.0, gt=0)
    depth_cm: float = Field(default=50.0, gt=0)
    height_cm: float = Field(default=50.0, gt=0)
    image_url: str = ""

    @field_validator("category")
    @classmethod
    def _category(cls, v: str) -> str:
        return v if v in CATEGORIES else "other"


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    store_name: Optional[str] = None
    product_url: Optional[str] = None
    title: Optional[str] = None
    category: Optional[str] = None
    price_ils: Optional[float] = Field(default=None, ge=0)
    width_cm: Optional[float] = Field(default=None, gt=0)
    depth_cm: Optional[float] = Field(default=None, gt=0)
    height_cm: Optional[float] = Field(default=None, gt=0)
    image_url: Optional[str] = None


class ProductRead(ProductBase):
    id: int
    model_3d_url: Optional[str] = None
    model_status: ModelStatus = "none"
    model_error: Optional[str] = None
    updated_at: datetime


class ModelStatusRead(BaseModel):
    id: int
    model_status: ModelStatus
    model_3d_url: Optional[str] = None
    model_error: Optional[str] = None


class IngestUrlRequest(BaseModel):
    url: str


class IngestBatchRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=100)


class IngestResult(BaseModel):
    url: str
    status: Literal["created", "updated", "failed"]
    source: Optional[str] = None
    product: Optional[ProductRead] = None
    error: Optional[str] = None


class Scene(BaseModel):
    ceilingHeightCm: float = 270
    walls: list[dict[str, Any]] = Field(default_factory=list)
    openings: list[dict[str, Any]] = Field(default_factory=list)
    placedItems: list[dict[str, Any]] = Field(default_factory=list)
    roomStyles: list[dict[str, Any]] = Field(default_factory=list)


class ProjectCreate(BaseModel):
    name: str = "פרויקט חדש"
    floorplan_image_url: Optional[str] = None
    pixels_per_cm: Optional[float] = None
    scene: Scene = Field(default_factory=Scene)


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    floorplan_image_url: Optional[str] = None
    pixels_per_cm: Optional[float] = None
    scene: Optional[Scene] = None


class ProjectRead(BaseModel):
    id: int
    name: str
    floorplan_image_url: Optional[str] = None
    pixels_per_cm: Optional[float] = None
    scene: Scene
    updated_at: datetime

    @classmethod
    def from_db(cls, p) -> "ProjectRead":
        try:
            scene = Scene(**json.loads(p.scene_json or "{}"))
        except Exception:
            scene = Scene()
        return cls(
            id=p.id,
            name=p.name,
            floorplan_image_url=p.floorplan_image_url,
            pixels_per_cm=p.pixels_per_cm,
            scene=scene,
            updated_at=p.updated_at,
        )


class ProjectSummary(BaseModel):
    id: int
    name: str
    updated_at: datetime


class FloorplanUploadResult(BaseModel):
    url: str
    width_px: int
    height_px: int


class DetectWallsRequest(BaseModel):
    url: str
    # None = estimate the scale automatically from the typical wall thickness
    pixels_per_cm: Optional[float] = Field(default=None, gt=0)


class DetectedOpeningRead(BaseModel):
    kind: Literal["door", "window"]
    offsetCm: float
    widthCm: float
    heightCm: float
    sillCm: float


class DetectedWallRead(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float
    thicknessCm: float
    openings: list[DetectedOpeningRead] = Field(default_factory=list)


class RoomHintRead(BaseModel):
    kinds: list[str]
    text: str
    x_cm: float
    y_cm: float


class DetectWallsResult(BaseModel):
    walls: list[DetectedWallRead]
    room_hints: list[RoomHintRead] = Field(default_factory=list)
    pixels_per_cm: Optional[float] = None
    scale_estimated: bool = False
