"""
跨 Bot 共享上下文（记忆）模块
=============================
所有 Bot（Nora/Sage/Elle）共享同一个对话上下文，确保数据互通。

功能：
  - 全局对话历史（最多保留 200 条）
  - 每个 Bot 独立上下文统计
  - 自动带时间戳
  - JSON 文件持久化
"""
import json
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict

_LOCK = threading.Lock()
_CONTEXT_FILE = Path(__file__).parent.parent / "data" / "shared_context.json"
_MAX_HISTORY = 200

TZ = timezone(timedelta(hours=8))


def _now_iso() -> str:
    return datetime.now(TZ).isoformat()


def _load() -> dict:
    """加载共享上下文（内部需持锁调用）。"""
    if not _CONTEXT_FILE.exists():
        return {"history": [], "bot_contexts": {}}
    try:
        return json.loads(_CONTEXT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"history": [], "bot_contexts": {}}


def _save(data: dict) -> None:
    """保存共享上下文（内部需持锁调用）。"""
    _CONTEXT_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        _CONTEXT_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def add_to_history(bot_name: str, message: str) -> None:
    """向共享对话历史追加一条记录。"""
    entry = {
        "bot": bot_name,
        "message": message,
        "timestamp": _now_iso(),
    }
    with _LOCK:
        data = _load()
        data["history"].append(entry)
        if len(data["history"]) > _MAX_HISTORY:
            data["history"] = data["history"][-_MAX_HISTORY:]

        # 更新 Bot 独立统计
        if bot_name not in data["bot_contexts"]:
            data["bot_contexts"][bot_name] = {
                "message_count": 0,
                "last_active": None,
                "recent_messages": [],
            }
        ctx = data["bot_contexts"][bot_name]
        ctx["message_count"] += 1
        ctx["last_active"] = _now_iso()
        ctx["recent_messages"].append(message[:200])
        if len(ctx["recent_messages"]) > 20:
            ctx["recent_messages"] = ctx["recent_messages"][-20:]

        _save(data)


def get_conversation_history(limit: int = 50) -> List[dict]:
    """获取最近的跨 Bot 共享对话历史。"""
    with _LOCK:
        data = _load()
    return data.get("history", [])[-limit:]


def get_bot_context() -> Dict[str, dict]:
    """获取每个 Bot 的上下文统计。"""
    with _LOCK:
        data = _load()
    return data.get("bot_contexts", {})


def clear_history(keep_days: int = 0) -> int:
    """清除历史记录。keep_days=0 全部清除。"""
    with _LOCK:
        if keep_days <= 0:
            data = {"history": [], "bot_contexts": {}}
            _save(data)
            return 0
        data = _load()
        cutoff = datetime.now(TZ) - timedelta(days=keep_days)
        cutoff_iso = cutoff.isoformat()
        data["history"] = [
            h for h in data.get("history", [])
            if h.get("timestamp", "") >= cutoff_iso
        ]
        data["bot_contexts"] = {}
        for h in data["history"]:
            bn = h.get("bot", "unknown")
            if bn not in data["bot_contexts"]:
                data["bot_contexts"][bn] = {
                    "message_count": 0,
                    "last_active": None,
                    "recent_messages": [],
                }
            ctx = data["bot_contexts"][bn]
            ctx["message_count"] += 1
            ctx["last_active"] = h.get("timestamp")
            ctx["recent_messages"].append(h.get("message", "")[:200])
            if len(ctx["recent_messages"]) > 20:
                ctx["recent_messages"] = ctx["recent_messages"][-20:]
        _save(data)
        return len(data["history"])
