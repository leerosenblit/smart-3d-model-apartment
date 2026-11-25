"""Procedural furniture modeller for the built-in (mock) image-to-3D provider.

Every product gets a recognisable, well-proportioned model: soft rounded cushions, tapered legs, door panels
with handles, real appliance details, ... The look is varied per product (style variants are chosen
deterministically from the product id / title keywords) and coloured from the product photo.

Conventions: metres, X = width, Y = up, Z = depth. Origin = bottom-centre on the floor. The FRONT is +Z and the
back (against a wall) is -Z. Dimensions are re-applied exactly by the client, so proportions matter most.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import trimesh

Color = tuple[int, int, int]


@dataclass
class Palette:
    """Colours read from the product photo."""

    main: Color  # dominant: fabric, body, frame
    accent: Color  # second: legs, trim
    pale: bool = False  # product is (nearly) white


# ----------------------------------------------------------------------------- colour helpers

def shade(c: Color, f: float) -> Color:
    return (max(0, min(255, int(c[0] * f))), max(0, min(255, int(c[1] * f))), max(0, min(255, int(c[2] * f))))


def mix(a: Color, b: Color, t: float) -> Color:
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t), int(a[2] + (b[2] - a[2]) * t))


def _dist(a: Color, b: Color) -> float:
    return float(sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5)


WOOD_LIGHT: Color = (201, 164, 120)
WOOD_MID: Color = (160, 118, 80)
WOOD_DARK: Color = (96, 66, 46)
METAL: Color = (74, 78, 84)
BRASS: Color = (196, 164, 96)
GLASS: Color = (188, 214, 224)
WHITE: Color = (244, 244, 246)


# ----------------------------------------------------------------------------- colours from the title

_COLOR_WORDS: dict[str, Color] = {
    # hebrew
    "כחול": (58, 92, 150), "כחולה": (58, 92, 150), "תכלת": (130, 185, 220), "אפור": (138, 140, 146), "אפורה": (138, 140, 146),
    "שחור": (42, 43, 48), "שחורה": (42, 43, 48), "לבן": (240, 240, 242), "לבנה": (240, 240, 242),
    "בז": (205, 186, 156), "שמנת": (234, 224, 200), "קרם": (234, 224, 200), "שנהב": (240, 232, 214),
    "חום": (116, 80, 58), "חומה": (116, 80, 58), "קפה": (104, 74, 56),
    "ירוק": (74, 120, 84), "ירוקה": (74, 120, 84), "זית": (112, 120, 72), "מרווה": (150, 168, 140),
    "אדום": (172, 52, 52), "אדומה": (172, 52, 52), "בורדו": (112, 32, 48), "ורוד": (224, 162, 178), "ורודה": (224, 162, 178),
    "סגול": (112, 74, 142), "צהוב": (232, 196, 72), "צהובה": (232, 196, 72), "חרדל": (204, 152, 52), "כתום": (222, 124, 52),
    "טורקיז": (60, 160, 160), "זהב": (200, 170, 92), "כסף": (192, 194, 200), "נירוסטה": (196, 200, 206),
    "אלון": (204, 170, 128), "אגוז": (102, 70, 50), "טבעי": (205, 175, 135), "אבן": (170, 166, 158), "בטון": (150, 150, 148),
    "אפרסק": (240, 190, 150), "טרקוטה": (196, 110, 80), "נחושת": (184, 115, 80),
    # english
    "blue": (58, 92, 150), "navy": (40, 60, 105), "grey": (138, 140, 146), "gray": (138, 140, 146), "anthracite": (70, 74, 80),
    "black": (42, 43, 48), "white": (240, 240, 242), "beige": (205, 186, 156), "cream": (234, 224, 200), "brown": (116, 80, 58),
    "green": (74, 120, 84), "red": (172, 52, 52), "pink": (224, 162, 178), "yellow": (232, 196, 72), "orange": (222, 124, 52),
    "oak": (204, 170, 128), "walnut": (102, 70, 50), "birch": (222, 200, 160), "turquoise": (60, 160, 160),
}
_DARK_WORDS = {"כהה", "כהים", "כהה", "dark"}
_LIGHT_WORDS = {"בהיר", "בהירה", "בהירים", "light", "pale"}
_PREFIXES = "בהולכמש"


def _lum(c: Color) -> float:
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def colors_from_title(title: str) -> list[Color]:
    """Colours named in a product title ("בגוון כחול", "אפור כהה", "Kilanda בז' בהיר", "white/oak"), in order."""
    tokens = re.findall(r"[\u05d0-\u05ea]+|[A-Za-z]+", title or "")
    out: list[Color] = []
    for i, raw in enumerate(tokens):
        word = raw.lower()
        key = word if word in _COLOR_WORDS else (word[1:] if len(word) > 3 and word[0] in _PREFIXES and word[1:] in _COLOR_WORDS else None)
        if key is None:
            continue
        c = _COLOR_WORDS[key]
        nxt = tokens[i + 1].lower() if i + 1 < len(tokens) else ""
        if nxt in _DARK_WORDS:
            c = shade(c, 0.62)
        elif nxt in _LIGHT_WORDS:
            c = mix(c, (255, 255, 255), 0.42)
        if not out or _dist(out[-1], c) > 30:
            out.append(c)
        if len(out) == 2:
            break
    return out


def resolve_palette(title: str, photo: Optional[Palette]) -> Optional[Palette]:
    """Title colours win (they are explicit and reliable); the photo, which is often a room scene, is the fallback."""
    cols = colors_from_title(title)
    if not cols:
        return photo
    main = cols[0]
    # second named colour -> accent; otherwise a near-main accent so legs fall back to a wood/metal tone
    accent = cols[1] if len(cols) > 1 else shade(main, 0.9)
    return Palette(main, accent, pale=_lum(main) > 225)


# ----------------------------------------------------------------------------- mesh primitives

def _paint(m: trimesh.Trimesh, color: Color) -> trimesh.Trimesh:
    rgba = np.array([*color, 255], dtype=np.uint8)
    m.visual = trimesh.visual.ColorVisuals(mesh=m, vertex_colors=np.tile(rgba, (len(m.vertices), 1)))
    return m


def _outward(m: trimesh.Trimesh) -> trimesh.Trimesh:
    """Make sure the winding points outwards (flip when the signed volume is negative)."""
    try:
        if m.volume < 0:
            m.invert()
    except Exception:  # noqa: BLE001
        pass
    return m


def _spow(t: np.ndarray, e: float) -> np.ndarray:
    return np.sign(t) * np.abs(t) ** e


def rbox(ext: tuple[float, float, float], center: tuple[float, float, float], color: Color, e: float = 0.3, nu: int = 28, nv: int = 16) -> trimesh.Trimesh:
    """Soft box (superquadric): e=1 is an ellipsoid, e->0 a sharp box. Used for cushions, pillows, rounded bodies."""
    a, b, c = (x / 2 for x in ext)
    u = np.linspace(-np.pi, np.pi, nu, endpoint=False)
    v = np.linspace(-np.pi / 2, np.pi / 2, nv)
    U, V = np.meshgrid(u, v)
    cv, sv = _spow(np.cos(V), e), _spow(np.sin(V), e)
    x = a * cv * _spow(np.cos(U), e)
    z = c * cv * _spow(np.sin(U), e)
    y = b * sv
    verts = np.stack([x, y, z], -1).reshape(-1, 3)
    faces = []
    for i in range(nv - 1):
        for j in range(nu):
            k = (j + 1) % nu
            a0, a1, b0, b1 = i * nu + j, i * nu + k, (i + 1) * nu + j, (i + 1) * nu + k
            faces.append([a0, a1, b1])
            faces.append([a0, b1, b0])
    m = trimesh.Trimesh(vertices=verts, faces=np.array(faces), process=False)
    m.apply_translation(center)
    return _paint(_outward(m), color)


def box(ext: tuple[float, float, float], center: tuple[float, float, float], color: Color) -> trimesh.Trimesh:
    base = trimesh.creation.box(extents=ext)
    # unshare the vertices so every face keeps its own (flat) normal: hard edges stay crisp instead of
    # being smoothed into a glossy gradient across the box
    m = trimesh.Trimesh(
        vertices=base.vertices[base.faces].reshape(-1, 3),
        faces=np.arange(len(base.faces) * 3).reshape(-1, 3),
        process=False,
    )
    m.apply_translation(center)
    return _paint(m, color)


def frustum(r0: float, r1: float, h: float, center: tuple[float, float, float], color: Color, sections: int = 24) -> trimesh.Trimesh:
    """Vertical truncated cone (r0 at the bottom, r1 at the top): tapered legs, lamp shades, pots, drums."""
    ang = np.linspace(0, 2 * np.pi, sections, endpoint=False)
    bottom = np.stack([r0 * np.cos(ang), np.zeros_like(ang), r0 * np.sin(ang)], -1)
    top = np.stack([r1 * np.cos(ang), np.full_like(ang, h), r1 * np.sin(ang)], -1)
    verts = np.vstack([bottom, top, [[0, 0, 0]], [[0, h, 0]]])
    cb, ct = 2 * sections, 2 * sections + 1
    faces = []
    for j in range(sections):
        k = (j + 1) % sections
        faces += [[j, k, sections + k], [j, sections + k, sections + j]]
        faces += [[cb, k, j], [ct, sections + j, sections + k]]
    m = trimesh.Trimesh(vertices=verts, faces=np.array(faces), process=False)
    m.apply_translation((center[0], center[1] - h / 2, center[2]))  # centre-based like the other helpers
    return _paint(_outward(m), color)


def cylinder(r: float, h: float, center: tuple[float, float, float], color: Color, sections: int = 24) -> trimesh.Trimesh:
    return frustum(r, r, h, center, color, sections)


def tilt(m: trimesh.Trimesh, deg_x: float = 0.0, deg_z: float = 0.0, about: Optional[tuple[float, float, float]] = None) -> trimesh.Trimesh:
    pt = about if about is not None else m.centroid
    if deg_x:
        m.apply_transform(trimesh.transformations.rotation_matrix(np.radians(deg_x), [1, 0, 0], pt))
    if deg_z:
        m.apply_transform(trimesh.transformations.rotation_matrix(np.radians(deg_z), [0, 0, 1], pt))
    return m


def spin(m: trimesh.Trimesh, deg_y: float) -> trimesh.Trimesh:
    m.apply_transform(trimesh.transformations.rotation_matrix(np.radians(deg_y), [0, 1, 0], [0, 0, 0]))
    return m


# ----------------------------------------------------------------------------- shared building blocks

def leg(x: float, z: float, height: float, style: str, color: Color, radius: float = 0.022) -> list[trimesh.Trimesh]:
    """One leg whose top is at y=height. Styles: peg (tapered round), square, hairpin/metal (thin), block."""
    if style == "metal":
        return [cylinder(0.009, height, (x, height / 2, z), color, 12)]
    if style == "block":
        return [box((radius * 2.4, height, radius * 2.4), (x, height / 2, z), color)]
    if style == "square":
        return [box((radius * 1.8, height, radius * 1.8), (x, height / 2, z), color)]
    m = frustum(radius * 0.55, radius, height, (x, height / 2, z), color, 16)  # tapered: thin at the floor
    return [m]


def corner_legs(w: float, d: float, height: float, style: str, color: Color, inset: float = 0.07, radius: float = 0.022) -> list[trimesh.Trimesh]:
    out: list[trimesh.Trimesh] = []
    for sx in (-1, 1):
        for sz in (-1, 1):
            out += leg(sx * (w / 2 - inset), sz * (d / 2 - inset), height, style, color, radius)
    return out


def handle(x: float, y: float, z: float, vertical: bool, length: float, color: Color) -> list[trimesh.Trimesh]:
    if vertical:
        return [box((0.012, length, 0.014), (x, y, z + 0.007), color)]
    return [box((length, 0.012, 0.014), (x, y, z + 0.007), color)]


def knob(x: float, y: float, z: float, color: Color) -> list[trimesh.Trimesh]:
    m = rbox((0.03, 0.03, 0.02), (x, y, z + 0.01), color, 0.9, 12, 8)
    return [m]


# ----------------------------------------------------------------------------- per-category builders

@dataclass
class Ctx:
    w: float
    d: float
    h: float
    pal: Palette
    title: str
    rng: random.Random

    @property
    def main(self) -> Color:
        return self.pal.main

    @property
    def dark(self) -> Color:
        return shade(self.pal.main, 0.8)

    @property
    def light(self) -> Color:
        return WHITE if self.pal.pale else shade(self.pal.main, 1.08)

    @property
    def wood(self) -> Color:
        """Leg / frame colour: the photo's accent when it is wood-like or dark, otherwise a wood tone."""
        a = self.pal.accent
        if _dist(a, self.pal.main) > 45:
            return a
        return self.rng.choice([WOOD_LIGHT, WOOD_MID, WOOD_DARK, METAL])

    def has(self, pattern: str) -> bool:
        return re.search(pattern, self.title, re.IGNORECASE) is not None


