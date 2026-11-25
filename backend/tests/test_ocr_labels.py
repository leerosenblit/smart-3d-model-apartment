"""Room-label OCR helpers: fuzzy matching and grouping are pure; Tesseract itself is stubbed."""
from app.services import ocr_labels
from app.services.ocr_labels import Word, group_hints, match_kind


def test_fuzzy_stem_matching_handles_ocr_noise():
    assert match_kind("שינה") == "bedroom"
    assert match_kind("ח.שינה") == "bedroom"
    assert match_kind("הורים") == "master"
    assert match_kind("רחצה") == "bathroom"
    assert match_kind("ח;רחצה?") == "bathroom"
    assert match_kind("קביסה") == "laundry"  # OCR confused כ with ק
    assert match_kind("מ.קביסה.") == "laundry"
    assert match_kind("דיוך") == "living"  # ר read as ך
    assert match_kind("אוכל") == "dining"
    assert match_kind("מרפסת") == "balcony"
    assert match_kind("418") is None and match_kind("ח.") is None and match_kind("טיפוס") is None


def w(text, left, top, line=(1, 1, 1), width=40, height=13, conf=80):
    return Word(text, conf, left, top, width, height, line)


def test_group_hints_merges_words_on_one_line_and_skips_non_rooms():
    words = [
        w("שינה", 774, 468, (4, 1, 1)),
        w("ח.", 823, 468, (4, 1, 1), width=17),
        w("הורים", 700, 468, (4, 1, 1), width=45),
        w("298", 300, 290, (5, 1, 1)),
        w("ח.שינה", 576, 263, (6, 1, 1), width=57),
    ]
    hints = group_hints(words)
    kinds = sorted(h.kinds[0] for h in hints)
    assert len(hints) == 2 and kinds == ["bedroom", "master"] or {"master", "bedroom"} <= {k for h in hints for k in h.kinds}
    master = next(h for h in hints if "master" in h.kinds)
    assert "bedroom" in master.kinds  # one phrase "ח. שינה הורים" carries both
    assert 700 < master.x_px < 860 and abs(master.y_px - 474.5) < 3


def test_room_hints_empty_when_tesseract_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(ocr_labels, "tesseract_cmd", lambda: None)
    ocr_labels.hebrew_available.cache_clear()
    assert ocr_labels.read_words(tmp_path / "x.png") == []
    assert ocr_labels.room_hints(tmp_path / "x.png") == []
    ocr_labels.hebrew_available.cache_clear()
