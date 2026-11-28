"""Optional room-label reader: finds Hebrew room names written on a floorplan ("ח.שינה", "ח.רחצה", ...).

Uses the Tesseract CLI when it is installed WITH Hebrew data (no Python dependency). If it is missing, or
anything fails, an empty list is returned and the app falls back to size/shape heuristics for naming rooms.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Optional

log = logging.getLogger("roomcraft.ocr")

_HEB = re.compile(r"[\u05d0-\u05ea]")
_WINDOWS_DEFAULT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# room kind -> Hebrew stems (OCR is noisy, so matching is fuzzy)
STEMS: list[tuple[str, tuple[str, ...]]] = [
    ("master", ("הורים",)),
    ("bedroom", ("שינה", "שנה")),
    ("bathroom", ("רחצה", "אמבטיה", "מקלחת", "רחץ")),
    ("toilet", ("שירותים", "שרותים")),
    ("laundry", ("כביסה", "כביסת")),
    ("living", ("דיור", "סלון", "מגורים", "אירוח")),
    ("dining", ("אוכל",)),
    ("kitchen", ("מטבח",)),
    ("balcony", ("מרפסת", "מרפסות")),
    ("closet", ("מלתחה", "ארונות")),
    ("hallway", ("מסדרון", "מבואה", "פרוזדור")),
    ("storage", ("מחסן",)),
    ("office", ("משרד", "עבודה")),
    ("kids", ("ילדים",)),
]


@dataclass
class Word:
    text: str
    conf: float
    left: float
    top: float
    width: float
    height: float
    line: tuple[int, int, int, int]  # (block, paragraph, line) ids


@dataclass
class RoomHint:
    kinds: list[str]
    text: str
    x_px: float
    y_px: float
    kinds_conf: float = 0.0
    extra: dict = field(default_factory=dict)


def tesseract_cmd() -> Optional[str]:
    found = shutil.which("tesseract")
    if found:
        return found
    return _WINDOWS_DEFAULT if Path(_WINDOWS_DEFAULT).exists() else None


@lru_cache(maxsize=1)
def hebrew_available() -> bool:
    cmd = tesseract_cmd()
    if not cmd:
        return False
    try:
        out = subprocess.run([cmd, "--list-langs"], capture_output=True, text=True, timeout=20)
        return "heb" in (out.stdout + out.stderr).split()
    except Exception:  # noqa: BLE001
        return False


def read_words(image_path: Path, timeout: float = 90.0) -> list[Word]:
    """Run Tesseract (Hebrew + English, sparse text mode) and return recognised words with positions."""
    cmd = tesseract_cmd()
    if not cmd or not hebrew_available():
        return []
    try:
        out = subprocess.run(
            [cmd, str(image_path), "stdout", "-l", "heb+eng", "--psm", "11", "tsv"],
            capture_output=True,
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        log.info("tesseract failed: %s", exc)
        return []
    text = out.stdout.decode("utf-8", errors="replace")
    words: list[Word] = []
    for row in csv.DictReader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE):
        try:
            t = (row.get("text") or "").strip()
            conf = float(row.get("conf") or -1)
            if not t or conf < 30:
                continue
            words.append(
                Word(
                    t, conf, float(row["left"]), float(row["top"]), float(row["width"]), float(row["height"]),
                    (int(row["block_num"]), int(row["par_num"]), int(row["line_num"])),
                )
            )
        except (KeyError, ValueError):
            continue
    return words


def _norm(token: str) -> str:
    return "".join(_HEB.findall(token))


def match_kind(token: str) -> Optional[str]:
    """Fuzzy-match one OCR token against the room-name stems.

    A token like "מ.קביסה." is also tried part by part ("קביסה"), since plans abbreviate with "ח." / "מ.".
    """
    parts = [p for p in re.split(r"[^א-ת]+", token) if len(p) >= 3]
    for candidate in [token, *parts]:
        kind = _match_one(candidate)
        if kind:
            return kind
    return None


def _match_one(token: str) -> Optional[str]:
    t = _norm(token)
    if len(t) < 3:
        return None
    best: tuple[float, str] = (0.0, "")
    for kind, stems in STEMS:
        for stem in stems:
            ratio = 1.0 if (stem in t and len(t) <= len(stem) + 2) else SequenceMatcher(None, t, stem).ratio()
            if ratio > best[0]:
                best = (ratio, kind)
    return best[1] if best[0] >= 0.74 else None


def group_hints(words: list[Word]) -> list[RoomHint]:
    """Group words that sit on the same text line into phrases and keep those naming a room."""
    lines: dict[tuple, list[Word]] = {}
    for w in words:
        lines.setdefault(w.line, []).append(w)
    hints: list[RoomHint] = []
    for ws in lines.values():
        ws.sort(key=lambda w: w.left)
        # split a tesseract line into runs of nearby words (gap < 1.8 x text height)
        runs: list[list[Word]] = [[ws[0]]]
        for w in ws[1:]:
            prev = runs[-1][-1]
            if w.left - (prev.left + prev.width) < 3.0 * max(w.height, prev.height):
                runs[-1].append(w)
            else:
                runs.append([w])
        for run in runs:
            kinds: list[str] = []
            for w in run:
                k = match_kind(w.text)
                if k and k not in kinds:
                    kinds.append(k)
            if not kinds:
                continue
            x0 = min(w.left for w in run)
            x1 = max(w.left + w.width for w in run)
            y0 = min(w.top for w in run)
            y1 = max(w.top + w.height for w in run)
            hints.append(
                RoomHint(kinds, " ".join(w.text for w in run), (x0 + x1) / 2, (y0 + y1) / 2,
                         sum(w.conf for w in run) / len(run))
            )
    return hints


def room_hints(image_path: Path) -> list[RoomHint]:
    """Room-name hints in image-pixel coordinates (empty when OCR is unavailable)."""
    try:
        return group_hints(read_words(image_path))
    except Exception as exc:  # noqa: BLE001
        log.info("room hint extraction failed: %s", exc)
        return []


# ----------------------------------------------------------------------------- window dimension labels

@dataclass
class DimLabel:
    """A window label such as "100 / 200 / (+30)": width, height and sill height in cm, in image pixels."""

    x_px: float
    y_px: float
    sill_cm: float
    width_cm: Optional[float] = None
    height_cm: Optional[float] = None


_SILL = re.compile(r"^\(?\+(\d{2,3})\)?$")
_NUM = re.compile(r"^\d{2,3}$")
_DIM_SCALE = 2  # tesseract reads small dimension text far better when enlarged
_DIM_ROTATIONS = (0, 270, 90)  # PIL angles: upright, then text that reads bottom-to-top / top-to-bottom


def _tsv_words(img, cmd: str) -> list[Word]:
    import tempfile

    from PIL import Image  # noqa: F401  (type of img)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "dim.png"
        img.save(path)
        try:
            out = subprocess.run([cmd, str(path), "stdout", "-l", "eng", "--psm", "11", "tsv"], capture_output=True, timeout=60)
        except Exception as exc:  # noqa: BLE001
            log.info("tesseract (dimension pass) failed: %s", exc)
            return []
    words: list[Word] = []
    for row in csv.DictReader(io.StringIO(out.stdout.decode("utf-8", errors="replace")), delimiter="\t", quoting=csv.QUOTE_NONE):
        try:
            t = (row.get("text") or "").strip().strip("_-.,;:")
            if t and float(row.get("conf") or -1) >= 30:
                words.append(Word(t, float(row["conf"]), float(row["left"]), float(row["top"]), float(row["width"]), float(row["height"]), (0, 0, 0)))
        except (KeyError, ValueError):
            continue
    return words


def _labels_from_words(words: list[Word]) -> list[tuple[float, float, DimLabel]]:
    """Sill tokens "(+30)" plus the two numbers stacked right above them -> (centre x, centre y, label)."""
    nums = [w for w in words if _NUM.match(w.text)]
    out: list[tuple[float, float, DimLabel]] = []
    for w in words:
        m = _SILL.match(w.text)
        if not m or not (10 <= int(m.group(1)) <= 250):
            continue
        cx, cy = w.left + w.width / 2, w.top + w.height / 2
        sill = float(m.group(1))
        height = width = None
        for n in nums:
            dx = abs(n.left + n.width / 2 - cx)
            dy = cy - (n.top + n.height / 2)
            if dx > 0.6 * w.width or not 0 < dy <= 2.6 * w.height or n.height > 1.3 * w.height:
                continue  # (a much taller box is two stacked lines merged into one bogus token)
            row = round(dy / (1.1 * w.height))  # the stack is: width row, height row, sill row (bottom)
            value = float(n.text)
            if row == 1 and 40 <= value <= 260 and sill + value <= 280:
                height = value
            elif row == 2 and 40 <= value <= 400:
                width = value
        out.append((cx, cy, DimLabel(0.0, 0.0, sill, width, height)))
    return out


def dimension_labels(image_path: Path) -> list[DimLabel]:
    """Window labels printed in the margins of a plan: "width / height (+sill)" (needs Tesseract; else empty)."""
    cmd = tesseract_cmd()
    if not cmd:
        return []
    try:
        from concurrent.futures import ThreadPoolExecutor

        from PIL import Image

        with Image.open(image_path) as im:
            gray = im.convert("L")
        w0, h0 = gray.size
        big = gray.resize((w0 * _DIM_SCALE, h0 * _DIM_SCALE), Image.LANCZOS)

        def one(angle: int) -> list[DimLabel]:
            img = big if angle == 0 else big.rotate(angle, expand=True)
            found: list[DimLabel] = []
            for cx, cy, lab in _labels_from_words(_tsv_words(img, cmd)):
                cx, cy = cx / _DIM_SCALE, cy / _DIM_SCALE
                if angle == 270:  # image rotated clockwise: (x', y') = (H - y, x)
                    lab.x_px, lab.y_px = cy, h0 - cx
                elif angle == 90:  # rotated counter-clockwise: (x', y') = (y, W - x)
                    lab.x_px, lab.y_px = w0 - cy, cx
                else:
                    lab.x_px, lab.y_px = cx, cy
                found.append(lab)
            return found

        with ThreadPoolExecutor(max_workers=len(_DIM_ROTATIONS)) as pool:
            batches = list(pool.map(one, _DIM_ROTATIONS))
    except Exception as exc:  # noqa: BLE001
        log.info("dimension label extraction failed: %s", exc)
        return []
    merged: list[DimLabel] = []
    for lab in (l for batch in batches for l in batch):  # the same label can be read by two passes
        if not any(abs(m.x_px - lab.x_px) < 12 and abs(m.y_px - lab.y_px) < 12 for m in merged):
            merged.append(lab)
    return merged