SECTIONAL = r"פינת|מודולר|שזלונג|chaise|corner|sectional|L[- ]?shape|U[- ]?shape"


def build_sofa(c: Ctx, armchair: bool = False) -> list[trimesh.Trimesh]:
    w, d, h, rng = c.w, c.d, c.h, c.rng
    out: list[trimesh.Trimesh] = []
    sectional = (not armchair) and (c.has(SECTIONAL) or (d >= 1.4 and w >= 2.0))
    leg_style = rng.choice(["peg", "peg", "metal", "block", "plinth"])
    leg_h = 0.0 if leg_style == "plinth" else rng.choice([0.08, 0.1, 0.14])
    arm_style = rng.choice(["track", "round", "round", "slim"])
    arm_w = min(w * (0.17 if armchair else 0.1), 0.24) * {"track": 1.0, "round": 1.15, "slim": 0.6}[arm_style]
    seat_top = min(h * 0.5, 0.48)
    base_h = seat_top - leg_h - 0.1
    seat_d = min(d, 1.0) if sectional else d
    back_t = rng.choice([0.2, 0.24, 0.28])
    chaise_right = rng.random() < 0.5
    chaise_w = max(0.85, w * 0.32) if sectional else 0.0
    sgn = 1 if chaise_right else -1

    # frame / base
    out.append(rbox((w, base_h, seat_d), (0, leg_h + base_h / 2, -d / 2 + seat_d / 2), c.dark, 0.1))
    if sectional:
        out.append(rbox((chaise_w, base_h, d), (sgn * (w / 2 - chaise_w / 2), leg_h + base_h / 2, 0), c.dark, 0.1))
    # seat cushions (soft)
    usable = w - (arm_w if armchair or True else 0) * (1 if sectional else 2) - chaise_w
    n = 1 if armchair else max(2, min(4, int(round(usable / 0.72))))
    cw = usable / n
    x0 = (-w / 2 + arm_w) if (not sectional or chaise_right) else (-w / 2 + chaise_w)
    for i in range(n):
        cx = x0 + cw * (i + 0.5)
        out.append(rbox((cw - 0.015, 0.14, seat_d - back_t * 0.6), (cx, leg_h + base_h + 0.07, -d / 2 + (seat_d - back_t * 0.6) / 2 + back_t * 0.6), c.light, 0.28))
    if sectional:
        out.append(rbox((chaise_w - 0.02, 0.14, d - 0.04), (sgn * (w / 2 - chaise_w / 2), leg_h + base_h + 0.07, 0.0), c.light, 0.28))
    # back cushions, leaning back
    back_h = max(0.3, h - seat_top - 0.02)
    for i in range(n if not sectional else n):
        cx = x0 + cw * (i + 0.5)
        m = rbox((cw - 0.02, back_h, back_t), (cx, seat_top + back_h / 2 - 0.02, -d / 2 + back_t / 2 + 0.04), c.main, 0.28)
        out.append(tilt(m, deg_x=-8, about=(cx, seat_top, -d / 2 + 0.2)))
    # back frame rail
    out.append(rbox((w, h - leg_h - 0.1, 0.08), (0, leg_h + 0.1 + (h - leg_h - 0.1) / 2, -d / 2 + 0.04), c.dark, 0.12))
    # arms
    arm_h = seat_top + (0.16 if arm_style != "slim" else 0.1) - leg_h
    arm_e = 0.35 if arm_style == "round" else 0.12
    arms = [-1, 1] if not sectional else [(-sgn)]
    for s in arms:
        out.append(rbox((arm_w, arm_h, seat_d), (s * (w / 2 - arm_w / 2), leg_h + arm_h / 2, -d / 2 + seat_d / 2), c.dark, arm_e))
    # legs
    if leg_style != "plinth":
        out += corner_legs(w, seat_d, leg_h, "peg" if leg_style == "block" else leg_style, c.wood if leg_style != "metal" else METAL, 0.09)
        if sectional:
            for sz in (1,):
                out += leg(sgn * (w / 2 - 0.09), d / 2 - 0.09, leg_h, "peg" if leg_style == "block" else leg_style, c.wood if leg_style != "metal" else METAL)
    # throw pillows for character
    if not armchair and rng.random() < 0.75:
        for s in (-1, 1) if not sectional else (-sgn,):
            m = rbox((0.4, 0.38, 0.12), (s * (w / 2 - arm_w - 0.28), seat_top + 0.22, -d / 2 + back_t + 0.2), mix(c.pal.accent, c.main, 0.4), 0.5)
            out.append(tilt(m, deg_x=-12, deg_z=s * 10))
    return out


