"""Dev tool: write one sample GLB per product type to ``storage/models/gallery/`` for visual review.

    python -m scripts.model_gallery

View them in the app with ``http://localhost:5173/?gallery`` (dev server only). Nothing here touches the database.
"""
from __future__ import annotations

import json
import sys

from app.config import get_settings
from app.services.procedural import Palette, build_model

# (label, category, width, depth, height, title, main colour, accent colour)
SPECS: list[tuple[str, str, float, float, float, str, tuple, tuple]] = [
    ("ספה 3 מושבים ירוקה", "sofa", 220, 92, 82, "ספה תלת מושבית", (92, 128, 88), (150, 110, 75)),
    ("ספה פינתית אפורה", "sofa", 300, 165, 85, "ספה פינתית מודולרית", (122, 126, 132), (60, 60, 64)),
    ("ספה 2 מושבים כחולה", "sofa", 180, 88, 80, "ספה דו מושבית", (60, 90, 140), (180, 140, 100)),
    ("כורסה בז'", "armchair", 78, 82, 88, "כורסה", (190, 170, 145), (110, 78, 58)),
    ("כסא אוכל 1", "chair", 44, 50, 88, "כיסא אוכל", (200, 190, 175), (130, 95, 65)),
    ("כסא אוכל 2", "chair", 46, 52, 84, "כיסא אוכל", (70, 74, 80), (50, 50, 52)),
    ("כסא אוכל 3", "chair", 45, 50, 90, "כיסא אוכל", (150, 70, 60), (150, 110, 75)),
    ("שולחן אוכל", "dining_table", 180, 90, 75, "שולחן אוכל", (200, 168, 130), (96, 66, 46)),
    ("שולחן אוכל עגול לבן", "dining_table", 110, 110, 75, "שולחן אוכל עגול", (240, 240, 242), (190, 160, 120)),
    ("שולחן סלון", "coffee_table", 100, 55, 40, "שולחן סלון", (210, 180, 140), (60, 56, 52)),
    ("שולחן עבודה", "desk", 140, 70, 74, "שולחן עבודה", (225, 225, 228), (80, 80, 84)),
    ("מיטה זוגית", "bed", 180, 210, 105, "מיטה זוגית מרופדת", (150, 150, 158), (200, 170, 140)),
    ("מיטה וחצי", "bed", 140, 200, 95, "מיטה", (190, 160, 125), (150, 110, 75)),
    ("ארון בגדים לבן", "wardrobe", 200, 60, 236, "ארון בגדים PAX", (240, 240, 242), (140, 140, 145)),
    ("ארון הזזה מראה", "wardrobe", 250, 62, 230, "ארון הזזה עם מראה", (225, 218, 208), (120, 120, 125)),
    ("שידת מגירות", "storage", 90, 47, 95, "שידת 5 מגירות", (200, 170, 130), (96, 66, 46)),
    ("מזנון", "storage", 160, 40, 75, "מזנון דלתות", (120, 150, 150), (160, 120, 80)),
    ("שידת לילה", "storage", 45, 38, 52, "שידת לילה", (235, 235, 235), (160, 120, 80)),
    ("ספרייה", "storage", 80, 28, 202, "ספרייה BILLY", (245, 245, 245), (120, 120, 120)),
    ("מזנון טלוויזיה", "tv_unit", 180, 40, 50, "מזנון טלוויזיה", (190, 150, 110), (60, 50, 45)),
    ("מנורת עמידה", "lighting", 38, 38, 150, "מנורת עמידה", (240, 232, 205), (70, 70, 74)),
    ("מנורת תלייה", "lighting", 50, 50, 45, "מנורת תלייה", (225, 200, 150), (60, 60, 64)),
    ("מקרר", "appliance", 91, 74, 178, "מקרר דלתות צד", (205, 208, 212), (150, 154, 160)),
    ("מכונת כביסה", "appliance", 60, 55, 85, "מכונת כביסה", (240, 242, 244), (150, 154, 160)),
    ("תנור", "appliance", 60, 55, 60, "תנור בנוי", (80, 84, 90), (180, 184, 190)),
    ("שטיח עגול", "decor", 160, 160, 2, "שטיח עגול", (170, 140, 110), (230, 220, 200)),
    ("מראה", "decor", 120, 4, 120, "מראה", (210, 190, 160), (150, 120, 90)),
    ("עציץ", "decor", 40, 40, 110, "עציץ", (190, 120, 90), (62, 130, 72)),
]


def main() -> None:
    out_dir = get_settings().models_dir / "gallery"
    out_dir.mkdir(parents=True, exist_ok=True)
    index = []
    for i, (label, cat, w, d, h, title, main_c, accent_c) in enumerate(SPECS):
        scene = build_model(cat, w, d, h, Palette(tuple(main_c), tuple(accent_c)), title, seed=i + 1)
        (out_dir / f"{i}.glb").write_bytes(scene.export(file_type="glb"))
        index.append({"i": i, "label": label, "w": w, "d": d, "h": h})
    (out_dir / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(SPECS)} models to {out_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
