"""Heuristic wall detection from a floorplan image (numpy + Pillow only).

Works best on architectural plans where walls are drawn as thick filled strokes
(solid black/grey or coloured hatching such as blue concrete / orange block walls).

Pipeline:
 1. mask of "wall ink": strongly coloured or very dark pixels
 2. morphological opening with thick-and-long rectangles keeps walls and removes thin
    text, dimension lines, furniture outlines and door-swing arcs (axis-aligned walls only)
 3. connected components -> rectangles -> centre-line walls (cm)
 4. collinear walls separated by a 45-260 cm gap become one wall with a door/window opening
 5. wall ends that touch a perpendicular wall are snapped onto its centre-line

All distances are centimeters; ``pixels_per_cm`` converts from image pixels.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image

MIN_THICKNESS_CM = 8.0
MAX_THICKNESS_CM = 70.0
MIN_LENGTH_CM = 45.0
MIN_GAP_CM = 45.0
MAX_GAP_CM = 360.0  # wide glass/sliding doors to terraces are often 2.4-3.5 m
DOOR_MAX_CM = 110.0
WIDE_DOOR_CM = 200.0


@dataclass
class DetectedOpening:
    kind: str  # 'door' | 'window'
    center: float  # absolute position along the wall axis (cm)
    width: float
    evidence: str = "width"  # what decided the kind: 'arc' | 'glazing' | 'context' | 'width'


@dataclass
class _Rect:
    orient: str  # 'h' (runs along x) | 'v' (runs along y)
    a0: float  # start along the axis
    a1: float
    cc: float  # centre-line coordinate on the perpendicular axis
    t: float  # thickness
    openings: list[DetectedOpening] = field(default_factory=list)
    thin: bool = False  # found as hollow/single thin lines (not a solid filled wall)


@dataclass
class DetectedWall:
    x1: float
    y1: float
    x2: float
    y2: float
    thicknessCm: float
    openings: list[dict] = field(default_factory=list)  # {kind, offsetCm, widthCm, heightCm, sillCm}
    thin: bool = False


# ----------------------------------------------------------------------------- morphology

def _window_sums(m: np.ndarray, kh: int, kw: int) -> np.ndarray:
    ii = np.zeros((m.shape[0] + 1, m.shape[1] + 1), dtype=np.int32)
    ii[1:, 1:] = m.astype(np.int32).cumsum(0).cumsum(1)
    return ii[kh:, kw:] - ii[:-kh, kw:] - ii[kh:, :-kw] + ii[:-kh, :-kw]


def _open(mask: np.ndarray, kh: int, kw: int) -> np.ndarray:
    """Binary opening with a kh x kw rectangle (erode then dilate)."""
    h, w = mask.shape
    if kh > h or kw > w:
        return np.zeros_like(mask)
    core = _window_sums(mask, kh, kw) == kh * kw  # anchored top-left
    ch, cw = core.shape
    padded = np.zeros((h + kh - 1, w + kw - 1), dtype=bool)
    padded[kh - 1: kh - 1 + ch, kw - 1: kw - 1 + cw] = core
    return _window_sums(padded, kh, kw) > 0


def _components(mask: np.ndarray) -> list[tuple[int, int, int, int, int]]:
    """Run-based connected components -> (x0, y0, x1, y1, area), x1/y1 exclusive."""
    parent: list[int] = []
    stats: list[list[int]] = []

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    prev: list[tuple[int, int, int]] = []
    for y in range(mask.shape[0]):
        row = mask[y]
        if not row.any():
            prev = []
            continue
        d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
        starts = np.flatnonzero(d == 1).tolist()
        ends = np.flatnonzero(d == -1).tolist()
        cur: list[tuple[int, int, int]] = []
        for s, e in zip(starts, ends):
            rid = len(parent)
            parent.append(rid)
            stats.append([s, y, e, y + 1, e - s])
            for ps, pe, pid in prev:
                if ps < e and s < pe:
                    ra, rb = find(rid), find(pid)
                    if ra != rb:
                        parent[ra] = rb
            cur.append((s, e, rid))
        prev = cur

    agg: dict[int, list[int]] = {}
    for i, st in enumerate(stats):
        r = find(i)
        if r not in agg:
            agg[r] = list(st)
        else:
            a = agg[r]
            a[0], a[1] = min(a[0], st[0]), min(a[1], st[1])
            a[2], a[3] = max(a[2], st[2]), max(a[3], st[3])
            a[4] += st[4]
    return [tuple(v) for v in agg.values()]  # type: ignore[misc]


# ----------------------------------------------------------------------------- detection

def wall_mask(img: Image.Image) -> np.ndarray:
    rgb = np.asarray(img.convert("RGB")).astype(np.int32)  # int32: luminance sums overflow int16
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    lum = (rgb[..., 0] * 299 + rgb[..., 1] * 587 + rgb[..., 2] * 114) // 1000
    # pale wall fills (e.g. light blue ~ (130,147,210)) still have clear chroma; paper/text/furniture do not
    ink = ((mx - mn) > 38) | (lum < 110)
    # morphological closing (opening of the complement) fills pin-holes and hatch gaps inside walls
    return ~_open(~ink, 3, 3)


def _rects_from_mask(cand: np.ndarray, orient: str, ppc: float, t_min: int, t_max: int, l_min: int) -> list[_Rect]:
    out: list[_Rect] = []
    for x0, y0, x1, y1, area in _components(cand):
        w, h = x1 - x0, y1 - y0
        length, thick = (w, h) if orient == "h" else (h, w)
        if length < l_min or thick < t_min or thick > t_max:
            continue
        if area / float(w * h) < 0.6:
            continue
        t_cm = (area / float(length)) / ppc
        if orient == "h":
            out.append(_Rect("h", x0 / ppc, x1 / ppc, (y0 + y1) / 2 / ppc, t_cm))
        else:
            out.append(_Rect("v", y0 / ppc, y1 / ppc, (x0 + x1) / 2 / ppc, t_cm))
    return out


def _bridge_gaps(rects: list[_Rect]) -> list[_Rect]:
    """Merge collinear walls across door/window-sized gaps, recording an opening for each gap."""
    rects = list(rects)
    while True:
        best: tuple[float, int, int] | None = None
        for i, a in enumerate(rects):
            for j, b in enumerate(rects):
                if i == j or a.orient != b.orient or b.a0 < a.a1:
                    continue
                gap = b.a0 - a.a1
                if not (MIN_GAP_CM <= gap <= MAX_GAP_CM):
                    continue
                if abs(a.cc - b.cc) > 6 + 0.25 * max(a.t, b.t):
                    continue
                if min(a.t, b.t) < 0.6 * max(a.t, b.t):
                    continue
                cc = (a.cc + b.cc) / 2
                # a perpendicular wall crossing the gap means a junction, not an opening
                blocked = any(
                    p.orient != a.orient and a.a1 - 5 <= p.cc <= b.a0 + 5 and p.a0 - 5 <= cc <= p.a1 + 5
                    for p in rects
                )
                # another wall on the same line in between -> not adjacent
                between = any(
                    k not in (i, j)
                    and r.orient == a.orient
                    and abs(r.cc - cc) <= 8
                    and r.a0 < b.a0
                    and r.a1 > a.a1
                    for k, r in enumerate(rects)
                )
                if blocked or between:
                    continue
                if best is None or gap < best[0]:
                    best = (gap, i, j)
        if best is None:
            return rects
        gap, i, j = best
        a, b = rects[i], rects[j]
        kind = "door" if (gap <= DOOR_MAX_CM or gap > WIDE_DOOR_CM) else "window"  # very wide gaps are patio doors
        merged = _Rect(
            a.orient,
            a.a0,
            b.a1,
            (a.cc * (a.a1 - a.a0) + b.cc * (b.a1 - b.a0)) / ((a.a1 - a.a0) + (b.a1 - b.a0)),
            max(a.t, b.t),
            a.openings + b.openings + [DetectedOpening(kind, (a.a1 + b.a0) / 2, gap)],
            thin=a.thin and b.thin,
        )
        rects = [r for k, r in enumerate(rects) if k not in (i, j)] + [merged]


# ----------------------------------------------------------------------------- door / window classification

ARC_MIN_FRACTION = 0.4  # share of a quarter-circle that must be inked (door swings are often dashed)
GLAZING_ROW_COVERAGE = 0.7  # a glazing line must span this share of the gap
EXTERIOR_MARGIN_CM = 40.0


def _dilate1(m: np.ndarray) -> np.ndarray:
    out = m.copy()
    out[1:] |= m[:-1]
    out[:-1] |= m[1:]
    out[:, 1:] |= m[:, :-1]
    out[:, :-1] |= m[:, 1:]
    return out


def _sample_fraction(ink: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> float:
    h, w = ink.shape
    xi, yi = np.rint(xs).astype(int), np.rint(ys).astype(int)
    ok = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
    if ok.sum() < len(xs) * 0.6:
        return 0.0  # arc mostly outside the image
    return float(ink[yi[ok], xi[ok]].mean())


def _door_swing(ink: np.ndarray, orient: str, cc: float, lo: float, hi: float, t: float, ppc: float) -> bool:
    """True when a quarter-circle door-swing arc (solid or dashed) hangs off either jamb of the gap.

    ``lo``/``hi`` are the gap ends along the wall axis, ``cc`` the wall centre-line, all in cm.
    """
    width = (hi - lo) * ppc
    if width < 8:
        return False
    theta = np.radians(np.linspace(15, 80, 36))
    cos, sin = np.cos(theta), np.sin(theta)

    def point(hinge: float, along: float, side: float, radius: float) -> tuple[np.ndarray, np.ndarray]:
        s = hinge * ppc + along * radius * cos  # along-axis pixel coordinate
        c = cc * ppc + side * radius * sin  # cross-axis pixel coordinate
        return (s, c) if orient == "h" else (c, s)

    arc_best, radius = 0.0, width
    best_cfg: tuple[float, float, float] | None = None  # (hinge, direction along the wall, swing side)
    for hinge, along in ((lo, 1.0), (hi, -1.0)):
        for side in (-1.0, 1.0):
            for mult in np.linspace(0.6, 1.1, 11):  # the leaf is often a bit shorter than the measured gap
                arc = _sample_fraction(ink, *point(hinge, along, side, width * mult))
                if arc > arc_best:
                    arc_best, radius, best_cfg = arc, width * mult, (hinge, along, side)
    if best_cfg is None or arc_best < 0.25:
        return False
    hinge, along, side = best_cfg
    r = radius
    control = max(
        _sample_fraction(ink, *point(hinge, along, side, r * 0.78)),
        _sample_fraction(ink, *point(hinge, along, side, r * 1.28)),
    )
    if arc_best < 2.5 * control:
        return False
    # hatching / dotted textures (balconies, tiles) ink everything: the arc must stand out from its surroundings
    s0, s1 = sorted((hinge * ppc, hinge * ppc + along * r))
    c0, c1 = sorted((cc * ppc, cc * ppc + side * r))
    box = ink[max(0, int(c0)):int(c1) + 1, max(0, int(s0)):int(s1) + 1] if orient == "h" else ink[max(0, int(s0)):int(s1) + 1, max(0, int(c0)):int(c1) + 1]
    if box.size and arc_best < 2.2 * float(box.mean()):
        return False
    if arc_best >= ARC_MIN_FRACTION:
        return True
    # a weaker arc is accepted when the straight door leaf (hinge -> open position) is drawn as well
    steps = np.linspace(t * ppc / 2 + 2, r - 2, 24)
    s = np.full_like(steps, hinge * ppc)
    c = cc * ppc + side * steps
    leaf = _sample_fraction(ink, *((s, c) if orient == "h" else (c, s)))
    return leaf >= 0.75


def _glazing_lines(ink: np.ndarray, orient: str, cc: float, lo: float, hi: float, t: float, ppc: float) -> int:
    """Number of thin lines running along the wall axis across the gap (the window-frame symbol)."""
    margin = 0.15 * (hi - lo)
    a0, a1 = int(round((lo + margin) * ppc)), int(round((hi - margin) * ppc))
    half = t * ppc / 2 + 2
    c0, c1 = int(round(cc * ppc - half)), int(round(cc * ppc + half)) + 1
    if a1 - a0 < 4 or c1 - c0 < 2 or min(a0, c0) < 0:
        return 0
    sub = ink[c0:c1, a0:a1] if orient == "h" else ink[a0:a1, c0:c1].T
    if sub.size == 0:
        return 0
    sub = sub.copy()
    sub[1:] |= sub[:-1].copy()  # tolerate a slightly skewed scan
    rows = sub.mean(axis=1) >= GLAZING_ROW_COVERAGE
    lines, prev = 0, False
    for on in rows:
        if on and not prev:
            lines += 1
        prev = bool(on)
    return lines


def _classify_openings(
    rects: list[_Rect], ink: np.ndarray, faint: np.ndarray, thick: np.ndarray, ppc: float
) -> None:
    """Decide door vs window for every bridged gap from what is drawn in/around it.

    1. a door-swing arc next to the gap -> door
    2. two or more parallel frame lines across the gap -> window (patio-door sized gaps stay doors)
    3. otherwise context: exterior walls favour windows, interior openings are doors; the gap width
       only breaks the tie (<=110 cm door, 110-200 cm window on an exterior wall, wider = patio door)
    """
    if not rects:
        return
    xs0 = min(r.a0 if r.orient == "h" else r.cc for r in rects)
    xs1 = max(r.a1 if r.orient == "h" else r.cc for r in rects)
    ys0 = min(r.cc if r.orient == "h" else r.a0 for r in rects)
    ys1 = max(r.cc if r.orient == "h" else r.a1 for r in rects)
    arc_ink = _dilate1(faint & ~_dilate1(thick))  # door arcs are thin lines; ignore the thick walls they graze (+-1 px slack)
    for r in rects:
        edge = (ys0, ys1) if r.orient == "h" else (xs0, xs1)
        exterior = min(abs(r.cc - edge[0]), abs(r.cc - edge[1])) <= EXTERIOR_MARGIN_CM
        for o in r.openings:
            lo, hi = o.center - o.width / 2, o.center + o.width / 2
            if _door_swing(arc_ink, r.orient, r.cc, lo, hi, r.t, ppc):
                o.kind, o.evidence = "door", "arc"
            elif _glazing_lines(ink, r.orient, r.cc, lo, hi, r.t, ppc) >= 2:
                o.kind, o.evidence = ("window" if o.width <= WIDE_DOOR_CM else "door"), "glazing"
            else:
                if o.width <= DOOR_MAX_CM or o.width > WIDE_DOOR_CM:
                    o.kind = "door"
                else:
                    o.kind = "window" if exterior else "door"
                o.evidence = "context" if exterior else "width"


def _snap_junctions(rects: list[_Rect]) -> None:
    """Snap wall ends that touch a perpendicular wall onto that wall's centre-line."""
    for a in rects:
        for end in ("a0", "a1"):
            pos = getattr(a, end)
            best: tuple[float, float] | None = None
            for b in rects:
                if b.orient == a.orient:
                    continue
                if not (b.a0 - a.t / 2 - 10 <= a.cc <= b.a1 + a.t / 2 + 10):
                    continue
                d = abs(pos - b.cc)
                if d <= b.t / 2 + 15 and (best is None or d < best[0]):
                    best = (d, b.cc)
            if best is not None:
                setattr(a, end, best[1])