def build_chair(c: Ctx) -> list[trimesh.Trimesh]:
    w, d, h, rng = c.w, c.d, c.h, c.rng
    style = rng.choice(["wood", "upholstered", "shell", "slat"])
    seat_h = min(h * 0.5, 0.48)
    leg_style = {"wood": "peg", "upholstered": "peg", "shell": "metal", "slat": "square"}[style]
    legc = c.wood if style != "shell" else METAL
    out: list[trimesh.Trimesh] = []
    seat_t = 0.05 if style != "upholstered" else 0.09
    seat_col = c.main if style != "slat" else mix(c.main, WOOD_LIGHT, 0.5)
    out.append(rbox((w, seat_t, d), (0, seat_h - seat_t / 2, 0), seat_col, 0.2 if style != "slat" else 0.1))
    # splayed legs
    for sx in (-1, 1):
        for sz in (-1, 1):
            parts = leg(sx * (w / 2 - 0.04), sz * (d / 2 - 0.04), seat_h - seat_t, leg_style, legc, 0.02)
            for p in parts:
                tilt(p, deg_x=sz * 4, deg_z=-sx * 4, about=(sx * w / 2, seat_h, sz * d / 2))
            out += parts
    back_h = h - seat_h
    if style == "shell":
        m = rbox((w * 0.95, back_h * 0.7, 0.05), (0, seat_h + back_h * 0.45, -d / 2 + 0.05), c.main, 0.4)
        out.append(tilt(m, deg_x=-12, about=(0, seat_h, -d / 2)))
    elif style == "slat":
        for i in range(4):
            out.append(box((w * 0.9, 0.05, 0.02), (0, seat_h + 0.1 + i * back_h * 0.2, -d / 2 + 0.03), legc))
        for sx in (-1, 1):
            out.append(box((0.035, back_h, 0.035), (sx * (w / 2 - 0.03), seat_h + back_h / 2, -d / 2 + 0.03), legc))
    else:
        m = rbox((w * 0.92, back_h * 0.75, 0.07), (0, seat_h + back_h * 0.5, -d / 2 + 0.05), c.main if style == "upholstered" else legc, 0.25)
        out.append(tilt(m, deg_x=-8, about=(0, seat_h, -d / 2)))
        for sx in (-1, 1):
            out.append(box((0.035, back_h, 0.035), (sx * (w / 2 - 0.035), seat_h + back_h / 2, -d / 2 + 0.035), legc))
    return out


