"""只同步图鉴属性元数据；不下载立绘、不改卡池或稀有度。"""
import json
import re
from pathlib import Path
from import_persona_assets import fetch, clean_name, PAGE_URL


def main():
    page = fetch(PAGE_URL).decode("utf-8")
    elements = {}
    for row in re.findall(r'<tr\b[^>]*data-param3="[23]"[^>]*>.*?</tr>', page, re.S):
        element = re.search(r'data-param2="([^"]+)"', row)
        name = re.search(r'<td><a[^>]+title="([^"]+)"', row)
        if name and element:
            elements["persona:" + clean_name(name[1])] = element[1]
    path = Path(__file__).resolve().parents[1] / "data/items/personas.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    updates = {item["id"]: elements[item["id"]] for item in data["items"] if item["id"] in elements}
    if len(updates) != len(data["items"]):
        raise RuntimeError("属性未完整匹配，停止写入")
    for item in data["items"]:
        item["element"] = updates[item["id"]]
        item["element_source"] = PAGE_URL
    data["_comment"] = "BWIKI图鉴2/3星素材与属性；非已核实的实际契约卡池名单。"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已同步 {len(updates)} 项属性；未修改卡池、素材或稀有度。")


if __name__ == "__main__":
    main()
