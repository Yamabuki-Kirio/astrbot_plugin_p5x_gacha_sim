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
角色采用逐项脸部锚点，68项有可用前景，69项均已生成卡槽检查图。人物脸宽目标为槽宽95%，脸部中心在槽高42%；独立后景以脸部/主体焦点定位到槽高13%。图层等比缩放并按实际卡槽裁切，避免武器与长披风挤走人物。J&C双脸分别在40%和68%位置定位。
低星人格面具60项均有独立focus、target_y与最大尺寸配置；犬神、真神翻转朝向适配左下倾斜槽，其余宽翼与圆形素材单独控制。此处参数属于视觉校准，不改变抽卡概率或属性。
人格面具背景继续按 element 选择 xibie 素材；现有60项都有属性，不按槽位换色。
固定 J&C 双五星 + SEPIA 四星预览：output/acceptance/09_character_pairs.jpg。
新增别名组预览：10_alias_characters.jpg；编号/变体组：11_numbered_characters.jpg。
人工对照表位于 output/character_review/，待识别清单为 unresolved.json。
prepared/ 是 alpha 裁边、最长边不超过1600的等比渲染副本；原图保留不覆盖。
