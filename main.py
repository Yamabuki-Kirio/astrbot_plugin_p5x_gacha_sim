"""P5X（女神异闻录：夜幕魅影）模拟抽卡插件。

指令入口 ``/p5x``，子指令：帮助 / 卡池 / 队伍 / 签到 / 次数 / 刷新 / 选择 / 单抽 / 十连 / 保底 / 记录 / 自选 / 榜单。

设计要点
--------
* 机制层（``src/core``）不依赖 AstrBot，可以单独跑测试和蒙特卡洛（见 ``tools/``）；
* 全限定池与对应目标池按 ``pity_group`` 共享保底；角色和武器独立计数；
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
from .src.render.roster import render_roster
from .src.render.team import render_team, team_pages
from .src.services.gacha_service import GachaService
from .src.services.identity import avatar_bytes, display_name

PLUGIN_NAME = "astrbot_plugin_p5x_gacha_sim"

TUTORIAL_IMAGE = Path(__file__).resolve().parent / "assets" / "tutorial" / "caroline-gacha-guide.jpg"

HELP_TEXT = """P5X 模拟抽卡
/卡池帮助           卡萝莉娜的图片版新手教程
/卡池               一张完整限定角色目录与当前 UP
/队伍 [页码]        已拥有的四五星角色/武器与意识/进化
/签到               每日签到领取额外抽数
/抽卡次数           查看今日剩余抽数和签到状态
/刷新               白名单管理员为所有已登记用户增加10抽
/十连 [角色名|别名]  默认抽全限定角色池，指定名字抽对应 UP 池
/十连 武器池         全限定武器池
/十连 武器 <角色名|武器名>  指定武器 UP 池
/p5x 选择 <角色名|全角色池|武器池>  个人默认池
/p5x 单抽 [角色名|卡池]  单抽
/p5x 保底 [角色名|卡池]  查看共享保底
/p5x 记录 [页码]      抽卡记录
/p5x 自选 <角色名>    常驻池满300抽自选
/p5x 榜单            5★数量排行
角色限定池共享抽数与保底，武器限定池另行共享。
默认每天10抽，签到额外10抽；北京时间零点重置。"""


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
                daily_pulls=self.config.get("daily_draw_limit", 10),
                signin_bonus=self.config.get("daily_signin_bonus", 10),
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
                found = self.registry.banner(default)
                if found.enabled:
                    return found
            except KeyError:
                pass
        return self.registry.configured_default(self.config)

    @staticmethod
    def _target(event, fallback=""):
        """保留英文名中的空格；兼容带机器人前缀的消息。"""
        import re
        try:
            message = event.get_message_str()
        except (AttributeError, TypeError):
            message = getattr(event, "message_str", "")
        match = re.search(r"(?:^|\s)/?(?:p5x(?:抽卡|_gacha)?\s+)?(?:十连|单抽|选择|保底)\s+(.+)$", message or "", re.I)
        return match.group(1).strip() if match else (fallback or "").strip()

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

    def _footer(self, banner: Banner, state, total: int, remaining: int | None = None) -> str:
        hard5 = banner.hard_pity.get(5, 80)
        parts = [f"当前 {state.pity5}/{hard5}", f"累计{total}抽"]
        if banner.has_off_rate(5):
            parts.append("大保底已触发" if state.guaranteed5 else "小保底")
        parts.append(f"共享累计{state.pulls}抽")
        parts.append(banner.name)
        if remaining is not None:
            parts.append(f"今日剩余{remaining}抽")
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

    @p5x_group.command("卡池帮助", priority=1)
    async def cmd_pool_help(self, event: AstrMessageEvent):
        """发送随插件安装的静态教程，无需数据库或渲染器。"""
        try:
            data = await asyncio.to_thread(TUTORIAL_IMAGE.read_bytes)
            image = Image.fromBytes(data)
        except Exception:  # noqa: BLE001 - 资源缺失仍提供用法
            logger.exception("P5X 教程图片读取失败，降级为文字")
            yield event.plain_result("教程图片暂时不可用，请检查插件资源是否完整。\n" + HELP_TEXT)
            return
        yield event.chain_result([image])

    @filter.command("卡池帮助", priority=1)
    async def direct_pool_help(self, event: AstrMessageEvent):
        async for result in self.cmd_pool_help(event):
            yield result

    @p5x_group.command("卡池", priority=1)
    async def cmd_banners(self, event: AstrMessageEvent):
        error = self._ready(event)
        if error:
            yield error
            return
        try:
            default = self._resolve(event, "")
        except ValueError as exc:
            yield event.plain_result(f"默认卡池配置错误：{exc}")
            return
        characters = self.registry.limited_characters()
        up_ids = {i.id for i in default.rate_up.get(5, ())}
        if default.kind == "weapon":
            up_ids = {"char:" + i.partition(":")[2].split("-weapon", 1)[0] for i in up_ids}
        status = "当前：" + default.name
        if not default.rate_up.get(5):
            status += " · 五星等概率，无单独UP"
        chain = await self._render(lambda: render_roster(
            self.renderer, characters, 1, 1, status, up_ids))
        if chain:
            yield event.chain_result(chain)
        else:
            lines = [status, "限定角色目录："]
            lines.extend(f"{n}. {i.name} [{i.id[5:]}]" + (" UP" if i.id in up_ids else "")
                         for n,i in enumerate(characters,1))
            yield event.plain_result("\n".join(lines))

    @filter.command("卡池", priority=1)
    async def direct_banners(self, event: AstrMessageEvent):
        async for result in self.cmd_banners(event):
            yield result

    @p5x_group.command("队伍", priority=1)
    async def cmd_team(self, event: AstrMessageEvent, page: str = ""):
        error = self._ready(event)
        if error:
            yield error
            return
        owned = await asyncio.to_thread(self.service.team_of, self._platform(event), str(event.get_sender_id()))
        pages = team_pages(owned)
        if page and (not page.isdigit() or not 1 <= int(page) <= len(pages)):
            yield event.plain_result(f"队伍页码范围：1—{len(pages)}。")
            return
        selected = [int(page)-1] if page else range(len(pages))
        quota = await asyncio.to_thread(self.service.quota_of, self._platform(event), str(event.get_sender_id()))
        avatar = await asyncio.to_thread(avatar_bytes, event) if self.config.get("enable_rendering", True) else None
        characters = sum(e.item.id.startswith("char:") for e in owned)
        for index in selected:
            rows = pages[index]
            chain = await self._render(lambda rows=rows,index=index: render_team(
                self.renderer, rows, self.registry, display_name(event), index+1, len(pages),
                characters, len(owned)-characters, quota.remaining, avatar))
            if chain:
                yield event.chain_result(chain)
            else:
                lines = [f"{display_name(event)}的队伍（{index+1}/{len(pages)}） · 今日可抽 {quota.remaining} 抽"]
                if not owned:
                    lines.append("尚未获得四、五星角色或武器，发送 /十连 开始收集。")
                for row in rows:
                    for entry in row:
                        lines.append(f"{entry.item.rarity}★ {entry.item.name} · {entry.label} {entry.level}/6" + (" · 满阶" if entry.maxed else ""))
                yield event.plain_result("\n".join(lines))

    @filter.command("队伍", priority=1)
    async def direct_team(self, event: AstrMessageEvent, page: str = ""):
        async for result in self.cmd_team(event, page):
            yield result

    @p5x_group.command("签到", priority=1)
    async def cmd_signin(self, event: AstrMessageEvent):
        error = self._ready(event)
        if error:
            yield error
            return
        quota, claimed = await asyncio.to_thread(
            self.service.signin, self._platform(event), str(event.get_sender_id()))
        if claimed:
            message = f"签到成功，获得 {self.service.signin_bonus} 抽！"
        else:
            message = "今天已经签到过了，奖励不可重复领取。"
        yield event.plain_result(f"{message}\n今日剩余 {quota.remaining} 抽 · 已抽 {quota.used} 抽\n北京时间零点刷新，剩余额度不结转。")

    @filter.command("签到", alias={"p5x签到"}, priority=1)
    async def direct_signin(self, event: AstrMessageEvent):
        async for result in self.cmd_signin(event):
            yield result

    @p5x_group.command("次数", priority=1)
    async def cmd_quota(self, event: AstrMessageEvent):
        error = self._ready(event)
        if error:
            yield error
            return
        quota = await asyncio.to_thread(self.service.quota_of, self._platform(event), str(event.get_sender_id()))
        signed = "已签到" if quota.signed else f"未签到，/签到 可再领 {self.service.signin_bonus} 抽"
        yield event.plain_result(f"今日剩余 {quota.remaining} 抽 · 已抽 {quota.used} 抽\n每日基础 {quota.base} 抽 · 额外获得 {quota.bonus} 抽\n{signed}\n北京时间零点刷新，剩余额度不结转。")

    @filter.command("抽卡次数", priority=1)
    async def direct_quota(self, event: AstrMessageEvent):
        async for result in self.cmd_quota(event):
            yield result

    def _quota_admin(self, event):
        # 附带关键词插件使用黑名单放行，此处按要求改为仅白名单授权。
        users = self.config.get("admin_whitelist", [])
        if not isinstance(users, (list, tuple, set)):
            return False
        user_id = str(event.get_sender_id()).strip()
        return bool(user_id) and user_id in {str(uid).strip() for uid in users}

    @p5x_group.command("刷新", priority=1)
    async def cmd_refresh(self, event: AstrMessageEvent):
        if not self._quota_admin(event):
            yield event.plain_result("权限不足：只有抽卡管理员白名单中的用户可以执行 /刷新。")
            return
        error = self._ready(event)
        if error:
            yield error
            return
        count = await asyncio.to_thread(self.service.refresh_all)
        yield event.plain_result(f"刷新完成：已为 {count} 位已登记用户各增加 10 抽。\n剩余 0→10、10→20、20→30；签到状态保持不变。")

    @filter.command("刷新", priority=1)
    async def direct_refresh(self, event: AstrMessageEvent):
        async for result in self.cmd_refresh(event):
            yield result

    @filter.command("十连", priority=1)
    async def direct_ten(self, event: AstrMessageEvent, target: str = ""):
        async for result in self.cmd_ten(event, target):
            yield result

    @p5x_group.command("选择", priority=1)
    async def cmd_select(self, event: AstrMessageEvent, target: str = ""):
        error = self._ready(event)
        if error:
            yield error
            return
        target = self._target(event, target)
        if not target:
            yield event.plain_result("用法：/p5x 选择 <编号|卡池名|卡池 id>")
            return
        banner = None
        if target.isdigit():
            characters = self.registry.limited_characters()
            index = int(target) - 1
            banner = self.registry.resolve_character(characters[index].name) if 0 <= index < len(characters) else None
        banner = banner or self.registry.resolve(target)
        if banner is None:
            yield event.plain_result(self.registry.selection_error(target))
            return
        self.store.set_default_banner(self._platform(event), str(event.get_sender_id()), banner.id)
        yield event.plain_result(f"已把默认卡池设为「{banner.name}」。")

    @p5x_group.command("单抽", priority=1)
    async def cmd_single(self, event: AstrMessageEvent, target: str = ""):
        error = self._ready(event)
        if error:
            yield error
            return
        target = self._target(event, target)
        try:
            banner = self._resolve(event, target)
        except ValueError as exc:
            yield event.plain_result(f"默认卡池配置错误：{exc}")
            return
        if banner is None:
            yield event.plain_result(self.registry.selection_error(target))
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

        total = self.store.total_pulls(self._platform(event), str(event.get_sender_id()))
        avatar = await asyncio.to_thread(avatar_bytes, event) if self.config.get("enable_rendering", True) else None
        text = self.service.format_single(outcome) + f"\n累计{total}抽 · 今日剩余 {outcome.remaining} 抽"
        chain = await self._render(
            lambda: self.renderer.render_single(
                outcome.results[0],
                banner,
                user_name=display_name(event),
                avatar=avatar,
                footer=self._footer(banner, outcome.state, total, outcome.remaining),
            )
        )
        if chain:
            yield event.chain_result(chain)
            if outcome.overflow_bonus:
                yield event.plain_result(f"满阶重复返还 {outcome.overflow_bonus} 抽，已加入今日额度；当前剩余 {outcome.remaining} 抽。")
        else:
            yield event.plain_result(text)

    @p5x_group.command("十连", priority=1)
    async def cmd_ten(self, event: AstrMessageEvent, target: str = ""):
        error = self._ready(event)
        if error:
            yield error
            return
        target = self._target(event, target)
        try:
            banner = self._resolve(event, target)
        except ValueError as exc:
            yield event.plain_result(f"默认卡池配置错误：{exc}")
            return
        if banner is None:
            yield event.plain_result(self.registry.selection_error(target))
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

        total = self.store.total_pulls(self._platform(event), str(event.get_sender_id()))
        avatar = await asyncio.to_thread(avatar_bytes, event) if self.config.get("enable_rendering", True) else None
        text = self.service.format_ten(outcome) + f"\n累计{total}抽 · 今日剩余 {outcome.remaining} 抽"
        chain = await self._render(
            lambda: self.renderer.render_ten(
                outcome.results,
                banner,
                user_name=display_name(event),
                avatar=avatar,
                footer=self._footer(banner, outcome.state, total, outcome.remaining),
            )
        )
        if chain:
            yield event.chain_result(chain)
            if outcome.overflow_bonus:
                yield event.plain_result(f"满阶重复返还 {outcome.overflow_bonus} 抽，已加入今日额度；当前剩余 {outcome.remaining} 抽。")
        else:
            yield event.plain_result(text)

    @p5x_group.command("保底", priority=1)
    async def cmd_pity(self, event: AstrMessageEvent, target: str = ""):
        error = self._ready(event)
        if error:
            yield error
            return
        target = self._target(event, target)
        try:
            banner = self._resolve(event, target)
        except ValueError as exc:
            yield event.plain_result(f"默认卡池配置错误：{exc}")
            return
        if banner is None:
            yield event.plain_result("没有找到卡池。")
            return
        state = self.service.state_of(self._platform(event), str(event.get_sender_id()), banner)
        quota = await asyncio.to_thread(self.service.quota_of, self._platform(event), str(event.get_sender_id()))
        yield event.plain_result(self.service.format_pity(banner, state) + f"\n今日剩余 {quota.remaining} 抽（北京时间零点刷新）")

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
