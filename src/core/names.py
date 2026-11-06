"""沿用夜幕档案的分级检索：完整身份 > 别名 > 唯一包含匹配。"""
import json
import unicodedata
from pathlib import Path


def normalize_key(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(c for c in value if c not in " \t\r\n·•・‧．.－—–-_")


def identities(item):
    return tuple(str(v) for v in (
        item.id, item.id.partition(":")[2], item.name,
        *(item.meta.get(k, "") for k in ("name_cn", "name_en", "name_jp", "codename", "source_key", "slug")),
    ) if v)


class CharacterNames:
    def __init__(self, items, aliases_path=None):
        self.characters = tuple(i for i in items.values() if i.id.startswith("char:"))
        path = aliases_path or Path(__file__).resolve().parents[2] / "data" / "character_aliases.json"
        self.aliases = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def search(self, term):
        key = normalize_key(term)
        if not key:
            return ()
        for matches in (
            tuple(i for i in self.characters if normalize_key(i.name) == key),
            tuple(i for i in self.characters if any(normalize_key(v) == key for v in identities(i))),
            tuple(i for i in self.characters if i.id in {
                target for alias, target in self.aliases.items() if normalize_key(alias) == key
            }),
            tuple(i for i in self.characters if any(key in normalize_key(v) for v in identities(i))
                  or any(key in normalize_key(a) and target == i.id for a, target in self.aliases.items())),
        ):
            if matches:
                return matches
        return ()
