"""渲染演示：不启动 AstrBot 也能看到出图效果。

    python tools/render_demo.py            # 默认出十连 + 单抽
    python tools/render_demo.py --multi5   # 额外出一张多 5★ / 多 4★ / 全武器 的压力测试图
"""

from __future__ import annotations

import random
import sys
from itertools import count
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.mechanics import GachaMechanics, PullResult  # noqa: E402
from src.core.models import PityState  # noqa: E402
from src.core.registry import Registry  # noqa: E402
from src.render.renderer import Renderer, encode  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "output"
_serial = count(1)


def _result(item, rarity: int | None = None, is_up: bool = False) -> PullResult:
    return PullResult(
        item=item,
        rarity=rarity or item.rarity,
        is_up=is_up,
        index=next(_serial),
        pity5_after=1,
        pity4_after=1,
    )


def main(argv: list[str]) -> None:
    OUT.mkdir(exist_ok=True)
    registry = Registry.load()
    renderer = Renderer()
    banner = registry.banner("char_limited")
    mech = GachaMechanics(random.Random(20261105))

    # 让十连里出现一个 5★：先垫到 79 抽
    state = PityState(pity5=77, pity4=6)
    results, state = mech.pull_many(banner, state, 10)
    image = renderer.render_ten(results, banner, user_name="玩家·Wonder")
    path = OUT / "demo_ten.jpg"
    path.write_bytes(encode(image, quality=92))
    print("十连 ->", path)

    single_state = PityState(pity5=79)
    single, single_state = mech.pull(banner, single_state)
    image = renderer.render_single(single, banner, user_name="玩家·Wonder", footer="第 80 抽 · 5★ 保底")
    path = OUT / "demo_single.jpg"
    path.write_bytes(encode(image, quality=92))
    print("单抽 ->", path)

    for result in results:
        print(f"  {result.stars} {result.item.name} ({result.item.element}){'  UP' if result.is_up else ''}")

    if "--multi5" not in argv:
        return

    five_star_pool = list(registry.banner("char_limited").pool.get(5, ()))
    four_star_pool = list(registry.banner("char_limited").pool.get(4, ()))
    weapon_banner = registry.banner("weapon_limited")
    weapon_pool = list(weapon_banner.pool.get(5, ()))

    def pick(pool: list, index: int):
        return pool[index % len(pool)]

    # 1) 多个 5★ + 多个 4★ 同时出现
    mixed = [
        _result(pick(five_star_pool, 0), 5, True),
        _result(pick(four_star_pool, 0), 4),
        _result(pick(five_star_pool, 1), 5),
        _result(pick(four_star_pool, 1), 4),
        _result(registry.items["persona:pixie"], 2),
        _result(pick(five_star_pool, 2), 5, True),
        _result(pick(four_star_pool, 2), 4),
        _result(pick(five_star_pool, 3), 5),
        _result(registry.items["persona:slime"], 3),
        _result(pick(four_star_pool, 3), 4),
    ]
    path = OUT / "demo_multi_star.jpg"
    path.write_bytes(encode(renderer.render_ten(mixed, banner), quality=92))
    print("多 5★/4★ ->", path, f"(5★ 候选 {len(five_star_pool)} 个)")

    # 2) 武器十连
    weapon_four = list(weapon_banner.pool.get(4, ()))
    weapon_results = [_result(item) for item in (weapon_pool[:5] + weapon_four[:5])]
    path = OUT / "demo_weapon_ten.jpg"
    path.write_bytes(encode(renderer.render_ten(weapon_results, weapon_banner), quality=92))
    print("武器十连 ->", path)

    # 3) 全部低星（人格面具剪影）
    standard = registry.banner("char_standard")
    low = [_result(item) for item in (list(standard.pool.get(2, ()))[:7] + list(standard.pool.get(3, ()))[:3])]
    path = OUT / "demo_all_low.jpg"
    path.write_bytes(encode(renderer.render_ten(low, standard, show_new=False), quality=92))
    print("全低星 ->", path)


if __name__ == "__main__":
    main(sys.argv[1:])
