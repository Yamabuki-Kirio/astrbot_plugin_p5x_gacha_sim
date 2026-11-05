"""从 p5x-data-crawler 的产物生成插件使用的角色 / 武器数据集。

用法：
    python tools/build_dataset.py --source "C:/新建文件夹/p5x-data-crawler/output"

输入：
    output/raw/lufel-character_info.js  角色总表（含 limit 标记、中文名、稀有度）
    output/p5x_zh.sqlite3               zh_characters / zh_weapons 中文数据

输出：
    data/characters.json
    data/weapons.json

数据可信度见每条的 ``status`` 字段：
    verified  中英文来源一致、可直接用于卡池
    partial   只有部分字段，可参考
    placeholder 占位数据，必须替换
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3


def load_js_objects(path: str) -> dict:
    """把 lufel 的 ``Object.assign(window.X, {...})`` 脚本解析成 dict。

    直接用 ``json`` 无法解析（对象字面量带尾逗号且外层是 JS 语句），这里把
    ``window.characterData = window.characterData || {};`` 之类的前缀剥掉，
    只保留 ``Object.assign(..., { ... });`` 里的 JSON 片段。
    """
    text = open(path, encoding="utf-8").read()
    merged = {}
    for match in re.finditer(r"Object\.assign\([^,]+,\s*(\{)", text):
        start = match.start(1)
        depth = 0
        end = start
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        body = re.sub(r",(\s*[}\]])", r"\1", text[start:end])  # 去掉尾逗号
        merged.update(json.loads(body))
    return merged


def read_zh(path: str):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    chars = {row["source_key"]: dict(row) for row in conn.execute("select * from zh_characters")}
    weapons = [dict(row) for row in conn.execute("select * from zh_weapons order by id")]
    conn.close()
    return chars, weapons


ELEMENT_MAP = {
    "물리": "物理",
    "총격": "枪击",
    "화염": "火焰",
    "빙결": "冰结",
    "전격": "电击",
    "질풍": "疾风",
    "염동": "念动",
    "핵열": "核热",
    "축복": "祝福",
    "주원": "咒怨",
    "만능": "万能",
}

POSITION_MAP = {
    "지배": "支配",
    "굴복": "屈从",
    "구원": "救援",
    "반항": "反抗",
    "우월": "优越",
    "해명": "解明",
}


def build(source: str, out_dir: str) -> None:
    raw = load_js_objects(f"{source}/raw/lufel-character_info.js")
    zh_chars, zh_weapons = read_zh(f"{source}/p5x_zh.sqlite3")

    characters = []
    for key, data in raw.items():
        zh = zh_chars.get(key, {})
        rarity = data.get("rarity") or zh.get("rarity")
        name = zh.get("name_zh") or data.get("name_cn") or data.get("name")
        if not rarity:
            status = "partial"  # 未上线角色，没有稀有度
        elif zh.get("name_zh"):
            status = "verified"
        else:
            status = "partial"
        characters.append(
            {
                "id": f"char:{data.get('codename') or key}",
                "name": name,
                "name_cn": data.get("name_cn") or name,
                "name_jp": data.get("name_jp", ""),
                "name_en": data.get("name_en", ""),
                "rarity": int(rarity) if rarity else None,
                "element": zh.get("element_zh") or ELEMENT_MAP.get(data.get("element", ""), ""),
                "position": zh.get("position_zh") or POSITION_MAP.get(data.get("position", ""), ""),
                "limited": bool(data.get("limit")),
                "codename": data.get("codename", ""),
                "persona": data.get("persona_cn") or data.get("persona", ""),
                "release_order": data.get("release_order"),
                "source_key": key,
                "status": status,
            }
        )

    characters.sort(key=lambda c: (c["rarity"] or 0, c["release_order"] or 0))
    for c in characters:
        c.pop("source_key", None)

    weapons = []
    for row in zh_weapons:
        char_key = row["character_key"]
        char = raw.get(char_key, {})
        owner = zh_chars.get(char_key, {}).get("name_zh") or char.get("name_cn") or char_key
        if not row.get("name_zh"):
            continue
        weapons.append(
            {
                "id": f"weapon:{char.get('codename') or char_key}-{row['weapon_key']}",
                "name": row["name_zh"],
                "rarity": row.get("rarity"),
                "attack": row.get("attack"),
                "defense": row.get("defense"),
                "health": row.get("health"),
                "owner": owner,
                "status": "verified" if row.get("translation_status") == "source_original" else "partial",
            }
        )

    weapons.sort(key=lambda w: (-(w["rarity"] or 0), w["name"]))
    for w in weapons:
        w.pop("attack", None)
        w.pop("defense", None)
        w.pop("health", None)

    with open(f"{out_dir}/characters.json", "w", encoding="utf-8") as fh:
        json.dump(characters, fh, ensure_ascii=False, indent=2)
    with open(f"{out_dir}/weapons.json", "w", encoding="utf-8") as fh:
        json.dump(weapons, fh, ensure_ascii=False, indent=2)

    pool5 = [c for c in characters if c["rarity"] == 5]
    pool4 = [c for c in characters if c["rarity"] == 4]
    print(f"角色 {len(characters)} 个（5★ {len(pool5)} / 4★ {len(pool4)}）")
    print(f"  其中限定 5★ {sum(1 for c in pool5 if c['limited'])} 个")
    print(f"  待定（无稀有度）{sum(1 for c in characters if not c['rarity'])} 个")
    print(f"武器 {len(weapons)} 把（5★ {sum(1 for w in weapons if w['rarity'] == 5)} / 4★ {sum(1 for w in weapons if w['rarity'] == 4)}）")
    for c in pool5[:30]:
        print(f"  {c['name']:<14} {c['element']:<4} {'限定' if c['limited'] else '常驻'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=r"C:/新建文件夹/p5x-data-crawler/output")
    parser.add_argument("--out", default="data")
    args = parser.parse_args()
    build(args.source, args.out)
