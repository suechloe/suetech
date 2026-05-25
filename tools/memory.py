"""
Nora 对话记忆模块
==================
让 Nora 记住最近 N 轮对话，不再每次从零开始。

策略：
  - 启动时从 data/results/ 加载最近历史（跨重启持久化）
  - 运行中实时追加新对话
  - 每个 bot 独立维护最近 MAX_TURNS 轮（= 20 条消息）
"""
import json
import logging
from collections import deque
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger("sue-tech.memory")

_RESULTS_DIR = Path(__file__).parent.parent / "data" / "results"

MAX_TURNS = 10          # 最多保留 10 轮（=20 条消息：user+assistant 各一条）
MAX_HISTORY_MSGS = 20   # 传给模型的最大消息数

# 进程内缓存：{bot_name: deque of {"role": ..., "content": ...}}
_memory: Dict[str, deque] = {}


def _load_from_disk(bot_name: str) -> deque:
    """从 data/results/*.json 加载最近若干轮历史对话。"""
    records = []
    if _RESULTS_DIR.exists():
        files = sorted(_RESULTS_DIR.glob("*.json"), reverse=True)
        for f in files:
            if len(records) >= MAX_TURNS:
                break
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
                # 匹配 bot 字段，或 source 字段包含 bot 名
                bot_field = r.get("bot", "")
                source = r.get("source", "")
                if bot_field == bot_name or source.endswith(bot_name):
                    inp = (r.get("input") or "").strip()
                    out = (r.get("output") or "").strip()
                    if inp and out:
                        records.append((inp, out))
            except Exception:
                pass

    buf = deque(maxlen=MAX_HISTORY_MSGS)
    for inp, out in reversed(records):   # 旧 → 新
        buf.append({"role": "user",      "content": inp})
        buf.append({"role": "assistant", "content": out})
    logger.info(f"[memory] {bot_name}: 从磁盘加载 {len(records)} 轮历史")
    return buf


def _ensure(bot_name: str) -> deque:
    if bot_name not in _memory:
        _memory[bot_name] = _load_from_disk(bot_name)
    return _memory[bot_name]


def get_history(bot_name: str) -> List[dict]:
    """返回该 bot 的历史消息列表（可直接插入 messages 参数）。"""
    return list(_ensure(bot_name))


def add_turn(bot_name: str, user_msg: str, assistant_msg: str) -> None:
    """追加一轮对话到内存缓存（不写磁盘，持久化由 task_handler 负责）。"""
    buf = _ensure(bot_name)
    buf.append({"role": "user",      "content": user_msg[:2000]})
    buf.append({"role": "assistant", "content": assistant_msg[:2000]})


def clear(bot_name: str) -> None:
    """清除指定 bot 的内存（测试用）。"""
    _memory[bot_name] = deque(maxlen=MAX_HISTORY_MSGS)
