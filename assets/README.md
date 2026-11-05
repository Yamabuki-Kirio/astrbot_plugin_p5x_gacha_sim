P5X 抽卡插件的图片素材目录
================================

插件**没有素材也能跑**：立绘缺失时渲染器会画一个稀有度色块 + 角色首字占位。
往下面这几个位置丢图即可自动生效，不用改代码。

assets/portraits/<id>.png
    角色 / 武器立绘。文件名用物品 id，把非法字符换成下划线：
        角色 char:SKULL·Starlight  ->  char_SKULL·Starlight.png
        武器 weapon:KOTONE-weapon5-1 -> weapon_KOTONE-weapon5-1.png
    透明 PNG，长边 1024~1600 足够；单张别超过 2 MB，十连一次要读 10 张。
    可以用 `python tools/list_missing_portraits.py` 导出缺失清单。

assets/banner/<卡池 id>.jpg
    卡池横幅，例如 char_limited.jpg。会被压在图片顶部并做渐隐。

assets/bg.jpg
    可选的总背景，留空就用内置深色渐变。

素材来源只能是你能合法使用的图：
* 官方公告 / 官方社媒发布的宣传图；
* 你自己截的图（注意别把别人的 UID 截进去）；
* 官方素材站（如果开服时有）。
不要用第三方 wiki 的汉化立绘，也不要二次传播别人的整合包。