def _dedupe(rects: list[_Rect]) -> list[_Rect]:
    keep: list[_Rect] = []
    for i, a in enumerate(rects):
        contained = any(
            i != j
            and a.orient == b.orient
            and abs(a.cc - b.cc) <= 10
            and b.a0 - 5 <= a.a0
            and a.a1 <= b.a1 + 5
            and (b.a1 - b.a0, j) > (a.a1 - a.a0, i)
            for j, b in enumerate(rects)
        )
        if not contained and (a.a1 - a.a0) >= MIN_GAP_CM:
            keep.append(a)
    return keep


def _thin_line_runs(ink: np.ndarray, min_len: int) -> list[tuple[int, int, int]]:
    """Long continuous horizontal ink runs: (row, x0, x1). A 3 px closing bridges small breaks."""
    closed = ~_open(~ink, 1, 3)
    runs: list[tuple[int, int, int]] = []
    for y in range(closed.shape[0]):
        row = closed[y]
        if not row.any():
            continue
        d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
        for a, b in zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist()):
            if b - a >= min_len:
                runs.append((y, a, b))
    return runs


def _group_lines(runs: list[tuple[int, int, int]]) -> list[tuple[float, int, int]]:
    """Merge vertically adjacent runs that overlap in x into lines: (centre row, x0, x1)."""
    lines: list[list] = []  # [y_sum, count, x0, x1, last_row]
    for y, a, b in sorted(runs):
        for ln in lines:
            if y - ln[4] <= 1 and min(b, ln[3]) - max(a, ln[2]) > 0.6 * (b - a):
                ln[0] += y
                ln[1] += 1
                ln[2], ln[3], ln[4] = min(ln[2], a), max(ln[3], b), y
                break
        else:
            lines.append([y, 1, a, b, y])
    return [(ln[0] / ln[1], ln[2], ln[3]) for ln in lines if ln[1] <= 4]  # thin lines only


