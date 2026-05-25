"""
后台任务执行器
==============
启动一个守护线程，每3秒轮询任务队列。
取到任务后：
  1. 推送进度通知（开始处理）
  2. 调用 orchestrator.run_multi_agent(text)
  3. 推送最终结果（成功或失败）
  4. 结果写入 data/results/{task_id}.json

用法：
    from worker import start_worker
    start_worker()   # 在 main() 里调用一次即可
"""
import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional

from tools import task_queue
from tools.feishu_push import push_to_chat
import orchestrator
from agents.sage import sage as _sage_chat
from agents.elle import elle as _elle_chat
from tools.memory import get_history, add_turn

logger = logging.getLogger("sue-tech.worker")

_RESULTS_DIR = Path(__file__).parent / "data" / "results"

# ── 进度文案 ──────────────────────────────────────────────────────────
def _msg_start(text: str) -> str:
    preview = text[:30] + ("..." if len(text) > 30 else "")
    return f"🚀 开始处理你的任务：{preview}"


def _msg_tech() -> str:
    return "💻 Nora 已将任务交给 Sage 处理..."


def _msg_legal() -> str:
    return "⚖️ Nora 已将任务交给 Elle 处理..."


def _msg_done(result: str, bot_name: str = "nora") -> str:
    body = result
    if len(body) > 18800:
        body = body[:18800] + "\n\n…（内容过长已截断）"
    if bot_name == "sage":
        prefix = "💻 Sage 回复："
    elif bot_name == "elle":
        prefix = "⚖️ Elle 回复："
    else:
        prefix = "✅ 任务完成！"
    return f"{prefix}\n\n{body}"


def _msg_error(error: str) -> str:
    return f"❌ 处理出错：{error}\n\n请重试或换个方式描述问题"


# ── 安全推送（失败只 log，不抛异常） ─────────────────────────────────
# ── 带上下文的 Agent 调用 ──────────────────────────────────────────────
async def _sage_with_history(text: str) -> str:
    """Sage 调用，加载对话历史，完成后保存。"""
    history = get_history("sage")
    from agents.sage import SYSTEM as SAGE_SYSTEM
    from agents.base import chat as deepseek_chat
    from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

    if ANTHROPIC_API_KEY and history:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        msgs = [{"role": h["role"], "content": h["content"]} for h in history]
        msgs.append({"role": "user", "content": text})
        msg = await client.messages.create(
            model=ANTHROPIC_MODEL, max_tokens=4096,
            system=SAGE_SYSTEM, messages=msgs,
        )
        result = msg.content[0].text.strip()
    elif ANTHROPIC_API_KEY:
        result = await _sage_chat(text)
    else:
        result = await deepseek_chat(SAGE_SYSTEM, text, agent="sage", history=history)

    add_turn("sage", text, result)
    return result


async def _elle_with_history(text: str) -> str:
    """Elle 调用，加载对话历史，完成后保存。"""
    history = get_history("elle")
    from agents.elle import SYSTEM as ELLE_SYSTEM
    from agents.base import chat as deepseek_chat
    result = await deepseek_chat(ELLE_SYSTEM, text, agent="elle", history=history)
    add_turn("elle", text, result)
    return result


def _safe_push(app_id: str, app_secret: str, chat_id: str, text: str) -> None:
    try:
        ok = push_to_chat(app_id, app_secret, chat_id, text)
        if not ok:
            logger.warning(f"[worker] push 返回失败，继续执行")
    except Exception as e:
        logger.warning(f"[worker] push 异常（已忽略）: {e}")


# ── 保存结果到文件 ────────────────────────────────────────────────────
def _save_result(task: dict, result: Optional[str], error: Optional[str]) -> None:
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "task_id": task["id"],
        "bot_name": task["bot_name"],
        "text": task["text"],
        "chat_id": task["chat_id"],
        "open_id": task["open_id"],
        "started_at": task.get("started_at"),
        "result": result,
        "error": error,
    }
    out_path = _RESULTS_DIR / f"{task['id']}.json"
    try:
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"[worker] 结果已写入 {out_path.name}")
    except Exception as e:
        logger.warning(f"[worker] 写入结果文件失败: {e}")


# ── 单任务执行 ────────────────────────────────────────────────────────
def _execute_task(task: dict) -> None:
    app_id = task["app_id"]
    app_secret = task["app_secret"]
    chat_id = task["chat_id"]
    text = task["text"]
    task_id = task["id"]

    # 1. 推送"开始处理"
    _safe_push(app_id, app_secret, chat_id, _msg_start(text))

    bot_name = task.get("bot_name", "nora")

    try:
        # 2. 根据 bot_name 分配到对应 Agent
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            if bot_name == "sage":
                logger.info(f"[worker] 任务 {task_id} → Sage 直接处理（带历史）")
                result = loop.run_until_complete(_sage_with_history(text))
            elif bot_name == "elle":
                logger.info(f"[worker] 任务 {task_id} → Elle 直接处理（带历史）")
                result = loop.run_until_complete(_elle_with_history(text))
            else:
                logger.info(f"[worker] 任务 {task_id} → Nora 多 Agent 协作")
                result = loop.run_until_complete(orchestrator.run_multi_agent(text))
        finally:
            loop.close()

        # 3a. 推送成功结果
        _safe_push(app_id, app_secret, chat_id, _msg_done(result, bot_name))

        # 4. 持久化
        _save_result(task, result=result, error=None)

        # 更新队列状态
        task_queue.mark_done(task_id, result)

    except Exception as e:
        err_str = str(e)
        logger.error(f"[worker] 任务 {task_id} 执行失败: {err_str}", exc_info=True)

        # 3b. 推送失败通知
        _safe_push(app_id, app_secret, chat_id, _msg_error(err_str))

        # 4. 持久化
        _save_result(task, result=None, error=err_str)

        # 更新队列状态
        task_queue.mark_error(task_id, err_str)


# ── 轮询循环 ──────────────────────────────────────────────────────────
def _worker_loop() -> None:
    logger.info("[worker] 后台 worker 已启动，轮询间隔 3 秒")
    while True:
        try:
            task = task_queue.get_pending()
            if task:
                logger.info(f"[worker] 取到任务 {task['id']}，开始执行")
                _execute_task(task)
            else:
                time.sleep(3)
        except Exception as e:
            # 顶层防御，防止 worker 线程意外退出
            logger.error(f"[worker] 轮询异常（已忽略）: {e}", exc_info=True)
            time.sleep(3)


# ── 对外接口 ──────────────────────────────────────────────────────────
def start_worker() -> threading.Thread:
    """
    在守护线程中启动后台 worker，返回线程对象。
    在 main() 中调用一次即可。
    """
    t = threading.Thread(target=_worker_loop, name="sue-tech-worker", daemon=True)
    t.start()
    logger.info("[worker] 守护线程已启动")
    return t
