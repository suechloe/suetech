"""
任务队列
========
用 JSON 文件持久化存储任务，threading.Lock 保证并发安全。

任务结构：
  {
    id, text, chat_id, open_id, app_id, app_secret, bot_name,
    status,       # pending / running / done / error
    created_at, started_at, completed_at,
    result, error
  }
"""
import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("sue-tech.task_queue")

# 队列文件路径
_QUEUE_FILE = Path(__file__).parent.parent / "data" / "queue.json"

_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> list:
    """从文件读取任务列表（内部使用，调用方需持锁）。"""
    if not _QUEUE_FILE.exists():
        return []
    try:
        return json.loads(_QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[task_queue] 读取队列失败，返回空列表: {e}")
        return []


def _save(tasks: list) -> None:
    """写入任务列表到文件（内部使用，调用方需持锁）。"""
    _QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        _QUEUE_FILE.write_text(
            json.dumps(tasks, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.error(f"[task_queue] 写入队列失败: {e}")


def enqueue(
    task_id: str,
    text: str,
    chat_id: str,
    open_id: str,
    app_id: str,
    app_secret: str,
    bot_name: str,
) -> dict:
    """
    将新任务加入队列，返回任务 dict。

    参数：
        task_id   — 外部生成的唯一 ID（建议 uuid4）
        text      — 用户原始消息文本
        chat_id   — 飞书 chat_id（用于主动推送）
        open_id   — 发送者 open_id
        app_id    — bot 的飞书 App ID
        app_secret— bot 的飞书 App Secret
        bot_name  — bot 名称（"nora" / "sage" / "elle"）
    """
    task = {
        "id": task_id,
        "text": text,
        "chat_id": chat_id,
        "open_id": open_id,
        "app_id": app_id,
        "app_secret": app_secret,
        "bot_name": bot_name,
        "status": "pending",
        "created_at": _now_iso(),
        "started_at": None,
        "completed_at": None,
        "result": None,
        "error": None,
    }
    with _lock:
        tasks = _load()
        tasks.append(task)
        _save(tasks)
    logger.info(f"[task_queue] enqueue: {task_id} ({bot_name}) text={text[:40]!r}")
    return task


def get_pending() -> Optional[dict]:
    """
    取出一个 pending 任务，将其状态改为 running，返回该任务 dict。
    没有 pending 任务时返回 None。
    """
    with _lock:
        tasks = _load()
        for task in tasks:
            if task["status"] == "pending":
                task["status"] = "running"
                task["started_at"] = _now_iso()
                _save(tasks)
                logger.info(f"[task_queue] get_pending → {task['id']}")
                return task
    return None


def mark_done(task_id: str, result: str) -> None:
    """标记任务完成，存储结果。"""
    with _lock:
        tasks = _load()
        for task in tasks:
            if task["id"] == task_id:
                task["status"] = "done"
                task["completed_at"] = _now_iso()
                task["result"] = result
                _save(tasks)
                logger.info(f"[task_queue] mark_done: {task_id}")
                return
    logger.warning(f"[task_queue] mark_done: 未找到任务 {task_id}")


def mark_error(task_id: str, error: str) -> None:
    """标记任务失败，存储错误信息。"""
    with _lock:
        tasks = _load()
        for task in tasks:
            if task["id"] == task_id:
                task["status"] = "error"
                task["completed_at"] = _now_iso()
                task["error"] = error
                _save(tasks)
                logger.info(f"[task_queue] mark_error: {task_id} — {error[:80]}")
                return
    logger.warning(f"[task_queue] mark_error: 未找到任务 {task_id}")
