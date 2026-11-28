"""Wall auto-detection on synthetic floorplans."""
import io
import math

from PIL import Image, ImageDraw

from app.services.wall_detect import detect_walls

PPC = 0.5  # px per cm
BLUE = (110, 130, 200)


def make_plan() -> Image.Image:
    """A 600x400 cm room (20 cm walls) with a 90 cm door gap in the bottom wall and thin 'text' clutter."""
    img = Image.new("RGB", (400, 300), "white")
    d = ImageDraw.Draw(img)
    s = PPC
    x0, y0, x1, y1, t = 50, 40, 350, 240, 10  # px; walls drawn centred on these coordinates

    def rect(a, b, c, e):
        d.rectangle([a, b, c, e], fill=BLUE)

    rect(x0 - t / 2, y0 - t / 2, x1 + t / 2, y0 + t / 2)  # top
    rect(x0 - t / 2, y0 - t / 2, x0 + t / 2, y1 + t / 2)  # left
    rect(x1 - t / 2, y0 - t / 2, x1 + t / 2, y1 + t / 2)  # right
    gap0, gap1 = 150, 195  # 45 px = 90 cm door gap
    rect(x0 - t / 2, y1 - t / 2, gap0, y1 + t / 2)
    rect(gap1, y1 - t / 2, x1 + t / 2, y1 + t / 2)
    # thin clutter that must be ignored: dimension line, text-ish scribbles, furniture outline
    d.line([(60, 10), (340, 10)], fill=(0, 0, 0), width=1)
    d.line([(100, 120), (160, 120)], fill=(0, 0, 0), width=2)
    d.rectangle([200, 100, 260, 160], outline=(90, 90, 90), width=2)
    return img


def test_detects_room_walls_and_door():
    walls = detect_walls(make_plan(), PPC)
    horiz = [w for w in walls if w.y1 == w.y2]
    vert = [w for w in walls if w.x1 == w.x2]
    assert len(vert) == 2 and len(horiz) == 2  # clutter ignored; bottom wall bridged across the door gap

    top = min(horiz, key=lambda w: w.y1)
    bottom = max(horiz, key=lambda w: w.y1)
    assert abs(top.y1 - 80) <= 4 and abs(top.x1 - 100) <= 6 and abs(top.x2 - 700) <= 6  # 600 cm wide
    assert abs(bottom.y1 - 480) <= 4
    assert 15 <= top.thicknessCm <= 25
    left = min(vert, key=lambda w: w.x1)
    assert abs(left.x1 - 100) <= 4 and abs(left.y2 - 480) <= 6

    assert len(bottom.openings) == 1
    door = bottom.openings[0]
    assert door["kind"] == "door" and door["sillCm"] == 0 and door["heightCm"] == 210
    assert 80 <= door["widthCm"] <= 110
    center_x = bottom.x1 + door["offsetCm"]
    assert abs(center_x - (150 + 195) / 2 / PPC) <= 8


