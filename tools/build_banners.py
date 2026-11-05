"""生成 P5X 卡池配置（data/banners.json）。

卡池结构依据官方公告与日服攻略站（神ゲー攻略 / Game8）公布的数据：

* 角色契约：5★ 0.8%、4★ 6.2%、2-3★ 人格面具 93%；80 抽必出 5★，10 抽必出 4★。
* 武器契约：5★ 0.8%（其中 UP 0.4%）、4★ 8.0%、3★ 91.2%；70 抽必出 5★，
  歪一次后下次 5★ 必为 UP，所以最坏 140 抽。
* 单抽价格：角色 150、武器 100（日服「自在結晶」，国服对应晶珀）。
* 常驻角色池累计 300 抽可选一个 5★，因此带 ``selector_at``。

跑法：
    python tools/build_banners.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ITEMS = ROOT / "data" / "items"

# 3★ 武器占位：官方没有公开 3★ 武器表，这里只保证武器池的 91.2% 有东西可出。
WEAPON_3STAR = [
    ("制式短剑", "物理"), ("制式长枪", "枪击"), ("制式手斧", "物理"),
    ("制式双刃", "物理"), ("制式拳套", "物理"), ("制式手枪", "枪击"),
    ("制式长弓", "枪击"), ("制式法杖", "念动"), ("制式太刀", "物理"),
    ("制式铁球", "物理"), ("制式锁链", "物理"), ("制式音叉", "祝福"),
]

CHAR_RATES = {5: 0.008, 4: 0.062, 3: 0.03, 2: 0.90}
WEAPON_RATES = {5: 0.008, 4: 0.08, 3: 0.912, 2: 0.0}


def load(name: str) -> list[dict]:
    return json.loads((ITEMS / name).read_text(encoding="utf-8"))


def main() -> None:
    characters = load("characters.json")
    weapons = load("weapons.json")
    personas = json.loads((ITEMS / "personas.json").read_text(encoding="utf-8"))["items"]

    # ---- 3★ 武器占位，只在缺失时写一次 ----
    three_star_path = ITEMS / "weapons_3star.json"
    if not three_star_path.exists():
        three_star = [
            {
                "id": f"weapon3:{i}",
                "name": name,
                "rarity": 3,
                "kind": "weapon",
                "element": element,
                "status": "placeholder",
            }
            for i, (name, element) in enumerate(WEAPON_3STAR)
        ]
        three_star_path.write_text(
            json.dumps(three_star, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    five_chars = [c for c in characters if c["rarity"] == 5]
    four_chars = [c for c in characters if c["rarity"] == 4]
    five_weapons = [w for w in weapons if w["rarity"] == 5]
    four_weapons = [w for w in weapons if w["rarity"] == 4]

    standard5 = [c for c in five_chars if not c["limited"]]
    limited5 = [c for c in five_chars if c["limited"]]
    if not standard5:
        raise SystemExit("没有常驻 5★ 角色，无法构建卡池")

    # 限定池示例取最新上线的限定角色（release_order 最大）
    featured = max(limited5, key=lambda c: c.get("release_order") or 0)
    base_name = featured["name"].split("·")[0]
    featured_weapon = next(
        (w for w in five_weapons if w["owner"] == featured["name"]), None
    ) or next(
        (w for w in five_weapons if w["owner"].split("·")[0] == base_name), None
    ) or five_weapons[0]

    up4 = [c["id"] for c in four_chars[:3]]
    rng = random.Random(7)
    up_weapon4 = [w["id"] for w in rng.sample(four_weapons, min(3, len(four_weapons)))]

    banners = [
        {
            "id": "char_limited",
            "name": f"限定角色契约·{featured['name']}",
            "kind": "character",
            "pity_group": "char",
            "cost": 150,
            "rates": {str(k): v for k, v in CHAR_RATES.items()},
            "up_rate": {"5": 0.5, "4": 0.5},
            "hard_pity": {"5": 80, "4": 10},
            "soft_pity": [],
            "pool": {
                "5": [featured["id"]] + [c["id"] for c in standard5],
                "4": [c["id"] for c in four_chars],
                "3": [p["id"] for p in personas if p["rarity"] == 3],
                "2": [p["id"] for p in personas if p["rarity"] == 2],
            },
            "rate_up": {"5": [featured["id"]], "4": up4, "3": [], "2": []},
            "note": "限时角色池：80 抽必出 5★，歪了下次必为 UP；保底跨限定池继承。",
            "enabled": True,
        },
        {
            "id": "char_standard",
            "name": "常驻角色契约",
            "kind": "character",
            "pity_group": "char_standard",
            "cost": 150,
            "rates": {str(k): v for k, v in CHAR_RATES.items()},
            "up_rate": {"5": 0.5, "4": 0.5},
            "hard_pity": {"5": 80, "4": 10},
            "soft_pity": [],
            "selector_at": 300,
            "pool": {
                "5": [c["id"] for c in standard5],
                "4": [c["id"] for c in four_chars],
                "3": [p["id"] for p in personas if p["rarity"] == 3],
                "2": [p["id"] for p in personas if p["rarity"] == 2],
            },
            "rate_up": {"5": [], "4": [], "3": [], "2": []},
            "note": "常驻池无 UP，累计 300 抽可选一个 5★。",
            "enabled": True,
        },
        {
            "id": "weapon_limited",
            "name": f"限定武器契约·{featured_weapon['name']}",
            "kind": "weapon",
            "pity_group": "weapon",
            "cost": 100,
            "rates": {str(k): v for k, v in WEAPON_RATES.items()},
            "up_rate": {"5": 0.5, "4": 0.5},
            "hard_pity": {"5": 70, "4": 10},
            "soft_pity": [],
            "pool": {
                "5": [featured_weapon["id"]] + [w["id"] for w in five_weapons if w["id"] != featured_weapon["id"]],
                "4": [w["id"] for w in four_weapons],
                "3": [f"weapon3:{i}" for i in range(len(WEAPON_3STAR))],
            },
            "rate_up": {"5": [featured_weapon["id"]], "4": up_weapon4, "3": []},
            "note": "武器池：70 抽必出 5★，UP 占 5★ 的一半，最坏 140 抽。",
            "enabled": True,
        },
        {
            "id": "weapon_standard",
            "name": "常驻武器契约",
            "kind": "weapon",
            "pity_group": "weapon_standard",
            "cost": 100,
            "rates": {str(k): v for k, v in WEAPON_RATES.items()},
            "up_rate": {"5": 0.5, "4": 0.5},
            "hard_pity": {"5": 70, "4": 10},
            "soft_pity": [],
            "pool": {
                "5": [w["id"] for w in five_weapons],
                "4": [w["id"] for w in four_weapons],
                "3": [f"weapon3:{i}" for i in range(len(WEAPON_3STAR))],
            },
            "rate_up": {"5": [], "4": [], "3": []},
            "note": "常驻武器池无 UP。",
            "enabled": True,
        },
    ]

    (ROOT / "data" / "banners.json").write_text(
        json.dumps(banners, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for banner in banners:
        print(f"{banner['id']:<16} {banner['name']}")


if __name__ == "__main__":
    main()