def build_table(c: Ctx, kind: str) -> list[trimesh.Trimesh]:
    w, d, h, rng = c.w, c.d, c.h, c.rng
    round_top = c.has(r"עגול|round|אליפס|oval") or (abs(w - d) < 0.04 and not c.has(r"מרובע|square"))
    base = rng.choice(["four", "four", "trestle", "pedestal"]) if kind != "desk" else rng.choice(["four", "trestle", "drawers"])
    if round_top and base == "trestle":
        base = "pedestal"
    top_t = rng.choice([0.03, 0.04, 0.05]) if kind != "coffee_table" else 0.04
    top_col = c.main if not c.pal.pale else mix(c.main, WHITE, 0.5)
    legc = c.wood
    out: list[trimesh.Trimesh] = []
    if round_top:
        out.append(rbox((w, top_t, d), (0, h - top_t / 2, 0), top_col, 0.9, 40, 10))  # ellipsoid-ish disc
        out[-1] = rbox((w, top_t * 1.2, d), (0, h - top_t / 2, 0), top_col, 0.6, 40, 10)
    else:
        out.append(rbox((w, top_t, d), (0, h - top_t / 2, 0), top_col, 0.12))
    leg_h = h - top_t
    if base == "pedestal":
        out.append(frustum(0.05, 0.035, leg_h, (0, leg_h / 2, 0), legc, 20))
        out.append(rbox((min(w, d) * 0.6, 0.03, min(w, d) * 0.6), (0, 0.015, 0), legc, 0.8, 28, 8))
    elif base == "trestle":
        for sx in (-1, 1):
            out.append(box((0.045, leg_h, d * 0.7), (sx * (w / 2 - 0.2), leg_h / 2, 0), legc))
        out.append(box((w - 0.5, 0.04, 0.05), (0, leg_h - 0.1, 0), legc))
    elif base == "drawers":
        out.append(box((0.45, leg_h, d - 0.1), (w / 2 - 0.3, leg_h / 2, 0), c.dark))
        for i in range(3):
            out += handle(w / 2 - 0.3, leg_h * (0.2 + 0.3 * i), d / 2 - 0.05, False, 0.12, METAL)
        out += leg(-w / 2 + 0.06, d / 2 - 0.06, leg_h, "square", legc)
        out += leg(-w / 2 + 0.06, -d / 2 + 0.06, leg_h, "square", legc)
    else:
        out += corner_legs(w, d, leg_h, rng.choice(["peg", "square", "metal"]), legc, 0.06, 0.03)
        if kind == "dining_table":  # apron
            out.append(box((w - 0.16, 0.07, 0.025), (0, leg_h - 0.045, d / 2 - 0.06), shade(legc, 0.9)))
            out.append(box((w - 0.16, 0.07, 0.025), (0, leg_h - 0.045, -d / 2 + 0.06), shade(legc, 0.9)))
    if kind == "coffee_table" and base == "four" and not round_top:
        out.append(box((w - 0.18, 0.025, d - 0.18), (0, 0.14, 0), shade(legc, 1.05)))  # lower shelf
    return out