def test_wide_gap_becomes_window():
    img = Image.new("RGB", (400, 200), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([20, 50, 120, 60], fill=BLUE)
    d.rectangle([220, 50, 380, 60], fill=BLUE)  # 100 px = 200 cm gap
    walls = detect_walls(img, PPC)
    assert len(walls) == 1 and walls[0].openings[0]["kind"] == "window"
    assert walls[0].openings[0]["sillCm"] == 90


def test_blank_plan_has_no_walls():
    assert detect_walls(Image.new("RGB", (300, 300), "white"), PPC) == []


def test_detect_walls_endpoint(client):
    buf = io.BytesIO()
    make_plan().save(buf, "PNG")
    up = client.post("/api/floorplans/upload", files={"file": ("p.png", buf.getvalue(), "image/png")}).json()
    r = client.post("/api/floorplans/detect-walls", json={"url": up["url"], "pixels_per_cm": PPC})
    assert r.status_code == 200
    body = r.json()
    assert len(body["walls"]) == 4
    assert any(w["openings"] for w in body["walls"])
    assert math.isfinite(body["walls"][0]["x1"])

    assert client.post("/api/floorplans/detect-walls", json={"url": "/static/floorplans/nope.png", "pixels_per_cm": 1}).status_code == 404
    assert client.post("/api/floorplans/detect-walls", json={"url": "/static/floorplans/../../x.png", "pixels_per_cm": 1}).status_code == 404
    assert client.post("/api/floorplans/detect-walls", json={"url": up["url"], "pixels_per_cm": 0}).status_code == 422


def test_auto_scale_estimation_from_wall_thickness():
    from app.services.wall_detect import detect_walls_auto

    walls, ppc, estimated = detect_walls_auto(make_plan(), None)
    assert estimated and ppc is not None
    assert abs(ppc - PPC) / PPC < 0.15  # 10 px walls at 20 cm -> 0.5 px/cm
    assert len(walls) == 4
    top = min((w for w in walls if w.y1 == w.y2), key=lambda w: w.y1)
    assert abs((top.x2 - top.x1) - 600) <= 90  # within the accuracy of the thickness assumption

    walls2, ppc2, est2 = detect_walls_auto(make_plan(), PPC)
    assert not est2 and ppc2 == PPC and len(walls2) == 4


def test_auto_scale_downsizes_huge_images_and_reports_original_scale():
    from app.services.wall_detect import detect_walls_auto

    big = make_plan().resize((1600 * 2, 1200 * 2), Image.NEAREST)  # same plan at 4x resolution
    walls, ppc, estimated = detect_walls_auto(big, None)
    assert estimated and abs(ppc - PPC * 8) / (PPC * 8) < 0.15
    assert len(walls) == 4


def test_analyze_endpoint_without_scale_and_extra_upload_formats(client):
    buf = io.BytesIO()
    make_plan().save(buf, "PNG")
    up = client.post("/api/floorplans/upload", files={"file": ("p.png", buf.getvalue(), "image/png")}).json()
    r = client.post("/api/floorplans/detect-walls", json={"url": up["url"]})
    body = r.json()
    assert r.status_code == 200 and body["scale_estimated"] is True
    assert abs(body["pixels_per_cm"] - PPC) / PPC < 0.15 and len(body["walls"]) == 4

    for fmt, mime in (("BMP", "image/bmp"), ("TIFF", "image/tiff"), ("GIF", "image/gif")):
        b = io.BytesIO()
        make_plan().save(b, fmt)
        r = client.post("/api/floorplans/upload", files={"file": (f"p.{fmt.lower()}", b.getvalue(), mime)})
        assert r.status_code == 200 and r.json()["url"].endswith(".png"), fmt


def _room_with_hollow_partition() -> Image.Image:
    """Solid outer walls plus an interior partition drawn as TWO thin parallel lines (hollow wall)."""
    img = Image.new("RGB", (460, 300), "white")
    d = ImageDraw.Draw(img)
    t = 10
    d.rectangle([40, 40, 420, 40 + t], fill=BLUE)  # top
    d.rectangle([40, 240, 420, 240 + t], fill=BLUE)  # bottom
    d.rectangle([40, 40, 40 + t, 250], fill=BLUE)  # left
    d.rectangle([410, 40, 420, 250], fill=BLUE)  # right
    # hollow partition at x=230: two 1px dark lines 8px apart, running between top and bottom walls
    d.line([(226, 50), (226, 240)], fill=(60, 60, 60), width=1)
    d.line([(234, 50), (234, 240)], fill=(60, 60, 60), width=1)
    # a dimension line OUTSIDE the building must not become a wall
    d.line([(40, 15), (420, 15)], fill=(0, 0, 0), width=1)
    return img


def test_hollow_double_line_partition_is_found_and_flagged_thin():
    walls = detect_walls(_room_with_hollow_partition(), PPC)
    vertical = sorted((w for w in walls if w.x1 == w.x2), key=lambda w: w.x1)
    assert len(vertical) == 3  # left, right and the hollow partition between them
    partition = vertical[1]
    assert partition.thin and abs(partition.x1 - 460) <= 12  # x = 230 px / 0.5 px per cm
    assert not vertical[0].thin and not vertical[2].thin
    assert all(w.y1 > 50 for w in walls if w.y1 == w.y2)  # the dimension line at y=15 px is ignored


def test_scale_estimate_ignores_thin_partitions():
    from app.services.wall_detect import detect_walls_auto

    _, ppc, estimated = detect_walls_auto(_room_with_hollow_partition(), None)
    assert estimated and abs(ppc - PPC) / PPC < 0.15  # solid 10 px walls = 20 cm -> 0.5 px/cm


# ----------------------------------------------------------------------------- door / window classification

def _room_with_gap(gap0: int, gap1: int, draw) -> Image.Image:
    """Blue room whose TOP wall has a gap [gap0, gap1] px; ``draw(d)`` adds the symbol drawn in the gap."""
    img = Image.new("RGB", (400, 300), "white")
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1, t = 50, 60, 350, 250, 10
    d.rectangle([x0 - t / 2, y0 - t / 2, gap0, y0 + t / 2], fill=BLUE)
    d.rectangle([gap1, y0 - t / 2, x1 + t / 2, y0 + t / 2], fill=BLUE)
    d.rectangle([x0 - t / 2, y0 - t / 2, x0 + t / 2, y1 + t / 2], fill=BLUE)
    d.rectangle([x1 - t / 2, y0 - t / 2, x1 + t / 2, y1 + t / 2], fill=BLUE)
    d.rectangle([x0 - t / 2, y1 - t / 2, x1 + t / 2, y1 + t / 2], fill=BLUE)
    draw(d)
    return img


def test_narrow_gap_with_frame_lines_is_a_window_not_a_door():
    def frame(d):  # three thin lines (4 px apart) across a 44 px (= 88 cm) gap: the window symbol
        for y in (56, 60, 64):
            d.line([(150, y), (194, y)], fill=(40, 40, 40), width=1)

    walls = detect_walls(_room_with_gap(150, 194, frame), PPC)
    top = min((w for w in walls if w.y1 == w.y2), key=lambda w: w.y1)
    assert [o["kind"] for o in top.openings] == ["window"]
    assert top.openings[0]["sillCm"] == 90


def test_door_swing_arc_makes_a_wide_gap_a_door():
    def swing(d):  # 70 px (= 140 cm) gap; leaf + dashed quarter arc swinging into the room
        d.line([(150, 65), (150, 135)], fill=(60, 60, 60), width=1)
        d.arc([80, 65 - 70, 220, 65 + 70], 0, 90, fill=(60, 60, 60), width=1)

    walls = detect_walls(_room_with_gap(150, 220, swing), PPC)
    top = min((w for w in walls if w.y1 == w.y2), key=lambda w: w.y1)
    assert [o["kind"] for o in top.openings] == ["door"]  # without the arc a 140 cm exterior gap would be a window


def test_plain_exterior_gap_keeps_the_width_rule():
    walls = detect_walls(_room_with_gap(150, 220, lambda d: None), PPC)
    top = min((w for w in walls if w.y1 == w.y2), key=lambda w: w.y1)
    assert [o["kind"] for o in top.openings] == ["window"]  # 140 cm on an exterior wall, nothing drawn


# ----------------------------------------------------------------------------- window labels

def _box_walls():
    from app.services.wall_detect import DetectedWall

    return [
        DetectedWall(0, 0, 600, 0, 20, [{"kind": "door", "offsetCm": 200, "widthCm": 88, "heightCm": 210, "sillCm": 0}]),
        DetectedWall(600, 0, 600, 400, 20),
        DetectedWall(0, 400, 600, 400, 20),
        DetectedWall(0, 0, 0, 400, 20),
    ]


def test_window_label_converts_a_door_sized_gap_into_a_window_with_sill():
    from app.services.wall_detect import WindowLabel, apply_window_labels

    walls = _box_walls()
    n = apply_window_labels(walls, [WindowLabel(205, -40, 30, 100, 200)])  # label above the top wall
    assert n == 1
    (o,) = walls[0].openings
    assert o["kind"] == "window" and o["sillCm"] == 30 and o["heightCm"] == 200
    assert o["widthCm"] == 100 and o["offsetCm"] == 200


def test_window_label_creates_a_missed_window_and_defaults_the_height():
    from app.services.wall_detect import WindowLabel, apply_window_labels

    walls = _box_walls()
    assert apply_window_labels(walls, [WindowLabel(450, 440, 110)]) == 1  # below the bottom wall, no size printed
    (o,) = walls[2].openings
    assert o["kind"] == "window" and o["sillCm"] == 110 and o["widthCm"] == 100
    assert o["heightCm"] == 105  # head at ~215 cm
    assert abs(o["offsetCm"] - 450) <= 1


def test_labels_inside_the_building_or_far_from_walls_are_ignored():
    from app.services.wall_detect import WindowLabel, apply_window_labels

    walls = _box_walls()
    assert apply_window_labels(walls, [WindowLabel(300, 200, 110), WindowLabel(1500, -50, 30)]) == 0


def test_label_parser_reads_sill_and_the_stacked_numbers():
    from app.services.ocr_labels import Word, _labels_from_words

    def w(text, cx, cy, h=14):
        return Word(text, 90, cx - 15, cy - h / 2, 30, h, (0, 0, 0))

    words = [w("100", 131, 42), w("200", 131, 64), Word("(+30)", 95, 106, 75, 50, 19, (0, 0, 0)), w("210", 254, 42)]
    ((_, _, lab),) = _labels_from_words(words)
    assert (lab.sill_cm, lab.width_cm, lab.height_cm) == (30, 100, 200)
