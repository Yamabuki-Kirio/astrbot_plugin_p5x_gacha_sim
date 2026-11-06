"""固定结果的视觉验收图：不抽样、不改卡池。"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw
from src.core.registry import Registry
from src.core.mechanics import PullResult
from src.render.renderer import Renderer, encode


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "output" / "acceptance"
    output.mkdir(parents=True, exist_ok=True)
    registry = Registry.load()
    renderer, structure = Renderer(), Renderer()
    structure.art_layer = lambda *args, **kwargs: None
    low_ids = ["persona:皮克希", "persona:杰克灯笼", "persona:和魂", "persona:奇魂",
               "persona:木叶天狗", "persona:阴摩罗鬼", "persona:犬神", "persona:克鲁波克鲁",
               "persona:百臂巨人", "persona:黑软泥怪"]
    low = [registry.items[key] for key in low_ids]
    five = sorted(registry.banner("char_limited").pool[5], key=lambda item: item.id)
    four = sorted(registry.banner("char_limited").pool[4], key=lambda item: item.id)
    def results(items):
        return [PullResult(item, item.rarity, False, index+1, 0, 0) for index,item in enumerate(items)]
    groups = {
        "01_all_low": low,
        "02_one_four": low[:9]+four[:1],
        "03_one_five": low[:9]+five[:1],
        "04_two_five_one_four": low[:7]+five[:2]+four[:1],
        "05_multi_high": low[:2]+five[:4]+four[:4],
    }
    reference_items = low[:7] + [registry.items["char:J&C"], registry.items["char:J&C"],
                                  registry.items["char:SEPIA"]]
    (output / "09_character_pairs.jpg").write_bytes(
        encode(renderer.render_ten(results(reference_items)), quality=95))
    for name, codes in {
        "10_alias_characters": ["FLEURET", "YUKI", "KEY", "MOKO", "MESSA", "NOIR", "KIRIJO",
                                 "MATOI", "VIOLET", "MONT·Frostgale"],
        "11_numbered_characters": ["CLOSER·Radiance", "JOKER·Starlight", "AEGIS", "MONA·Starlight",
                                    "MIKU", "PANTHER·Starlight", "KOTONE", "BUI·Cosmic",
                                    "LUCE·Notte", "SOY·Pioneer"],
    }.items():
        items = [registry.items["char:"+code] for code in codes]
        (output / f"{name}.jpg").write_bytes(encode(renderer.render_ten(results(items)), quality=95))
    manifest = {}
    sheets = []
    for name, items in groups.items():
        image = structure.render_ten(results(items))
        path = output / f"{name}.jpg"
        path.write_bytes(encode(image, quality=95))
        manifest[name] = {"items": [item.id for item in items], "size": image.size,
                          "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest()}
        sheets.append((name, image))
    character = renderer.render_ten(results(groups["04_two_five_one_four"]))
    (output / "06_character.jpg").write_bytes(encode(character, quality=95))
    sheets.append(("06_character (art positioning paused)", character))
    # 仅验证武器渲染；实际武器池低星含人格面具，不在本轮改动卡池。
    weapon_items = []
    for rarity, count in ((5, 2), (4, 3), (3, 5)):
        weapon_items.extend(sorted((item for item in registry.items.values()
                                    if item.kind == "weapon" and item.rarity == rarity),
                                   key=lambda item: item.id)[:count])
    if len(weapon_items) != 10:
        raise RuntimeError("武器固定组必须有10项")
    weapon_image = renderer.render_ten(results(weapon_items))
    (output / "07_weapon.jpg").write_bytes(encode(weapon_image, quality=95))
    for name, items, image in (("06_character", groups["04_two_five_one_four"], character),
                               ("07_weapon", weapon_items, weapon_image)):
        manifest[name] = {"items": [item.id for item in items], "size": image.size,
                          "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest()}
    for rarity, item in ((2, low[0]), (4, four[0]), (5, five[0])):
        image = renderer.render_single(results([item])[0])
        name = f"08_single_{rarity}"
        (output / f"{name}.jpg").write_bytes(encode(image, quality=95))
        manifest[name] = {"items": [item.id], "size": image.size,
                          "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest()}
    # 输出接触表，不依靠浏览器拼图；每格是完整16:9缩略图。
    contact = Image.new("RGB", (1920, 1710), (12,13,18))
    draw = ImageDraw.Draw(contact)
    for index, (name, image) in enumerate(sheets):
        x,y = (index%2)*960, (index//2)*570
        draw.text((x+12,y+8), name, font=renderer.font(20, latin=True), fill="white")
        contact.paste(image.resize((960,540), Image.Resampling.LANCZOS), (x,y+30))
    contact.save(output / "contact.jpg", quality=93)
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
