# AstrBot P5X 模拟抽卡

「女神异闻录：夜幕魅影」（Persona 5: The Phantom X）风格的模拟抽卡插件，参照
[astrbot_plugin_ww_gacha_sim](https://github.com/HoshiKurea/astrbot_plugin_ww_gacha_sim) 的架构重写。

**准备清单 / 还缺什么 / 数据来源** 见 [`docs/准备清单.md`](docs/准备清单.md)。

## 特性

- 角色契约、武器契约、常驻池，概率与保底按公开资料建模：**5★ 0.8%、4★ 6.2%、80/70 抽硬保底、4★ 每 10 抽保底**。
- **50-50 小保底**：歪了下次 5★ 必为 UP，状态跨池继承（按 `pity_group` 分组）。
- 常驻角色池 **300 抽自选** 5★。
- 抽卡记录、保底进度、群内 5★ 榜单。
- Pillow 出图，内置角色、武器及完整 2★/3★人格面具立绘；缺图时仍会自动降级为剪影占位。
- 机制层不依赖 AstrBot，可单独跑蒙特卡洛与单测。

## 安装

```bash
cd AstrBot
git clone https://github.com/Yamabuki-Kirio/astrbot_plugin_p5x_gacha_sim.git data/plugins/astrbot_plugin_p5x_gacha_sim
```

依赖只有 `Pillow`（`requirements.txt`）。装好重载插件，看到日志 `P5X 抽卡插件已就绪` 即成功。

## 指令

统一前缀 `/p5x`：

| 指令 | 说明 |
| --- | --- |
| `/p5x 帮助` | 指令列表 |
| `/p5x 卡池` | 列出卡池与编号 |
| `/p5x 选择 <编号\|名称>` | 设置个人默认卡池 |
| `/p5x 单抽 [卡池]` | 单抽 |
| `/p5x 十连 [卡池]` | 十连 |
| `/p5x 保底 [卡池]` | 保底进度与小保底状态 |
| `/p5x 记录 [页码]` | 抽卡记录，每页 10 条 |
| `/p5x 自选 <角色名>` | 常驻池满 300 抽后自选 5★ |
| `/p5x 榜单` | 本平台 5★ 数量排行 |

示例：

```text
/p5x 卡池
/p5x 选择 1
/p5x 十连
/p5x 保底
```

## 配置

`data/config/astrbot_plugin_p5x_gacha_sim_config.json`（也可在插件配置页改）：

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `enable_rendering` | `true` | 是否发图，关掉只发文字 |
| `enable_history_recording` | `true` | 是否记历史（关掉仍存保底） |
| `default_banner` | `char_limited` | 用户没选池子时的默认卡池 id |
| `font_path` | `""` | 中文字体绝对路径，留空自动找 |

## 自定义卡池

改 `data/banners.json` 后重载插件。字段含义：

```jsonc
{
  "id": "char_limited",
  "name": "限定角色契约·XX",
  "kind": "character",          // character / weapon
  "pity_group": "char",         // 保底继承组；同组共享保底计数
  "cost": 150,                  // 每抽消耗
  "rates": {"5": 0.008, "4": 0.062, "3": 0.03, "2": 0.90},  // 必须和为 1
  "up_rate": {"5": 0.5, "4": 0.5},
  "hard_pity": {"5": 80, "4": 10},
  "soft_pity": [{"start": 66, "end": 70, "increment": 0.04}], // 可留空
  "selector_at": 300,           // 可选，常驻自选
  "pool": {"5": ["char:XXX"], "4": [], "3": [], "2": []},
  "rate_up": {"5": ["char:XXX"], "4": []}
}
```

启动时会做校验：概率之和必须为 1、UP 必须在候选池内、每个稀有度都要有候选。

## 素材

见 [`assets/README.md`](assets/README.md)。往 `assets/portraits/` 丢图即可，不用改代码。
缺哪些图：`python tools/report_coverage.py`。

2★/3★人格面具已内置 60 张透明立绘和对应中文名单；来源与重新导入方式见
[`assets/README.md`](assets/README.md) 和 `tools/import_persona_assets.py`。

## 结果页渲染

十连/单抽结果页按游戏内截图还原（`tools/fixtures/gacha_reference.jpg`）：

- 10 条由右上斜向左下、高低错落的色带，相邻结果互相遮压；
- 十连采用1920×1080画布；角色使用半身前景与专属人格面具后景，J&C分别定位两张脸；
- 角色四/五星分别采用金色/紫色兜底纹理，原生品质边框在立绘之后合成；
- 人格面具按属性选择原生底纹，独立控制缩放；武器使用武器专用底纹；
- 成图仅保留 P5X 纹理背景与抽卡结果，不绘制顶部资源栏、相机、分享等外围 UI；
- 不显示奖励、角色标识、NEW、资源栏或分享等无关UI；低星无光效，四五星光效仍为程序近似。

改动渲染后可以这样并排对照：

```bash
python tools/render_demo.py --multi5      # 出 4 张：十连、单抽、多 5★/4★、武器十连、全低星
python tools/render_compare.py            # 参考截图 vs 当前出图 -> output/compare_reference.png
python tools/render_compare.py output/demo_multi_star.jpg   # 也可以指定别的图
```

## 开发

```bash
python -m pytest tests -q                 # 机制、素材和渲染测试
python tools/render_acceptance.py         # 固定输入验收图，输出到 output/acceptance/
python tools/build_dataset.py             # 从 p5x-data-crawler 重新生成角色/武器
python tools/build_banners.py             # 重新生成卡池配置
python tools/simulate.py --runs 20000     # 蒙特卡洛校验概率
python tools/render_demo.py               # 出不带 AstrBot 的结果图
```

## 已知限制

- 3★ 武器仍是 **占位数据**，上线前必须替换。
- 角色显式映射63项（62项前后景、1项独立前景），另6项身份映射仍待确认，暂用旧立绘；未逐角色完成定位验收。
- 使用用户提供的解包素材；原始角色大图留在本地，仓库仅包含最长边1600的渲染副本。素材权利归原权利人所有。
- 低星素材名单不等同于已经核实的实际契约卡池名单；四五星光效尚未完整还原。
- 3★:2★ 的拆分官方未公示，当前按 3% : 90% 推断。
- 未在真实 AstrBot 宿主内跑过消息管线（仅做了机制与持久化测试）。
- 还没有管理页面，改池子要改 JSON。

## 许可

模拟抽卡，与官方无关。游戏素材版权归 ATLUS / SEGA / 完美世界所有，请自行确认素材来源的可用性。
