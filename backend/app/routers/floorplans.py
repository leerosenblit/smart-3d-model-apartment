"""Floorplan upload. PDFs are rendered (page 1) to PNG so the editor always gets an image."""
from __future__ import annotations

import io
import uuid

from pathlib import PurePosixPath

from fastapi import APIRouter, HTTPException, UploadFile

from ..config import get_settings
from ..schemas import DetectedWallRead, DetectWallsRequest, DetectWallsResult, FloorplanUploadResult, RoomHintRead
from ..services import ocr_labels
from ..services.wall_detect import detect_walls_auto

router = APIRouter(prefix="/api/floorplans", tags=["floorplans"])

PDF_DPI = 200


def _sniff(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"%PDF"):
        return "pdf"
    if data[:2] == b"BM" or data[:4] in (b"GIF8", b"II*\x00", b"MM\x00*"):
        return "other"  # BMP / GIF / TIFF: converted to PNG below
    return None


def _image_size(data: bytes) -> tuple[int, int]:
    from PIL import Image  # pulled in by pymupdf/trimesh deps; optional

    with Image.open(io.BytesIO(data)) as im:
        return im.size


def _render_pdf(data: bytes) -> tuple[bytes, int, int]:
    import pymupdf

    with pymupdf.open(stream=data, filetype="pdf") as doc:
        if doc.page_count == 0:
            raise ValueError("PDF has no pages")
        pix = doc[0].get_pixmap(dpi=PDF_DPI, alpha=False)
        return pix.tobytes("png"), pix.width, pix.height


@router.post("/upload", response_model=FloorplanUploadResult)
async def upload_floorplan(file: UploadFile):
    settings = get_settings()
    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File too large (max {settings.max_upload_mb} MB)")
    kind = _sniff(data)
    if kind is None:
        raise HTTPException(415, "Unsupported file type. Use PNG, JPG, WebP, BMP, GIF, TIFF or PDF.")

    width = height = 0
    if kind == "pdf":
        try:
            data, width, height = _render_pdf(data)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(422, f"Could not render PDF: {exc}") from exc
        kind = "png"
    elif kind == "other":
        try:
            from PIL import Image

            with Image.open(io.BytesIO(data)) as im:
                im.seek(0)
                out = io.BytesIO()
                im.convert("RGB").save(out, "PNG")
                width, height = im.size
            data, kind = out.getvalue(), "png"
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(422, f"Could not read image: {exc}") from exc
    else:
        try:
            width, height = _image_size(data)
        except Exception:  # noqa: BLE001 - size is best-effort
            width = height = 0

    settings.floorplans_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{kind}"
    (settings.floorplans_dir / name).write_bytes(data)
    return FloorplanUploadResult(url=f"/static/floorplans/{name}", width_px=width, height_px=height)


@router.post("/detect-walls", response_model=DetectWallsResult)
def detect_floorplan_walls(body: DetectWallsRequest):
    """Heuristically detect axis-aligned walls (and door/window gaps) in an uploaded floorplan.

    Coordinates are returned in centimeters with the image's top-left corner as the origin,
    matching how the 2D editor places the floorplan.
    """
    from PIL import Image

    name = PurePosixPath(body.url).name  # basename only: no path traversal
    path = get_settings().floorplans_dir / name
    if not body.url.startswith("/static/floorplans/") or not name or not path.is_file():
        raise HTTPException(404, "Floorplan not found")
    from concurrent.futures import ThreadPoolExecutor

    # OCR (room names printed on the plan; needs Tesseract + Hebrew data, else empty) runs in parallel
    with ThreadPoolExecutor(max_workers=1) as pool:
        ocr_future = pool.submit(ocr_labels.room_hints, path)
        try:
            with Image.open(path) as im:
                walls, ppc, estimated = detect_walls_auto(im, body.pixels_per_cm)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(422, f"Could not analyse floorplan: {exc}") from exc
        raw_hints = ocr_future.result()
    hints: list[RoomHintRead] = []
    if ppc and walls:
        hints = [
            RoomHintRead(kinds=h.kinds, text=h.text, x_cm=h.x_px / ppc, y_cm=h.y_px / ppc) for h in raw_hints
        ]
    return DetectWallsResult(
        walls=[DetectedWallRead(**w.__dict__) for w in walls],
        room_hints=hints,
        pixels_per_cm=ppc,
        scale_estimated=estimated,
    )
