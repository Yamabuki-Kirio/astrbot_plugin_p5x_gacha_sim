"""P5X（女神异闻录：夜幕魅影）模拟抽卡插件。

指令入口 ``/p5x``，子指令：帮助 / 卡池 / 选择 / 单抽 / 十连 / 保底 / 记录 / 自选 / 榜单。

设计要点
--------
* 机制层（``src/core``）不依赖 AstrBot，可以单独跑测试和蒙特卡洛（见 ``tools/``）；
* 保底按 ``pity_group`` 继承：限定角色、常驻角色、限定武器、常驻武器各自计数；
* 图片渲染失败不影响抽卡结果，文字结果一定会发出去。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.message.components import Image

from .src.core.models import Banner
from .src.core.registry import Registry
from .src.core.store import Store
from .src.render.renderer import Renderer, encode
from .src.services.gacha_service import GachaService

PLUGIN_NAME = "astrbot_plugin_p5x_gacha_sim"

HELP_TEXT = """P5X 模拟抽卡
/p5x 卡池            查看所有卡池
/p5x 选择 <编号|名称>  设置个人默认卡池
/p5x 单抽 [卡池]      单抽
/p5x 十连 [卡池]      十连
/p5x 保底 [卡池]      查看保底进度
/p5x 记录 [页码]      查看抽卡记录
/p5x 自选 <角色名>    常驻池满 300 抽后自选 5★
/p5x 榜单            本群 5★ 数量排行"""


class P5XGachaPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.registry: Registry | None = None
        self.store: Store | None = None
        self.service: GachaService | None = None
        self.renderer: Renderer | None = None
        self._init_error: str = ""

    # ------------------------------------------------------------------
    async def initialize(self):
        await asyncio.to_thread(self._setup)
        if self._init_error:
            logger.error(f"P5X 抽卡插件初始化失败：{self._init_error}")
        else:
            logger.info(f"P5X 抽卡插件已就绪，共 {len(self.registry.enabled_banners())} 个卡池")

    def _setup(self) -> None:
        try:
            self.registry = Registry.load()
            data_dir = Path(StarTools.get_data_dir(PLUGIN_NAME))
            self.store = Store(data_dir / "p5x_gacha.sqlite3")
            self.service = GachaService(
                self.registry,
                self.store,
                record_history=bool(self.config.get("enable_history_recording", True)),
            )
            self.renderer = Renderer(
                assets_dir=Path(__file__).resolve().parent / "assets",
                font_path=self.config.get("font_path") or None,
            )
        except Exception as exc:  # noqa: BLE001 - 初始化失败要继续在聊天里报错
            self._init_error = str(exc)

    async def terminate(self):
        if self.store is not None:
            self.store.close()
            self.store = None

    # ------------------------------------------------------------------
    # 通用工具
    # ------------------------------------------------------------------
    @staticmethod
    def _platform(event: AstrMessageEvent) -> str:
        try:
            return str(event.get_platform_id())
        except Exception:  # noqa: BLE001
            return "unknown"

    @staticmethod
    def _nickname(event: AstrMessageEvent) -> str:
        try:
            return str(event.get_sender_name())
        except Exception:  # noqa: BLE001
            return "玩家"

    def _resolve(self, event: AstrMessageEvent, text: str) -> Banner | None:
        if text:
            return self.registry.resolve(text)
        default = self.store.get_default_banner(self._platform(event), str(event.get_sender_id()))
        if default:
            try:
                return self.registry.banner(default)
            except KeyError:
                pass
        configured = (self.config.get("default_banner") or "").strip()
        if configured:
            found = self.registry.resolve(configured)
            if found:
                return found
        enabled = self.registry.enabled_banners()
        return enabled[0] if enabled else None

    def _ready(self, event: AstrMessageEvent):
        if self._init_error:
            return event.plain_result(f"插件未就绪：{self._init_error}")
        if self.service is None or self.registry is None:
            return event.plain_result("插件尚未初始化完成，请稍后再试。")
        return None

    async def _render(self, image_factory) -> list | None:
        if not self.config.get("enable_rendering", True) or self.renderer is None:
            return None
        try:
            image = await asyncio.to_thread(image_factory)
            data = await asyncio.to_thread(encode, image)
            return [Image.fromBytes(data)]
        except Exception:  # noqa: BLE001
            logger.exception("P5X 抽卡图片渲染失败，降级为文字")
            return None

    def _footer(self, banner: Banner, state) -> str:
        hard5 = banner.hard_pity.get(5, 80)
        hard4 = banner.hard_pity.get(4, 10)
        parts = [f"5★ {state.pity5}/{hard5}", f"4★ {state.pity4}/{hard4}"]
        if banner.has_off_rate(5):
            parts.append("大保底已触发" if state.guaranteed5 else "小保底")
        parts.append(f"本池累计 {state.total_of(banner.id)} 抽")
        return "    ".join(parts)

    # ------------------------------------------------------------------
    # 指令
    # ------------------------------------------------------------------
    @filter.command_group("p5x", alias={"p5x抽卡", "p5x_gacha"}, priority=1)
    def p5x_group():
        """P5X 模拟抽卡入口。"""

    @p5x_group.command("帮助", priority=1)
    async def cmd_help(self, event: AstrMessageEvent):
        yield event.plain_result(HELP_TEXT)

    @p5x_group.command("卡池", priority=1)
    async def cmd_banners(self, event: AstrMessageEvent):
        error = self._ready(event)
        if error:
            yield error
            return
        banners = self.registry.enabled_banners()
        if not banners:
            yield event.plain_result("没有启用任何卡池，请检查 data/banners.json。")
            return
        default = self._resolve(event, "")
        lines = ["可用卡池："]
        for index, banner in enumerate(banners, 1):
            mark = " ←当前" if default and banner.id == default.id else ""
            lines.append(f"{index}. {banner.name}（{banner.id}）{mark}")
            lines.append(
                f"    {banner.cost} 晶珀/抽 · 5★ 保底 {banner.hard_pity.get(5)} · "
                f"最坏 {banner.max_pity_hint()} 抽得 UP"
            )
        lines.append("用 /p5x 选择 <编号> 固定个人默认卡池。")
        yield event.plain_result("\n".join(lines))

    @p5x_group.command("选择", priority=1)
    async def cmd_select(self, event: AstrMessageEvent, target: str = ""):
        error = self._ready(event)
        if error:
            yield error
            return
        if not target:
            yield event.plain_result("用法：/p5x 选择 <编号|卡池名|卡池 id>")
            return
        banner = None
        if target.isdigit():
            banners = self.registry.enabled_banners()
            index = int(target) - 1
            banner = banners[index] if 0 <= index < len(banners) else None
        banner = banner or self.registry.resolve(target)
        if banner is None:
            yield event.plain_result(f"没有找到卡池「{target}」。可以先发送 /p5x 卡池 查看编号。")
            return
        self.store.set_default_banner(self._platform(event), str(event.get_sender_id()), banner.id)
        yield event.plain_result(f"已把默认卡池设为「{banner.name}」。")

    @p5x_group.command("单抽", priority=1)
    async def cmd_single(self, event: AstrMessageEvent, target: str = ""):
        error = self._ready(event)
        if error:
            yield error
            return
        banner = self._resolve(event, target)
        if banner is None:
            yield event.plain_result("没有找到卡池，请先 /p5x 卡池 查看。")
            return
        try:
            outcome = await asyncio.to_thread(
                self.service.draw, self._platform(event), str(event.get_sender_id()), banner, 1
            )
        except ValueError as exc:
            yield event.plain_result(f"抽卡失败：{exc}")
            return
        except Exception:  # noqa: BLE001
            logger.exception("P5X 单抽异常")
            yield event.plain_result("抽卡时发生错误，已记录日志。")
            return

        text = self.service.format_single(outcome)
        chain = await self._render(
            lambda: self.renderer.render_single(
                outcome.results[0],
                banner,
                user_name=self._nickname(event),
                footer=self._footer(banner, outcome.state),
            )
        )
        if chain:
            yield event.chain_result(chain)
        else:
            yield event.plain_result(text)

    @p5x_group.command("十连", priority=1)
    async def cmd_ten(self, event: AstrMessageEvent, target: str = ""):
        error = self._ready(event)
        if error:
            yield error
            return
        banner = self._resolve(event, target)
        if banner is None:
            yield event.plain_result("没有找到卡池，请先 /p5x 卡池 查看。")
            return
        try:
            outcome = await asyncio.to_thread(
                self.service.draw, self._platform(event), str(event.get_sender_id()), banner, 10
            )
        except ValueError as exc:
            yield event.plain_result(f"抽卡失败：{exc}")
            return
        except Exception:  # noqa: BLE001
            logger.exception("P5X 十连异常")
            yield event.plain_result("抽卡时发生错误，已记录日志。")
            return

        text = self.service.format_ten(outcome)
        chain = await self._render(
            lambda: self.renderer.render_ten(
                outcome.results,
                banner,
                user_name=self._nickname(event),
                footer=self._footer(banner, outcome.state),
            )
        )
        if chain:
            yield event.chain_result(chain)
        else:
            yield event.plain_result(text)

    @p5x_group.command("保底", priority=1)
    async def cmd_pity(self, event: AstrMessageEvent, target: str = ""):
        error = self._ready(event)
        if error:
            yield error
            return
        banner = self._resolve(event, target)
        if banner is None:
            yield event.plain_result("没有找到卡池。")
            return
        state = self.service.state_of(self._platform(event), str(event.get_sender_id()), banner)
        yield event.plain_result(self.service.format_pity(banner, state))

    @p5x_group.command("记录", priority=1)
    async def cmd_history(self, event: AstrMessageEvent, arg: str = ""):
        error = self._ready(event)
        if error:
            yield error
            return
        arg = (arg or "").strip()
        page = 1
        banner = None
        if arg.isdigit():
            page = int(arg)
        elif arg:
            banner = self.registry.resolve(arg)
            if banner is None:
                yield event.plain_result(f"没有找到卡池「{arg}」。")
                return
        text = await asyncio.to_thread(
            self.service.format_history, self._platform(event), str(event.get_sender_id()), banner, page
        )
        yield event.plain_result(text)

    @p5x_group.command("自选", priority=1)
    async def cmd_selector(self, event: AstrMessageEvent, name: str = ""):
        error = self._ready(event)
        if error:
            yield error
            return
        banner = self._resolve(event, "常驻角色")
        if banner is None or not banner.selector_at:
            yield event.plain_result("当前没有带自选机制的卡池。")
            return
        if not name:
            names = "、".join(item.name for item in banner.candidates(5))
            yield event.plain_result(f"用法：/p5x 自选 <角色名>\n可选：{names}")
            return
        match = next((item for item in banner.candidates(5) if item.name == name), None) or next(
            (item for item in banner.candidates(5) if name in item.name), None
        )
        if match is None:
            yield event.plain_result(f"卡池里没有「{name}」这个 5★。")
            return
        try:
            got = await asyncio.to_thread(
                self.service.select_character,
                self._platform(event),
                str(event.get_sender_id()),
                banner,
                match.id,
            )
        except ValueError as exc:
            yield event.plain_result(f"自选失败：{exc}")
            return
        yield event.plain_result(f"自选成功，获得 ★★★★★ {got}！")

    @p5x_group.command("榜单", priority=1)
    async def cmd_rank(self, event: AstrMessageEvent):
        error = self._ready(event)
        if error:
            yield error
            return
        rows = await asyncio.to_thread(self.store.leaderboard, self._platform(event), 10)
        if not rows:
            yield event.plain_result("本平台还没有 5★ 记录。")
            return
        lines = ["5★ 数量排行："]
        for index, row in enumerate(rows, 1):
            lines.append(f"{index}. {row['user_id']} — {row['n']} 个")
        yield event.plain_result("\n".join(lines))
