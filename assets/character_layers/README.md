# 角色与专属人格面具图层

来源：用户提供的 Texture2D-20261106T125440Z-1-001/Texture2D。
保留 lihui-guaidao 系列原始文件名。未确认素材再分发授权，未经用户要求不推送。

优先按物品 ID 的角色代号匹配无后缀前景、-02 后景。
已显式处理 J&C → JandC、LEON → leo、joker-02-new、marian02。
现已加入 Sprite-20261106T134141Z-1-001/Sprite 的人工视觉比对。
显式映射见 mapping.json，导入工具为 tools/import_character_pairs.py。
当前运行时注册表 69 个角色条目中 63 项已映射，其中 62 项有前后景，
CHORD·Summer 仅接入已识别的独立前景，不把含角色的整张场景重复当作后景。
尚待识别：ANRI、CROW、PINKY、KOROMARU、BERRY·Summer、SKULL·Starlight。
这些是“未确认映射”，不等于已经证实源目录缺图；继续使用旧立绘兜底。
没有修改卡池或用其他角色替代。

角色底版不使用人格面具属性纹理；根据用户最新指定，五星采用紫色菱形底，
四星采用金色底（assets/gacha_native/character-bg-5.png、character-bg-4.png）。
character-frame-5.png、character-frame-4.png 是用户指定的左侧/底部品质框，
在立绘、特效、黑分隔之后合成，不再被角色遮挡；右侧黑分隔仍保留。
上述四张图直接取自本轮用户附件，带透明通道，不进行黑色抠图。
五星底按主体四角校正，排除图外零碎边缘；黑衬底和旧光效保留。
角色前景改为约 1.55 倍槽高的半身构图，后景约 1.15 倍槽高；背景仅填空。
J&C 前景按双人分界分层，以两张脸分别锚定槽高30%/61%，不整体挤入窄槽。
SEPIA、YUKI、MATOI 已加显式脸部锚点，其他角色仍使用通用定位，尚未逐张验收。
人格面具与角色规则独立：先前强制外接矩形完全入槽的版本被用户否决为过小，
用户再次验收认为过小，现以旧尺度90%、槽宽195%、槽高80%三者取小，
主体中心上移至槽高55%，允许宽幅肢体裁切；角色与J&C定位不变。
人格面具背景继续按 element 选择 xibie 素材；现有60项都有属性，不按槽位换色。
固定 J&C 双五星 + SEPIA 四星预览：output/acceptance/09_character_pairs.jpg。
新增别名组预览：10_alias_characters.jpg；编号/变体组：11_numbered_characters.jpg。
人工对照表位于 output/character_review/，待识别清单为 unresolved.json。
prepared/ 是 alpha 裁边、最长边不超过1600的等比渲染副本；原图保留不覆盖。
