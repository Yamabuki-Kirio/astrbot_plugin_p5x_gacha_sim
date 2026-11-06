import json
from src.core.registry import Registry
from src.render.renderer import Renderer


def test_every_available_character_has_reviewed_placement():
    renderer = Renderer()
    for item in Registry.load().items.values():
        if item.kind not in {"char", "character"}:
            continue
        if renderer._character_pair(item) or renderer.portrait(item):
            placement = renderer._placement(item)
            assert placement, item.id
            assert all(0 < value < 1 for value in placement["face"]), item.id
            assert 0 < placement["face_width"] < 1, item.id


def test_every_persona_has_reviewed_focus():
    renderer = Renderer()
    placements = json.loads((renderer.assets / "persona_placement.json").read_text(encoding="utf-8"))
    for item in Registry.load().items.values():
        if item.kind == "persona":
            assert item.id in placements, item.id
            assert all(0 < value < 1 for value in placements[item.id]["focus"])


def test_five_star_foundation_occupies_ninety_percent_of_canvas():
    from src.render.renderer import foundation_geometry, DESIGN_H
    for slot in range(10):
        geo = foundation_geometry(slot, 5)
        assert abs(geo.height / DESIGN_H - .90) < .001
        assert geo.top >= 0
        assert max(y for x,y in geo.quad) <= DESIGN_H
