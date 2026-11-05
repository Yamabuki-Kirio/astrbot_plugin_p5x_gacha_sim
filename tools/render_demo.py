"""渲染演示：不启动 AstrBot 也能看到出图效果。

    python tools/render_demo.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.mechanics import GachaMechanics  # noqa: E402
from src.core.models import PityState  # noqa: E402
from src.core.registry import Registry  # noqa: E402
from src.render.renderer import Renderer, encode  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "output"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    registry = Registry.load()
    renderer = Renderer()
    banner = registry.banner("char_limited")
    mech = GachaMechanics(random.Random(20261105))

    # 让十连里出现一个 5★：先垫到 79 抽
    state = PityState(pity5=77, pity4=6)
    results, state = mech.pull_many(banner, state, 10)
    footer = (
        f"5★ 保底 {state.pity5}/80    4★ 保底 {state.pity4}/10    "
        f"大保底：{'已触发' if state.guaranteed5 else '未触发'}    消耗 {banner.cost * 10} 晶珀"
    )
    image = renderer.render_ten(results, banner, user_name="玩家·Wonder", footer=footer)
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


if __name__ == "__main__":
    main()