def _thin_partitions(img_mask: np.ndarray, ppc: float, limit: tuple[float, float, float, float]) -> list[_Rect]:
    """Partitions drawn as two parallel thin lines (hollow walls) -> wall rectangles in cm."""
    min_len = max(20, int(round(90 * ppc)))
    gap_lo, gap_hi = 6.0 * ppc, 24.0 * ppc
    out: list[_Rect] = []
    for orient, arr in (("h", img_mask), ("v", img_mask.T)):
        lines = _group_lines(_thin_line_runs(arr, min_len))
        used: set[int] = set()
        for i, (y1, a1, b1) in enumerate(lines):
            for j in range(i + 1, len(lines)):
                if i in used or j in used:
                    continue
                y2, a2, b2 = lines[j]
                sep = abs(y2 - y1)
                if not (gap_lo <= sep <= gap_hi):
                    continue
                x0, x1 = max(a1, a2), min(b1, b2)
                if x1 - x0 < 0.8 * min(b1 - a1, b2 - a2) or x1 - x0 < min_len:
                    continue
                used.update((i, j))
                cc = (y1 + y2) / 2 / ppc
                r = _Rect(orient, x0 / ppc, x1 / ppc, cc, sep / ppc + 1.5, thin=True)
                lx0, ly0, lx1, ly1 = limit
                cx = (r.a0 + r.a1) / 2
                px, py = (cx, cc) if orient == "h" else (cc, cx)
                if lx0 <= px <= lx1 and ly0 <= py <= ly1:
                    out.append(r)
    return out