def build_bed(c: Ctx) -> list[trimesh.Trimesh]:
    w, d, h, rng = c.w, c.d, c.h, c.rng
    style = rng.choice(["upholstered", "wood", "panel", "upholstered"])
    frame_col = c.main if style != "wood" else mix(c.main, c.wood, 0.5)
    frame_h = min(0.3, h * 0.45)
    leg_h = 0.1
    out: list[trimesh.Trimesh] = []
    out.append(rbox((w, frame_h - leg_h, d), (0, leg_h + (frame_h - leg_h) / 2, 0), frame_col, 0.1))
    for sx in (-1, 1):
        for sz in (-1, 1):
            out += leg(sx * (w / 2 - 0.06), sz * (d / 2 - 0.06), leg_h, "block", c.wood if style != "upholstered" else METAL, 0.025)
    # headboard (always at the back, -z)
    hb_t = 0.09 if style == "upholstered" else 0.05
    hb_h = h
    out.append(rbox((w, hb_h - leg_h, hb_t), (0, leg_h + (hb_h - leg_h) / 2, -d / 2 + hb_t / 2), frame_col if style != "panel" else shade(frame_col, 0.9), 0.15 if style == "upholstered" else 0.06))
    if style == "upholstered":
        for i in range(1, 4):  # channels
            out.append(box((0.012, hb_h * 0.6, 0.012), (-w / 2 + w * i / 4, frame_h + hb_h * 0.3, -d / 2 + hb_t + 0.003), shade(frame_col, 0.75)))
    if style == "wood":  # footboard
        out.append(box((w, frame_h * 0.9, 0.04), (0, leg_h + frame_h * 0.45, d / 2 - 0.02), frame_col))
    # mattress, duvet, pillows
    m_h = 0.22
    out.append(rbox((w * 0.95, m_h, d * 0.94 - hb_t), (0, frame_h + m_h / 2 - 0.02, hb_t / 2 + 0.01), (240, 239, 235), 0.2))
    duvet_col = mix(c.pal.accent, WHITE, 0.45) if rng.random() < 0.5 else mix(c.main, WHITE, 0.55)
    out.append(rbox((w * 0.97, 0.06, d * 0.62), (0, frame_h + m_h + 0.0, d * 0.17), duvet_col, 0.25))
    npill = 2 if w < 1.5 else rng.choice([2, 4])
    for i in range(npill):
        per = 2 if npill == 4 else npill
        row = i // per
        col = i % per
        px = (col + 0.5) / per * w * 0.86 - w * 0.43
        pz = -d / 2 + hb_t + 0.22 + row * 0.2
        m = rbox((min(0.62, w * 0.82 / per), 0.12, 0.38), (px, frame_h + m_h + 0.09 + row * 0.02, pz), WHITE if row == 0 else mix(c.pal.accent, WHITE, 0.3), 0.45)
        out.append(tilt(m, deg_x=-12))
    return out


