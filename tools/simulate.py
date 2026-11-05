"""蒙特卡洛验证：用模拟抽卡反推概率，确认机制实现与官方公布的数字对得上。

    python tools/simulate.py            # 每个卡池 20 万次
    python tools/simulate.py --runs 1000000

关注三个数字：
* 5★ 基础出货率（官方 0.8% 角色 / 0.8% 武器）
* 5★ 平均抽数 → 倒数就是「综合概率」
* 拿到当期 UP 的平均抽数（含小保底）
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.mechanics import GachaMechanics  # noqa: E402
from src.core.models import PityState  # noqa: E402
from src.core.registry import Registry  # noqa: E402


def simulate_first_five(banner, runs: int, seed: int = 1):
    """每次从 0 保底开始，抽到第一个 5★ 为止，返回抽数列表与 UP 命中数。"""
    rng = random.Random(seed)
    mech = GachaMechanics(rng)
    pulls: list[int] = []
    ups = 0
    rare4 = 0
    total = 0
    for _ in range(runs):
        state = PityState()
        for n in range(1, 400):
            result, state = mech.pull(banner, state)
            total += 1
            if result.rarity == 4:
                rare4 += 1
            if result.rarity == 5:
                pulls.append(n)
                if result.is_up:
                    ups += 1
                break
    return pulls, ups, rare4, total


def simulate_up(banner, runs: int, seed: int = 2):
    """从 0 保底开始抽到「当期 UP 5★」为止，返回抽数列表。"""
    rng = random.Random(seed)
    mech = GachaMechanics(rng)
    pulls: list[int] = []
    for _ in range(runs):
        state = PityState()
        for n in range(1, 400):
            result, state = mech.pull(banner, state)
            if result.rarity == 5 and result.is_up:
                pulls.append(n)
                break
    return pulls


def report(banner, runs: int) -> None:
    pulls, ups, rare4, total = simulate_first_five(banner, runs)
    mean5 = statistics.fmean(pulls)
    up_pulls = simulate_up(banner, runs, seed=3)
    mean_up = statistics.fmean(up_pulls)

    print(f"\n=== {banner.name} ({banner.id}) ===")
    print(f"  抽数           : {total:,}")
    print(f"  5★ 出货率      : {len(pulls) / total:.4%}  (基础值 {banner.rates.get(5, 0):.2%}, 保底前)")
    print(f"  4★ 出货率      : {rare4 / total:.4%}  (基础值 {banner.rates.get(4, 0):.2%})")
    print(f"  5★ 平均抽数    : {mean5:.2f}  → 综合概率 {1 / mean5:.3%}")
    print(f"  5★ 中位数      : {statistics.median(pulls):.0f}")
    print(f"  5★ 最长/最短   : {max(pulls)} / {min(pulls)}（硬保底 {banner.hard_pity.get(5)}）")
    if banner.has_off_rate(5):
        print(f"  UP 占比(小保底之后): {ups / len(pulls):.2%}")
        print(f"  UP 平均抽数    : {mean_up:.2f}  → 最坏 {banner.max_pity_hint()}")
    else:
        print("  无 UP，常驻池每个 5★ 等概率")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=200_000)
    parser.add_argument("--banner", default="", help="只跑指定卡池 id")
    args = parser.parse_args()

    registry = Registry.load()
    banners = registry.enabled_banners()
    if args.banner:
        banners = [b for b in banners if b.id == args.banner]
        if not banners:
            raise SystemExit(f"没有找到卡池 {args.banner}")
    for banner in banners:
        report(banner, args.runs)


if __name__ == "__main__":
    main()