def _single_lines_between_walls(ink: np.ndarray, ppc: float, rects: list[_Rect]) -> list[_Rect]:
    """Long single thin lines whose BOTH ends touch perpendicular walls are almost certainly walls
    (furniture outlines and dimension lines do not connect two walls)."""
    min_len = max(30, int(round(100 * ppc)))
    out: list[_Rect] = []
    for orient, arr in (("h", ink), ("v", ink.T)):
        for yc, a, b in _group_lines(_thin_line_runs(arr, min_len)):
            cc, a0, a1 = yc / ppc, a / ppc, b / ppc

            def touches(pos: float) -> bool:
                return any(
                    r.orient != orient and abs(pos - r.cc) <= r.t / 2 + 20 and r.a0 - 15 <= cc <= r.a1 + 15
                    for r in rects
                )

            if touches(a0) and touches(a1):
                out.append(_Rect(orient, a0, a1, cc, 10.0, thin=True))
    return out


def detect_walls(img: Image.Image, pixels_per_cm: float, include_thin: bool = True) -> list[DetectedWall]:
    ppc = float(pixels_per_cm)
    if ppc <= 0:
        raise ValueError("pixels_per_cm must be positive")
    mask = wall_mask(img)
    t_min = max(3, int(round(MIN_THICKNESS_CM * ppc)))
    t_max = int(round(MAX_THICKNESS_CM * ppc))
    l_min = max(2 * t_min, int(round(MIN_LENGTH_CM * ppc)))

    hmask = _open(mask, t_min, l_min)
    vmask = _open(mask, l_min, t_min)
    rects = _rects_from_mask(hmask, "h", ppc, t_min, t_max, l_min) + _rects_from_mask(
        vmask, "v", ppc, t_min, t_max, l_min
    )
    ink_thin: np.ndarray | None = None
    ink_faint: np.ndarray | None = None
    if rects and include_thin:
        rgb = np.asarray(img.convert("RGB")).astype(np.int32)
        lum = (rgb[..., 0] * 299 + rgb[..., 1] * 587 + rgb[..., 2] * 114) // 1000
        ink_thin = ((rgb.max(axis=2) - rgb.min(axis=2)) > 38) | (lum < 150)
        # dashed door-swing arcs are drawn in light grey on many scans: a more permissive ink for them only
        ink_faint = ((rgb.max(axis=2) - rgb.min(axis=2)) > 38) | (lum < 205)
    # hollow partitions (two thin parallel lines) inside the area spanned by the solid walls
    if rects and ink_thin is not None:
        lim = (
            min(min(r.a0, r.cc) if r.orient == "h" else r.cc for r in rects) - 10,
            min(r.cc if r.orient == "h" else r.a0 for r in rects) - 10,
            max(max(r.a1, r.cc) if r.orient == "h" else r.cc for r in rects) + 10,
            max(r.cc if r.orient == "h" else r.a1 for r in rects) + 10,
        )
        for t in _thin_partitions(ink_thin, ppc, lim):
            if not any(
                r.orient == t.orient and abs(r.cc - t.cc) <= max(r.t, t.t) and min(r.a1, t.a1) - max(r.a0, t.a0) > 0.5 * (t.a1 - t.a0)
                for r in rects
            ):
                rects.append(t)
        for t in _single_lines_between_walls(ink_thin, ppc, rects):
            if not any(
                r.orient == t.orient and abs(r.cc - t.cc) <= max(r.t, t.t) and min(r.a1, t.a1) - max(r.a0, t.a0) > 0.5 * (t.a1 - t.a0)
                for r in rects
            ):
                rects.append(t)
    rects = _bridge_gaps(rects)
    if ink_thin is not None:
        _classify_openings(rects, ink_thin, ink_faint, hmask | vmask, ppc)
    _snap_junctions(rects)
    rects = _dedupe(rects)

    walls: list[DetectedWall] = []
    for r in rects:
        t = float(min(max(round(r.t), MIN_THICKNESS_CM), MAX_THICKNESS_CM))
        a0, a1, cc = round(r.a0), round(r.a1), round(r.cc)
        ops = []
        for o in r.openings:
            width = float(min(max(round(o.width), 60), MAX_GAP_CM))
            half = width / 2
            offset = min(max(o.center - a0, half), max(half, (a1 - a0) - half))
            if o.kind == "door":
                ops.append({"kind": "door", "offsetCm": round(offset), "widthCm": width, "heightCm": 210.0, "sillCm": 0.0})
            else:
                ops.append({"kind": "window", "offsetCm": round(offset), "widthCm": width, "heightCm": 120.0, "sillCm": 90.0})
        if r.orient == "h":
            walls.append(DetectedWall(a0, cc, a1, cc, t, ops, r.thin))
        else:
            walls.append(DetectedWall(cc, a0, cc, a1, t, ops, r.thin))
    walls.sort(key=lambda w: (round(w.y1), round(w.x1)))
    return walls


