"""统计数据集与素材缺口，用来写「需要准备什么」。

    python tools/report_coverage.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.models import iter_items  # noqa: E402
from src.core.registry import Registry  # noqa: E402
from src.render.renderer import Renderer  # noqa: E402


def main() -> None:
    registry = Registry.load()
    renderer = Renderer()

    kinds = Counter((item.kind, item.rarity) for item in registry.items.values())
    print("物品库存：")
    for (kind, rarity), count in sorted(kinds.items(), key=lambda kv: (kv[0][0], -kv[0][1])):
        print(f"  {kind:<10} {rarity}★ {count:>4}")

    used: dict[str, object] = {}
    for banner in registry.enabled_banners():
        for item in iter_items(banner):
            used[item.id] = item

    missing = [item for item in used.values() if renderer.portrait(item) is None]
    print(f"\n卡池共引用 {len(used)} 个物品，缺立绘 {len(missing)} 个：")
    for item in sorted(missing, key=lambda i: (-i.rarity, i.name))[:20]:
        print(f"  {item.rarity}★ {item.name:<16} -> assets/portraits/{renderer.safe_id(item.id)}.png")
    if len(missing) > 20:
        print(f"  …… 另有 {len(missing) - 20} 个")

    placeholders = [item for item in registry.items.values() if item.meta.get("status") == "placeholder"]
    print(f"\n占位数据（必须替换）：{len(placeholders)} 条")

    five = Counter(item.rarity for item in used.values())
    print("\n卡池稀有度分布：", dict(sorted(five.items(), reverse=True)))


if __name__ == "__main__":
    main()
