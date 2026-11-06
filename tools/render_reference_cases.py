"""渲染用户六张参考截图中的组合，仅保留背景与结果卡片。"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.core.registry import Registry
from src.core.mechanics import PullResult
from src.render.renderer import Renderer


CASES = [
    ("ANRI", "MIKU", ["幸魂", "花魄", "曼陀罗", "犬神", "莫克伊", "花魄", "欧若博司", "软泥怪"]),
    ("ANRI", "KOROMARU", ["木灵", "阴摩罗鬼", "莫克伊", "杰克灯笼", "杰克灯笼", "曼陀罗", "一本踏鞴", "安德拉斯"]),
    ("OKYANN", "PHOEBE", ["安德拉斯", "木灵", "阴摩罗鬼", "曼陀罗", "皮克希", "一本踏鞴", "狮爷", "软泥怪"]),
    ("PUPPET", "PANTHER·Starlight", ["幸魂", "克鲁波克鲁", "曼陀罗", "莫克伊", "杰克灯笼", "高等皮克希", "猫又", "奇魂"]),
    ("FLEURET", "CHORD·Summer", ["幸魂", "狮爷", "曼陀罗", "皮克希", "皮克希", "曼陀罗", "幸魂", "和魂"]),
    ("VINO", "KOTONE", ["幸魂", "花魄", "曼陀罗", "山灵", "杰克灯笼", "花魄", "飞天", "软泥怪"]),
]


def generate(destination):
    out = Path(destination)
    out.mkdir(parents=True, exist_ok=True)
    registry, renderer = Registry.load(), Renderer()
    for number, (four, five, low) in enumerate(CASES, 1):
        # 运行时低星从外向内填充，还原参考图左右两侧的结果顺序。
        low_order = [low[i] for i in (0, 7, 1, 6, 2, 5, 3, 4)]
        picks = [(registry.items["char:"+four], 4), (registry.items["char:"+five], 5)]
        picks += [(registry.items["persona:"+name], registry.items["persona:"+name].rarity) for name in low_order]
        results = [PullResult(item, rarity, False, n+1, 4, 0) for n, (item, rarity) in enumerate(picks)]
        renderer.render_ten(results).save(out / f"reference_{number:02}.jpg", quality=94)
        if number == 4:
            renderer.render_ten(results, user_name="风玲", footer="当前 4/80  累计 164 抽").save(
                out / "with_user_info.jpg", quality=94)
        print(number, four, five)


if __name__ == "__main__":
    generate(sys.argv[1] if len(sys.argv) > 1 else ROOT / "output" / "reference_cases")