def build_wardrobe(c: Ctx) -> list[trimesh.Trimesh]:
    w, d, h, rng = c.w, c.d, c.h, c.rng
    body = WHITE if c.pal.pale else c.main
    sliding = c.has(r"הזזה|sliding") or (w > 1.8 and rng.random() < 0.4)
    mirror = c.has(r"מראה|mirror")
    plinth = 0.07
    out: list[trimesh.Trimesh] = []
    out.append(box((w, h - plinth, d * 0.96), (0, plinth + (h - plinth) / 2, -d * 0.02), shade(body, 0.92)))
    out.append(box((w - 0.04, plinth, d - 0.1), (0, plinth / 2, -0.02), shade(body, 0.55)))  # recessed plinth
    out.append(box((w + 0.02, 0.03, d + 0.01), (0, h - 0.015, 0), shade(body, 0.97)))  # top cap
    doors = 1 if w < 0.55 else 2 if w < 1.25 else 3 if w < 2.0 else 4
    if sliding:
        doors = 2 if w < 1.9 else 3
        track_h = h - plinth - 0.06
        for i in range(doors):
            dw = w / doors + 0.03
            x = -w / 2 + (i + 0.5) * w / doors
            z = d / 2 + 0.005 + (0.012 if i % 2 else 0)
            col = GLASS if (mirror and i % 2 == 0) else shade(body, 1.0 if i % 2 else 0.95)
            out.append(box((dw, track_h, 0.018), (x, plinth + track_h / 2 + 0.01, z), col))
            out += handle(x + (dw / 2 - 0.05) * (1 if i % 2 else -1), h * 0.5, z + 0.002, True, 0.28, METAL)
    else:
        dw = w / doors
        for i in range(doors):
            x = -w / 2 + (i + 0.5) * dw
            col = GLASS if (mirror and i == doors - 1) else shade(body, 1.02)
            out.append(box((dw - 0.012, h - plinth - 0.06, 0.02), (x, plinth + (h - plinth - 0.03) / 2, d / 2 + 0.008), col))
            side = 1 if i % 2 == 0 else -1
            out += handle(x + side * (dw / 2 - 0.05) * (-1), h * 0.5, d / 2 + 0.018, True, 0.26, METAL if rng.random() < 0.7 else BRASS)
    return out


def build_storage(c: Ctx) -> list[trimesh.Trimesh]:
    w, d, h, rng = c.w, c.d, c.h, c.rng
    body = WHITE if c.pal.pale else c.main
    out: list[trimesh.Trimesh] = []
    if c.has(r"ספרי|מדפ|bookcase|shelf|shelving|BILLY|KALLAX|מערכת אחסון"):
        return build_shelf_unit(c)
    bedside = w < 0.62 and h < 0.7
    chest = h >= 0.7 and w < 1.3 and not c.has(r"דלת|doors?")
    low = h < 0.95 and w >= 0.9
    legs_on = rng.random() < 0.65 and h < 1.3
    leg_h = rng.choice([0.1, 0.14, 0.2]) if legs_on else 0.0
    style = "peg" if legs_on else "block"
    out.append(box((w, h - leg_h, d), (0, leg_h + (h - leg_h) / 2, 0), body))
    out.append(box((w + 0.02, 0.025, d + 0.02), (0, h - 0.0125, 0), shade(body, 1.04)))
    if legs_on:
        out += corner_legs(w, d, leg_h, style, c.wood, 0.06, 0.025)
    knob_col = METAL if rng.random() < 0.6 else BRASS
    if chest or bedside:
        rows = 2 if bedside else max(3, min(6, int(round((h - leg_h) / 0.22))))
        for r in range(rows):
            y = leg_h + (h - leg_h - 0.03) * (r + 0.5) / rows
            out.append(box((w - 0.03, (h - leg_h - 0.05) / rows - 0.012, 0.02), (0, y, d / 2 + 0.008), shade(body, 1.02)))
            if rng.random() < 0.5:
                out += knob(-w * 0.2, y, d / 2 + 0.018, knob_col)
                out += knob(w * 0.2, y, d / 2 + 0.018, knob_col)
            else:
                out += handle(0, y, d / 2 + 0.018, False, min(0.16, w * 0.4), knob_col)
    else:
        doors = 1 if w < 0.6 else 2 if w < 1.3 else 3 if w < 1.9 else 4
        for i in range(doors):
            dw = w / doors
            x = -w / 2 + (i + 0.5) * dw
            out.append(box((dw - 0.012, h - leg_h - 0.05, 0.02), (x, leg_h + (h - leg_h - 0.03) / 2, d / 2 + 0.008), shade(body, 1.02)))
            out += handle(x + (dw / 2 - 0.05) * (-1 if i % 2 == 0 else 1), leg_h + (h - leg_h) * (0.6 if not low else 0.5), d / 2 + 0.018, not low, 0.2 if not low else 0.12, knob_col)
    return out


def build_shelf_unit(c: Ctx) -> list[trimesh.Trimesh]:
    w, d, h, rng = c.w, c.d, c.h, c.rng
    body = WHITE if c.pal.pale else c.main
    out: list[trimesh.Trimesh] = []
    t = 0.022
    for sx in (-1, 1):
        out.append(box((t, h, d), (sx * (w / 2 - t / 2), h / 2, 0), body))
    out.append(box((w - 2 * t, h - 0.02, 0.008), (0, h / 2, -d / 2 + 0.004), shade(body, 0.85)))  # back panel
    n = max(3, min(8, int(h / 0.33)))
    for i in range(n + 1):
        y = 0.04 + (h - 0.04 - t) * i / n
        out.append(box((w - 2 * t, t, d), (0, y + t / 2, 0), shade(body, 1.02)))
    if w > 0.9:  # vertical divider
        out.append(box((t, h - 0.04, d * 0.98), (0, h / 2, 0), body))
    # a few books / boxes for the filled look
    for i in range(1, n):
        y0 = 0.04 + (h - 0.04 - t) * i / n + t
        if rng.random() < 0.55:
            bx = rng.uniform(-w * 0.3, w * 0.3)
            out.append(box((0.22, (h - 0.04) / n * 0.6, d * 0.7), (bx, y0 + (h - 0.04) / n * 0.3, 0), mix(c.pal.accent, WHITE, rng.uniform(0.1, 0.5))))
    return out


