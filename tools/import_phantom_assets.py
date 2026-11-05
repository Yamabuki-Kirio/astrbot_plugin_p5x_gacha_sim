"""从 ``astrbot_plugin_phantom_archive`` 导入已整理的 P5X 官方素材。"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT.parent / "astrbot_plugin_phantom_archive"
SOURCE_ASSETS = SOURCE / "data" / "assets"
SOURCE_DB = SOURCE / "data" / "p5x_zh.sqlite3"
TARGET_LIBRARY = ROOT / "assets" / "library"
TARGET_INDEX = ROOT / "data" / "asset_index.json"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _copy(relative_path: str) -> str:
    source = SOURCE_ASSETS / relative_path
    target = TARGET_LIBRARY / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return f"library/{relative_path}"


def main() -> None:
    if not SOURCE_DB.exists() or not (SOURCE_ASSETS / "manifest.json").exists():
        raise SystemExit(f"找不到素材仓库：{SOURCE}")
    source_manifest = _load(SOURCE_ASSETS / "manifest.json")
    characters = _load(ROOT / "data" / "items" / "characters.json")
    weapons = _load(ROOT / "data" / "items" / "weapons.json")
    connection = sqlite3.connect(SOURCE_DB)
    rows = connection.execute(
        "SELECT source_key, codename_zh, slug FROM zh_characters WHERE codename_zh IS NOT NULL"
    ).fetchall()
    connection.close()
    by_codename = {str(c).casefold(): (str(s), str(slug or "")) for s, c, slug in rows}
    item_art: dict[str, str] = {}
    missing: list[str] = []

    for entry in characters:
        if entry.get("rarity") is None:
            continue
        item_id = str(entry["id"])
        codename = str(entry.get("codename") or item_id.removeprefix("char:"))
        row = by_codename.get(codename.casefold())
        record = source_manifest.get("characters", {}).get(row[1]) if row and row[1] else None
        if not record:
            missing.append(item_id)
            continue
        portraits = record.get("portraits") or []
        selected = next((p for p in portraits if p.get("role_key") == "role2"), None)
        selected_path = (selected or {}).get("path") or record.get("portrait")
        if selected_path and (SOURCE_ASSETS / selected_path).exists():
            item_art[item_id] = _copy(selected_path)
        else:
            missing.append(item_id)

    for entry in weapons:
        item_id = str(entry["id"])
        payload = item_id.removeprefix("weapon:")
        owner_codename, separator, weapon_tail = payload.partition("-weapon")
        weapon_key = f"weapon{weapon_tail}" if separator else ""
        if not separator:
            missing.append(item_id)
            continue
        row = by_codename.get(owner_codename.casefold())
        record = source_manifest.get("weapons", {}).get(f"{row[0]}:{weapon_key}") if row else None
        image_path = record.get("image") if record else None
        if image_path and (SOURCE_ASSETS / image_path).exists():
            item_art[item_id] = _copy(image_path)
        else:
            missing.append(item_id)

    payload = {
        "_comment": "由 tools/import_phantom_assets.py 生成；角色/武器缺图时不会进入卡池",
        "items": dict(sorted(item_art.items())),
        "missing": sorted(missing),
    }
    TARGET_INDEX.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已映射 {len(item_art)} 项素材；缺失 {len(missing)} 项")


if __name__ == "__main__":
    main()
