"""The element reference sheet (2026-09-18): drawn on save as a job,
listed LAST among the element's photos, never banked on the Assets
wall, and never able to fail the element that asked for it."""
from pathlib import Path

import pytest

from src import element_sheet, nano_banana


def test_every_kind_has_a_prompt_and_it_fills():
    for kind in element_sheet.KINDS:
        text = element_sheet.prompt_for(kind, "Michael", "the rider", "white leathers")
        assert "MICHAEL" in text and "{" not in text and "}" not in text
    character = element_sheet.prompt_for("character", "Michael", "the rider", "white leathers")
    assert "FACE CLOSE UP" in character and "ROLE: THE RIDER" in character
    assert "white leathers" in character
    assert "PLACE: GARAGE" in element_sheet.prompt_for("location", "garage")
    with pytest.raises(ValueError):
        element_sheet.prompt_for("render", "x")


def test_the_sheet_prompt_leaves_no_placeholder_when_the_row_is_bare():
    text = element_sheet.prompt_for("prop", "Ducati 959")
    assert "TYPE: —" in text and "as in the attached photos" in text


def test_is_sheet_names_only_the_drawn_file():
    assert element_sheet.is_sheet("sheet.jpg") and element_sheet.is_sheet("SHEET.png")
    assert not element_sheet.is_sheet("IMG_0001.jpg")
    assert not element_sheet.is_sheet("sheet-music.jpg")


def test_draw_grounds_on_the_real_photos_and_lands_as_sheet_jpg(tmp_path, monkeypatch):
    folder = tmp_path / "michael"
    folder.mkdir()
    (folder / "b.jpg").write_bytes(b"photo-b")
    (folder / "a.jpg").write_bytes(b"photo-a")
    (folder / "sheet.jpg").write_bytes(b"an old drawing")   # a redraw must not ground on it
    rendered = tmp_path / "wf.png"
    rendered.write_bytes(b"\x89PNG-not-really")
    calls = []

    def fake_generate(prompt, **kw):
        calls.append((prompt, kw))
        return {"ok": True, "path": str(rendered), "generation_id": 7}

    monkeypatch.setattr(nano_banana, "generate_from_prompt", fake_generate)
    result = element_sheet.draw("character", "Michael",
                                [folder / "a.jpg", folder / "sheet.jpg", folder / "b.jpg"],
                                folder, detail="the rider", account_id=1)
    assert result["ok"] and result["generation_id"] == 7
    assert result["path"] == folder / "sheet.jpg"
    assert result["path"].read_bytes() != b"an old drawing"
    [(prompt, kw)] = calls
    assert "FACE CLOSE UP" in prompt
    assert kw["literal"] is True and kw["bank"] is False
    assert kw["source"] == "element_sheet" and kw["aspect_ratio"] == "16:9"
    assert [label for label, _ in kw["reference_image"]] == ["Michael — photo 1", "Michael — photo 2"]
    assert [data for _, data in kw["reference_image"]] == [b"photo-a", b"photo-b"]


def test_draw_never_raises_and_reports_the_reason(tmp_path, monkeypatch):
    folder = tmp_path / "x"
    folder.mkdir()
    assert element_sheet.draw("prop", "x", [], folder)["error"] == "no photos to draw the sheet from"
    (folder / "a.jpg").write_bytes(b"photo")
    monkeypatch.setattr(nano_banana, "generate_from_prompt",
                        lambda *a, **k: {"ok": False, "error": "daily cap"})
    assert element_sheet.draw("prop", "x", [folder / "a.jpg"], folder)["error"] == "daily cap"
    monkeypatch.setattr(nano_banana, "generate_from_prompt",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert element_sheet.draw("prop", "x", [folder / "a.jpg"], folder)["error"] == "boom"
    assert not (folder / "sheet.jpg").exists()


def test_literal_skips_the_still_frame_wrapper_and_bank_false_keeps_it_off_the_wall(
        tmp_path, monkeypatch):
    """The two flags the sheet relies on, checked on the lane itself."""
    from src import generative, render_assets
    seen = {}
    monkeypatch.setattr(nano_banana, "has_key", lambda a=None: True)
    monkeypatch.setattr(generative, "init", lambda **k: None)
    monkeypatch.setattr(generative, "cap_error", lambda *a, **k: None)
    monkeypatch.setattr(nano_banana, "generations_today", lambda **k: 0)
    monkeypatch.setattr(nano_banana, "RENDER_DIR", tmp_path)

    def fake_image(prompt, out_path, **kw):
        seen["prompt"] = prompt
        Path(out_path).write_bytes(b"png")
        return out_path

    monkeypatch.setattr(nano_banana, "generate_image", fake_image)
    monkeypatch.setattr(nano_banana, "_shot_row_for_prompt", lambda *a, **k: 1)
    monkeypatch.setattr(generative, "record_generation",
                        lambda *a, **k: seen.setdefault("params", k["params"]) and 42)
    monkeypatch.setattr(render_assets, "record_best_effort",
                        lambda **k: seen.setdefault("banked", True) or {"id": 1, "rag": None})
    from src import storage
    monkeypatch.setattr(storage, "configured", lambda: False)

    out = nano_banana.generate_from_prompt("Five panels, FACE CLOSE UP first",
                                           literal=True, bank=False, source="element_sheet",
                                           account_id=1)
    assert out["ok"], out
    assert seen["prompt"] == "Five panels, FACE CLOSE UP first"
    assert seen["params"]["framing"] == "literal" and seen["params"]["source"] == "element_sheet"
    assert "banked" not in seen and out["asset_id"] is None
