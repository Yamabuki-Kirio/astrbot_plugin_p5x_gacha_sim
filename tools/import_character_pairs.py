"""按人工视觉核对结果导入角色素材；不修改角色/卡池数据。"""
import json
import shutil
import sys
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.core.registry import Registry
from src.render.renderer import Renderer

SOURCES = [Path(r"C:\Users\Administrator\Downloads\Texture2D-20261106T125440Z-1-001\Texture2D"),
           Path(r"C:\Users\Administrator\Downloads\Sprite-20261106T134141Z-1-001\Sprite")]
ALIASES = {"FLEURET": "seiji", "YUKI": "tembin", "KEY": "kii", "MOKO": "kotomo",
           "MESSA": "doctor", "KIRIJO": "mitsuru", "CLOSER·Tropical": "closerS",
           "MONT·Frostgale": "montManwu", "LUCE·Notte": "luceYY", "SOY·Pioneer": "soyTH",
           "MARIAN·Beachflower": "marianS", "PUPPET·Wavecatcher": "puppetS", "BUI·Cosmic": "buiC"}
SPECIAL = {
    "NOIR": ("Texture-Renzhimoniactivity-noir.png", "Texture-Renzhimoniactivity-noir-02.png"),
    "MATOI": ("lihui-guaidao-matoi.png", "Texture-update-matoi-persona.png"),
    "VIOLET": ("lihui-guaidao-violet.png", "Texture-update-violet-persona.png"),
    "WIND·Tempest": ("lihui-guaidao-windWY.png", "Texture-update-windWY-persona.png"),
    "RIN·Firecracker": ("lihui-guaidao-rinN.png", "Texture-update-rinN-persona.png"),
    "MOKO·Seaside": ("Texture-Renzhimoniactivity-kotomos01.png", "Texture-Renzhimoniactivity-kotomos02.png"),
    "CLOSER·Radiance": ("PC055_01_01_04_01.png", "PC055_01_01_04_02.png"),
    "JOKER·Starlight": ("PC056_01_01_04_01.png", "PC056_01_01_04_02.png"),
    "AEGIS": ("PC063_thief_01_04_01.png", "PC063_thief_01_04_02.png"),
    "MONA·Starlight": ("PC067_01_01_04_01.png", "PC067_01_01_04_02.png"),
    "MIKU": ("PC068_01_01_04_01.png", "PC068_01_01_04_02.png"),
    "PANTHER·Starlight": ("PC073_01_01_04_01.png", "PC073_01_01_04_02.png"),
    "CHORD·Summer": ("PC077_01_01_04_01.png", None),
    "KOTONE": ("PC079_01_01_04_01.png", "PC079_01_01_04_02.png"),
}

def main():
    files = {p.name.casefold(): p for folder in SOURCES for p in folder.glob("*.png")}
    target = ROOT / "assets" / "character_layers"
    target.mkdir(parents=True, exist_ok=True)
    renderer = Renderer()
    manifest, unresolved = {}, []
    prepared = target / "prepared"
    prepared.mkdir(exist_ok=True)
    processed = set()
    for item in Registry.load().items.values():
        if item.kind not in ("char", "character"):
            continue
        code = item.id.split(":", 1)[1]
        names = SPECIAL.get(code)
        if not names and code in ALIASES:
            stem = "lihui-guaidao-"+ALIASES[code]
            names = (stem+".png", stem+"-02.png")
        if not names:
            pair = renderer._character_pair(item)
            names = tuple(p.name for p in pair) if pair else None
        if not names:
            unresolved.append({"id": item.id, "name": item.name, "status": "needs_visual_identification"})
            continue
        paths = [files.get(name.casefold()) if name else None for name in names]
        if not paths[0] or (names[1] and not paths[1]):
            raise FileNotFoundError((item.id, names))
        for path in paths:
            if path:
                shutil.copy2(path, target / path.name)
                if path.name not in processed:
                    with Image.open(path) as source:
                        image = source.convert("RGBA")
                    box = image.getchannel("A").point(lambda a: 255 if a > 16 else 0).getbbox()
                    if box:
                        image = image.crop(box)
                    image.thumbnail((1600,1600), Image.Resampling.LANCZOS)
                    image.save(prepared / path.name)
                    processed.add(path.name)
        manifest[item.id] = {"front": paths[0].name, "back": paths[1].name if paths[1] else None,
                             "name": item.name, "source": [str(p) if p else None for p in paths]}
    (target / "mapping.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "output" / "character_review" / "unresolved.json").write_text(
        json.dumps(unresolved, ensure_ascii=False, indent=2), encoding="utf-8")
    print("mapped", len(manifest), "unresolved", unresolved)

if __name__ == "__main__":
    main()
