"""事件昵称与 QQ 头像；识别方式参考夜幕档案每日运势。"""
from __future__ import annotations

import io
import time
import urllib.request

from PIL import Image

_CACHE: dict[str, tuple[float, bytes]] = {}


def display_name(event) -> str:
    try:
        name = event.get_sender_name()
    except Exception:
        name = ""
    if not name:
        name = getattr(getattr(getattr(event, "message_obj", None), "sender", None), "nickname", "")
    return " ".join(str(name or "玩家").split())[:20]


def avatar_bytes(event) -> bytes | None:
    """仅将 OneBot 的数字账号视作 QQ；网络失败不影响抽卡。"""
    try:
        meta = getattr(event, "platform_meta", None)
        kind = ""
        for holder in (meta, event):
            for attr in ("name", "type", "adapter_name"):
                value = holder.get(attr) if isinstance(holder, dict) else getattr(holder, attr, None)
                if isinstance(value, str) and value.strip():
                    kind = value.strip().lower()
                    break
            if kind:
                break
        if not kind:
            kind = str(event.get_platform_name()).lower()
        user_id = str(event.get_sender_id()).strip()
        if not (kind in {"aiocqhttp", "llonebot"} or "onebot" in kind):
            return None
        if not (user_id.isascii() and user_id.isdigit() and 5 <= len(user_id) <= 12):
            return None
        cached = _CACHE.get(user_id)
        if cached and time.monotonic() - cached[0] < 86400:
            return cached[1]
        url = f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=5) as response:
            data = response.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            return None
        with Image.open(io.BytesIO(data)) as image:
            image = image.convert("RGB")
            image.thumbnail((128, 128))
            output = io.BytesIO()
            image.save(output, format="PNG")
        data = output.getvalue()
        if len(_CACHE) >= 256:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[user_id] = (time.monotonic(), data)
        return data
    except Exception:
        return None