def build_tv_unit(c: Ctx) -> list[trimesh.Trimesh]:
    w, d, h, rng = c.w, c.d, c.h, c.rng
    body = c.main if not c.pal.pale else WHITE
    floating = rng.random() < 0.3
    leg_h = 0.0 if floating else rng.choice([0.0, 0.12, 0.16])
    out: list[trimesh.Trimesh] = []
    bh = min(h, 0.55) - leg_h
    y0 = leg_h + (0.25 if floating else 0.0)
    out.append(box((w, bh, d), (0, y0 + bh / 2, 0), body))
    out.append(box((w + 0.02, 0.025, d + 0.02), (0, y0 + bh - 0.0125, 0), shade(body, 1.05)))
    cols = max(2, min(5, int(round(w / 0.45))))
    for i in range(cols):
        x = -w / 2 + (i + 0.5) * w / cols
        if i % 2 == 0 or cols == 2:
            out.append(box((w / cols - 0.015, bh - 0.05, 0.018), (x, y0 + bh / 2, d / 2 + 0.008), shade(body, 1.03)))
            out += handle(x, y0 + bh / 2, d / 2 + 0.017, False, 0.08, METAL)
        else:
            out.append(box((w / cols - 0.03, bh - 0.08, d * 0.7), (x, y0 + bh / 2, d * 0.1), shade(body, 0.3)))  # open compartment
    if leg_h > 0:
        out += corner_legs(w, d, leg_h, "peg", c.wood, 0.1, 0.025)
    if h > 0.65:  # tall unit: add a top slab to read as a media console
        out.append(box((w * 0.9, h - bh - leg_h, d * 0.9), (0, leg_h + bh + (h - bh - leg_h) / 2, 0), shade(body, 0.95)))
    return out


def build_lighting(c: Ctx) -> list[trimesh.Trimesh]:
    w, d, h, rng = c.w, c.d, c.h, c.rng
    pendant = c.has(r"תלייה|תלויה|pendant|chandelier|נברשת|ceiling")
    wall = c.has(r"קיר|wall")
    table = h < 0.8 and not pendant and not wall
    shade_col = mix(c.main, WHITE, 0.35) if not c.pal.pale else (250, 244, 224)
    metal = rng.choice([METAL, BRASS, WOOD_DARK])
    out: list[trimesh.Trimesh] = []
    r = max(w, d) / 2
    if pendant:
        sh = min(h * 0.6, 0.4)
        out.append(cylinder(0.008, h - sh, (0, sh + (h - sh) / 2, 0), metal, 8))
        out.append(rbox((r * 2, sh * 1.05, r * 2), (0, sh / 2, 0), shade_col, 0.7, 32, 14))
    elif table or wall:
        out.append(rbox((r * 1.1, 0.03, r * 1.1), (0, 0.015, 0), metal, 0.6, 24, 8))
        out.append(cylinder(0.014, h * 0.6, (0, h * 0.3, 0), metal, 10))
        sh = h * 0.42
        out.append(frustum(r * 0.75, r, sh, (0, h - sh / 2, 0), shade_col, 28))
    else:  # floor lamp
        out.append(rbox((r * 1.1, 0.03, r * 1.1), (0, 0.015, 0), metal, 0.6, 24, 8))
        out.append(cylinder(0.014, h * 0.78, (0, h * 0.39, 0), metal, 10))
        sh = h * 0.22
        out.append(frustum(r * 0.7, r * 0.9, sh, (0, h - sh / 2, 0), shade_col, 28))
    return out


def build_appliance(c: Ctx) -> list[trimesh.Trimesh]:
    w, d, h = c.w, c.d, c.h
    body = WHITE if c.pal.pale else (c.main if c.pal.main[0] > 150 else mix(c.main, METAL, 0.3))
    steel = (196, 200, 206)
    out: list[trimesh.Trimesh] = []
    out.append(rbox((w, h, d), (0, h / 2, 0), body, 0.08))
    z = d / 2
    if c.has(r"מקרר|fridge|refrigerator|קירור|מקפיא"):
        split = h * 0.34 if h > 1.4 else h * 0.55
        out.append(box((w - 0.02, 0.012, 0.01), (0, h - split, z + 0.003), shade(body, 0.6)))
        out += handle(w / 2 - 0.07, h - split + 0.2, z + 0.012, True, 0.35, steel)
        out += handle(w / 2 - 0.07, h - split - 0.2, z + 0.012, True, 0.35, steel)
        if w > 0.75:  # side-by-side
            out.append(box((0.01, h - 0.04, 0.01), (0, h / 2, z + 0.003), shade(body, 0.6)))
    elif c.has(r"כביסה|washer|washing|מייבש|dryer"):
        out.append(box((w - 0.04, 0.1, 0.01), (0, h - 0.07, z + 0.004), shade(body, 0.9)))
        out.append(frustum(w * 0.34, w * 0.34, 0.03, (0, h * 0.45, z + 0.012), (60, 66, 74), 32))
        out[-1].apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0], [0, h * 0.45, z]))
        out.append(box((0.06, 0.03, 0.01), (w * 0.28, h - 0.07, z + 0.01), (90, 95, 100)))
    elif c.has(r"תנור|oven|מיקרוגל|microwave"):
        out.append(box((w * 0.8, h * 0.45, 0.01), (0, h * 0.42, z + 0.004), (40, 44, 50)))
        out += handle(0, h * 0.7, z + 0.012, False, w * 0.7, steel)
        for i in range(4):
            out += knob(-w * 0.3 + i * w * 0.2, h * 0.88, z + 0.004, steel)
    elif c.has(r"מדיח|dishwasher"):
        out += handle(0, h - 0.1, z + 0.012, False, w * 0.7, steel)
        out.append(box((w - 0.04, 0.05, 0.01), (0, h - 0.04, z + 0.004), shade(body, 0.85)))
    else:
        out += handle(w / 2 - 0.06, h * 0.6, z + 0.012, True, h * 0.3, steel)
    return out