# ----------------------------------------------------------------------------- window labels from the plan

CEILING_CM = 270.0
WINDOW_HEAD_CM = 215.0  # typical top edge of a window when its height is not printed
MAX_LABEL_REACH_CM = 300.0  # a label may extend an exterior wall at most this far to reach its window


@dataclass
class WindowLabel:
    """A printed "width / height (+sill)" window label, positioned in plan centimeters."""

    x_cm: float
    y_cm: float
    sill_cm: float
    width_cm: float | None = None
    height_cm: float | None = None


def apply_window_labels(walls: list[DetectedWall], labels: list[WindowLabel]) -> int:
    """Use window labels printed outside the building to fix kinds, sills, sizes and to add missed windows.

    A label sits in the margin next to the exterior wall it describes, centred on the window. It is matched
    to the exterior wall on that side; an opening already detected there is turned into a window with the
    printed sill, otherwise a new window is created. Returns the number of openings touched.
    """
    if not walls or not labels:
        return 0
    xmin = min(min(w.x1, w.x2) for w in walls)
    xmax = max(max(w.x1, w.x2) for w in walls)
    ymin = min(min(w.y1, w.y2) for w in walls)
    ymax = max(max(w.y1, w.y2) for w in walls)
    touched = 0
    for lab in labels:
        if lab.y_cm < ymin - 5:
            side = "top"
        elif lab.y_cm > ymax + 5:
            side = "bottom"
        elif lab.x_cm < xmin - 5:
            side = "left"
        elif lab.x_cm > xmax + 5:
            side = "right"
        else:
            continue  # inside the building: an elevation mark or a dimension, not a window label
        horiz = side in ("top", "bottom")
        pos = lab.x_cm if horiz else lab.y_cm
        edge = {"top": ymin, "bottom": ymax, "left": xmin, "right": xmax}[side]
        best: tuple[float, DetectedWall, float, float] | None = None  # (gap to label, wall, a0, a1)
        for w in walls:
            if (w.y1 == w.y2) != horiz:
                continue
            cc = w.y1 if horiz else w.x1
            if abs(cc - edge) > EXTERIOR_MARGIN_CM + 5:
                continue
            a0, a1 = (min(w.x1, w.x2), max(w.x1, w.x2)) if horiz else (min(w.y1, w.y2), max(w.y1, w.y2))
            gap = max(a0 - pos, pos - a1, 0.0)
            if gap <= MAX_LABEL_REACH_CM and (best is None or gap < best[0]):
                best = (gap, w, a0, a1)
        if best is None:
            continue
        _, wall, a0, a1 = best
        sill = float(lab.sill_cm)
        width = lab.width_cm
        if best[0] > 0:
            # the window fills the whole stretch of exterior wall up to the corner, so no wall segment was detected
            # there: grow the nearest exterior wall over it (up to the corner of the building)
            lo_lim, hi_lim = (xmin, xmax) if horiz else (ymin, ymax)
            reach = (width or 100.0) / 2 + 10
            new_a0, new_a1 = min(a0, max(lo_lim, pos - reach)), max(a1, min(hi_lim, pos + reach))
            shift = a0 - new_a0
            if horiz:
                wall.x1, wall.x2 = new_a0, new_a1
            else:
                wall.y1, wall.y2 = new_a0, new_a1
            for o in wall.openings:
                o["offsetCm"] += shift
            a0, a1 = new_a0, new_a1
        at = pos - a0
        match: dict | None = None
        for o in wall.openings:
            d = abs(o["offsetCm"] - at)
            if d <= max(35.0, 0.6 * o["widthCm"]) and (match is None or d < abs(match["offsetCm"] - at)):
                match = o
        if match is not None:
            if width is not None and not 0.5 * match["widthCm"] <= width <= 2.0 * match["widthCm"]:
                width = None  # OCR slip: keep the width measured from the drawing
            width = width or match["widthCm"]
        else:
            width = width or 100.0
        height = lab.height_cm or min(max(WINDOW_HEAD_CM - sill, 60.0), CEILING_CM - sill - 5)
        height = min(height, CEILING_CM - sill)
        opening = {"kind": "window", "offsetCm": at, "widthCm": float(width), "heightCm": float(height), "sillCm": sill}
        if match is not None:
            match.update({**opening, "offsetCm": match["offsetCm"]})
        else:
            half = width / 2
            if (a1 - a0) < width:
                continue
            opening["offsetCm"] = float(round(min(max(at, half), (a1 - a0) - half)))
            wall.openings.append(opening)
        touched += 1
    return touched


