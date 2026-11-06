"""从 P5X BWIKI 面具图鉴导入 2★/3★ 人格面具及透明立绘。"""

from __future__ import annotations

import html
import io
import json
import re
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PAGE_URL = "https://wiki.biligame.com/nsywl/%E9%9D%A2%E5%85%B7%E5%9B%BE%E9%89%B4"
USER_AGENT = "Mozilla/5.0 (compatible; P5X-Gacha-Asset-Importer/1.0)"
ROW_RE = re.compile(
    r'<tr(?P<attrs>[^>]*)data-param3="(?P<rarity>[23])"[^>]*>.*?'
    r'<img[^>]+src="(?P<image>https://patchwiki\.biligame\.com/images/nsywl/[^\"]+)".*?'
    r'<td><a[^>]+title="(?P<name>[^"]+)">',
    re.S,
)


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def clean_name(value: str) -> str:
    return html.unescape(value).replace("【人格面具】", "").strip()


def main() -> None:
    page = fetch(PAGE_URL).decode("utf-8")
    rows = [
        {"name": clean_name(match["name"]), "rarity": int(match["rarity"]), "url": match["image"],
         "element": (re.search(r'data-param2="([^"]+)"', match["attrs"])[1]
                     if re.search(r'data-param2="([^"]+)"', match["attrs"]) else "")}
        for match in ROW_RE.finditer(page)
    ]
    if len(rows) != 60 or sum(row["rarity"] == 2 for row in rows) != 27:
        raise RuntimeError(f"图鉴结构异常：解析到 {len(rows)} 项")

    target = ROOT / "assets" / "library" / "personas"
    target.mkdir(parents=True, exist_ok=True)
    items = []
    paths = {}
    for index, row in enumerate(rows, 1):
        item_id = f"persona:{row['name']}"
        filename = f"{row['rarity']}star-{index:02d}.webp"
        output = target / filename
        if not output.exists():
            source = Image.open(io.BytesIO(fetch(row["url"]))).convert("RGBA")
            if source.height > 1400:
                width = round(source.width * 1400 / source.height)
                source = source.resize((width, 1400), Image.Resampling.LANCZOS)
            source.save(output, "WEBP", quality=88, method=6)
        items.append({
            "id": item_id,
            "name": row["name"],
            "rarity": row["rarity"],
            "source_url": row["url"],
            "element": row["element"],
            "element_source": PAGE_URL,
        })
        paths[item_id] = output.relative_to(ROOT / "assets").as_posix()
        print(f"[{index:02d}/{len(rows)}] {row['rarity']}★ {row['name']}")

    personas_path = ROOT / "data" / "items" / "personas.json"
    personas_path.write_text(json.dumps({
        "_comment": "BWIKI图鉴2/3星素材与属性；非已核实的实际契约卡池名单。",
        "source": PAGE_URL,
        "items": items,
        "status": "verified_from_bwiki",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    banners_path = ROOT / "data" / "banners.json"
    banners = json.loads(banners_path.read_text(encoding="utf-8"))
    by_rarity = {rarity: [item["id"] for item in items if item["rarity"] == rarity] for rarity in (2, 3)}
    for banner in banners:
        pool = banner.get("pool", {})
        for rarity in (2, 3):
            if str(rarity) in pool:
                pool[str(rarity)] = by_rarity[rarity]
    banners_path.write_text(json.dumps(banners, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    index_path = ROOT / "data" / "asset_index.json"
    asset_index = json.loads(index_path.read_text(encoding="utf-8"))
    indexed = asset_index.setdefault("items", {})
    for key in [key for key in indexed if key.startswith("persona:")]:
        del indexed[key]
    indexed.update(paths)
    asset_index["persona_source"] = PAGE_URL
    index_path.write_text(json.dumps(asset_index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"完成：{len(items)} 项人格面具，{len(paths)} 张立绘")


if __name__ == "__main__":
    main()