def build_decor(c: Ctx) -> list[trimesh.Trimesh]:
    w, d, h, rng = c.w, c.d, c.h, c.rng
    out: list[trimesh.Trimesh] = []
    if c.has(r"שטיח|rug|carpet"):
        round_rug = c.has(r"עגול|round") or abs(w - d) < 0.05
        e = 0.9 if round_rug else 0.1
        out.append(rbox((w, max(h, 0.012), d), (0, max(h, 0.012) / 2, 0), c.main, e, 40, 8))
        out.append(rbox((w * 0.8, max(h, 0.012) * 1.1, d * 0.8), (0, max(h, 0.012) / 2 + 0.001, 0), mix(c.main, c.pal.accent, 0.55), e, 40, 8))
        return out
    if c.has(r"מראה|mirror"):
        t = max(d, 0.03)
        out.append(box((w, h, t), (0, h / 2, 0), c.wood))
        out.append(box((w - 0.06, h - 0.06, t * 0.5), (0, h / 2, t * 0.3), GLASS))
        return out
    if c.has(r"עציץ|צמח|plant|pot|אדנית"):
        pot_h = h * 0.4
        out.append(frustum(w * 0.32, w * 0.24, pot_h, (0, pot_h / 2, 0), c.main, 24))
        for i in range(7):
            ang = i * 0.9
            out.append(rbox((w * 0.4, h * 0.3, w * 0.4), (np.cos(ang) * w * 0.2, pot_h + h * (0.2 + 0.07 * (i % 4)), np.sin(ang) * w * 0.2), (62, 130, 72), 0.8, 16, 10))
        return out
    if c.has(r"אגרטל|vase"):
        out.append(rbox((w, h, d), (0, h / 2, 0), c.main, 0.8, 24, 14))
        return out
    out.append(rbox((w, h, d), (0, h / 2, 0), c.main, 0.2))
    return out


def build_other(c: Ctx) -> list[trimesh.Trimesh]:
    if c.has(r"ספרי|מדפ|bookcase|shelf|shelving|BILLY|KALLAX"):
        return build_shelf_unit(c)
    return [rbox((c.w, c.h, c.d), (0, c.h / 2, 0), c.main, 0.15)]


_BUILDERS: dict[str, Callable[[Ctx], list[trimesh.Trimesh]]] = {
    "sofa": lambda c: build_sofa(c),
    "armchair": lambda c: build_sofa(c, armchair=True),
    "chair": build_chair,
    "coffee_table": lambda c: build_table(c, "coffee_table"),
    "dining_table": lambda c: build_table(c, "dining_table"),
    "desk": lambda c: build_table(c, "desk"),
    "bed": build_bed,
    "wardrobe": build_wardrobe,
    "storage": build_storage,
    "tv_unit": build_tv_unit,
    "lighting": build_lighting,
    "appliance": build_appliance,
    "decor": build_decor,
    "other": build_other,
}

DEFAULT_PALETTES: dict[str, Palette] = {
    "sofa": Palette((96, 125, 139), (150, 110, 75)),
    "armchair": Palette((161, 136, 127), (90, 64, 55)),
    "coffee_table": Palette((190, 160, 125), (96, 66, 46)),
    "dining_table": Palette((190, 160, 125), (96, 66, 46)),
    "desk": Palette((190, 160, 125), (96, 66, 46)),
    "chair": Palette((188, 170, 164), (121, 85, 72)),
    "bed": Palette((150, 140, 132), (120, 100, 90)),
    "tv_unit": Palette((170, 140, 110), (60, 50, 45)),
    "wardrobe": Palette((222, 214, 204), (120, 120, 120)),
    "storage": Palette((205, 190, 170), (90, 70, 55)),
    "appliance": Palette((236, 239, 241), (176, 190, 197)),
    "lighting": Palette((255, 241, 190), (66, 66, 66)),
    "decor": Palette((128, 190, 180), (90, 140, 135)),
    "other": Palette((176, 190, 197), (120, 130, 135)),
}


def build_model(
    category: str,
    w_cm: float,
    d_cm: float,
    h_cm: float,
    palette: Optional[Palette] = None,
    title: str = "",
    seed: int = 0,
) -> trimesh.Scene:
    """Build a procedural model. ``seed`` (product id) makes style choices stable per product, different across products."""
    w, d, h = max(w_cm, 5) / 100.0, max(d_cm, 5) / 100.0, max(h_cm, 1) / 100.0
    pal = palette or DEFAULT_PALETTES.get(category, DEFAULT_PALETTES["other"])
    ctx = Ctx(w, d, h, pal, title or "", random.Random(seed * 7919 + len(title)))
    parts = _BUILDERS.get(category, build_other)(ctx)
    scene = trimesh.Scene()
    for i, m in enumerate(parts):
        _ = m.vertex_normals  # computed so smooth shading is exported
        scene.add_geometry(m, node_name=f"part_{i}", geom_name=f"part_{i}")
    # sit exactly on the floor
    lo = scene.bounds[0][1]
    if abs(lo) > 1e-6:
        scene.apply_translation([0, -lo, 0])
    return scene