# ----------------------------------------------------------------------------- automatic scale

ASSUMED_WALL_CM = 20.0  # typical structural wall; used only when the scale is unknown
MAX_WORKING_SIDE = 1600  # downscale huge renders (e.g. 300 DPI PDFs) for speed and stable thresholds


def detect_walls_auto(
    img: Image.Image, pixels_per_cm: float | None = None
) -> tuple[list[DetectedWall], float | None, bool]:
    """Detect walls, estimating the scale when it is not given.

    Returns ``(walls, pixels_per_cm, scale_estimated)`` where ``pixels_per_cm`` refers to the
    ORIGINAL image and the walls are in centimeters with the image's top-left as origin.
    When estimating, a first pass in raw pixel units measures the typical wall thickness, which is
    assumed to be ~20 cm; the result is only as accurate as that assumption, so callers should
    present it as an estimate that manual calibration can refine.
    """
    w0, h0 = img.size
    f = MAX_WORKING_SIDE / max(w0, h0) if max(w0, h0) > MAX_WORKING_SIDE else 1.0
    work = img.resize((max(1, round(w0 * f)), max(1, round(h0 * f))), Image.LANCZOS) if f != 1.0 else img

    if pixels_per_cm is not None:
        ppc_work = float(pixels_per_cm) * f
        estimated = False
    else:
        probe_all = detect_walls(work, 1.0, include_thin=False)  # raw-pixel thresholds; solid walls only (fast)
        if not probe_all:
            return [], None, True
        # thin hollow partitions are always ~10 cm, so they must not drag the thickness median down
        probe = [p for p in probe_all if not p.thin] or probe_all
        weights = [max(1.0, abs(p.x2 - p.x1) + abs(p.y2 - p.y1)) for p in probe]
        order = sorted(range(len(probe)), key=lambda i: probe[i].thicknessCm)
        half, acc = sum(weights) / 2, 0.0
        t_med = probe[order[-1]].thicknessCm
        for i in order:  # length-weighted median thickness (px)
            acc += weights[i]
            if acc >= half:
                t_med = probe[i].thicknessCm
                break
        ppc_work = max(0.05, t_med / ASSUMED_WALL_CM)
        estimated = True

    walls = detect_walls(work, ppc_work)
    return walls, ppc_work / f, estimated
