"""
Sue Tech 多 Agent 任务处理引擎
==============================
纯 Python 3.9 原生实现，不依赖 CrewAI。

流程（4 阶段）：
  Phase 1 - Nora 分析意图（技术？法律？闲聊？）
  Phase 2 - 如需委派 → Sage（技术）或 Elle（法律）执行
  Phase 3 - Nora 审核专家输出，生成大白话最终回复
  Phase 4 - 结果持久化到 JSON，返回给调用方

特性：
  - 超时保护：默认 120 秒
  - 结果自动存储到 data/results/ + data/tasks.json
  - 线程池复用，避免阻塞 asyncio 事件循环
"""
import json
import os
import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from orchestrator import run_multi_agent

logger = logging.getLogger("sue-tech.task_handler")

# ── 路径常量 ──
DATA_DIR = Path(__file__).parent / "data"
RESULTS_DIR = DATA_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

TZ = timezone(timedelta(hours=8))

# ── 线程池 ──
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="agent")

# ── 配置 ──
CREW_TIMEOUT = int(os.environ.get("CREW_TIMEOUT", "120"))


def _bot_from_source(source: str) -> str:
    """
    从 source 标识中解析出 bot 名称。
    支持：feishu_nora / dashboard_sage / web_elle ...
    无法识别时默认 nora。
    """
    for prefix in ("feishu_", "dashboard_", "web_"):
        if source.startswith(prefix):
            name = source[len(prefix):]
            if name in ("nora", "sage", "elle"):
                return name
    return "nora"


def save_conversation(
    input_text: str,
    output_text: str,
    source: str = "dashboard_nora",
    elapsed: float = 0.0,
) -> None:
    """
    公开接口：保存一轮对话到统一记录（data/results/）。
    供 server.py 的网页聊天调用，使网页对话与飞书对话进入同一个数据池。
    """
    _save_result(input_text, output_text, source, elapsed)
    try:
        from tools.shared_context import add_to_history
        bot_name = _bot_from_source(source)
        add_to_history(bot_name, f"[IN] {input_text[:200]}")
        add_to_history(bot_name, f"[OUT] {output_text[:200]}")
    except Exception:
        pass


async def process_message(
    text: str,
    source: str = "feishu",
    timeout: int = CREW_TIMEOUT,
) -> str:
    """
    通过多 Agent 系统处理一条用户消息。

    Args:
        text: 用户消息文本
        source: 来源标识（feishu / dashboard / api）
        timeout: 超时秒数

    Returns:
        最终回复文本
    """
    loop = asyncio.get_running_loop()
    start_time = time.monotonic()

    logger.info(f"收到消息 (source={source}): {text[:100]}...")

    try:
        result_text = await asyncio.wait_for(
            loop.run_in_executor(_executor, _run_agents_sync, text),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - start_time
        logger.error(f"⏱️ 超时 ({elapsed:.1f}s > {timeout}s)")
        result_text = "⏱️ 处理超时\n\n抱歉，请稍后重试或简化问题。"
        _save_result_safe(text, result_text, source, "timeout")
        return result_text
    except Exception as e:
        elapsed = time.monotonic() - start_time
        logger.error(f"❌ 异常 ({elapsed:.1f}s): {e}", exc_info=True)
        result_text = f"❌ 处理出错：{e}"
        _save_result_safe(text, result_text, source, "error")
        return result_text

    elapsed = time.monotonic() - start_time
    logger.info(f"✅ 完成 ({elapsed:.1f}s)")

    _save_result(text, result_text, source, elapsed)

    # 写入跨 Bot 共享上下文
    try:
        from tools.shared_context import add_to_history
        bot_name = _bot_from_source(source)
        add_to_history(bot_name, f"[IN] {text[:200]}")
        add_to_history(bot_name, f"[OUT] {result_text[:200]}")
    except Exception:
        pass

    return result_text


def _run_agents_sync(text: str) -> str:
    """
    在多 Agent 线程池中同步执行。

    run_multi_agent 是 async 函数，需要在新 event loop 中运行。
    """
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(run_multi_agent(text))
    finally:
        loop.close()


# ── 结果持久化 ──

def _save_result(input_text, output_text, source, elapsed):
    """存储完整结果到 data/results/{id}.json。"""
    now = datetime.now(TZ)
    timestamp = now.strftime("%Y%m%d_%H%M%S_%f")[:20]

    # 从 source 提取发起 bot 名称
    bot_name = _bot_from_source(source)

    record = {
        "id": timestamp,
        "source": source,
        "bot": bot_name,
        "input": input_text,
        "input_preview": input_text[:100],
        "output": output_text,
        "output_preview": output_text[:200],
        "timestamp": now.isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "agents": ["nora", "sage", "elle"],
        "status": "done",
    }
    try:
        (RESULTS_DIR / f"{timestamp}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        logger.error(f"保存结果失败: {e}")

    _append_task(input_text, timestamp, now, "done", bot_name)


def _save_result_safe(input_text, output_text, source, status="error"):
    """安全存储（超时/异常场景，不抛异常）。"""
    try:
        now = datetime.now(TZ)
        timestamp = now.strftime("%Y%m%d_%H%M%S_%f")[:20]
        bot_name = _bot_from_source(source)
        record = {
            "id": timestamp, "source": source, "bot": bot_name,
            "input": input_text, "output": output_text,
            "timestamp": now.isoformat(),
            "agents": ["nora", "sage", "elle"],
            "status": status,
        }
        (RESULTS_DIR / f"{timestamp}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _append_task(input_text, timestamp, now, status, bot_name)
    except Exception:
        pass


def _append_task(input_text, result_id, now, status, bot_name="nora"):
    """向 tasks.json 追加任务记录（保留最近 100 条）。"""
    tasks_path = DATA_DIR / "tasks.json"
    if not tasks_path.exists():
        return
    try:
        tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
        new_id = max((t.get("id", 0) for t in tasks), default=0) + 1
        title = input_text[:50] + ("..." if len(input_text) > 50 else "")
        tasks.append({
            "id": new_id,
            "title": title,
            "agent": bot_name,
            "status": status,
            "date": now.strftime("%Y-%m-%d"),
            "description": input_text,
            "result_id": result_id,
        })
        if len(tasks) > 100:
            tasks = tasks[-100:]
        tasks_path.write_text(
            json.dumps(tasks, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"更新 tasks.json 失败: {e}")


# ── 查询接口 ──

def list_results(limit: int = 50) -> list:
    """列出最近的处理结果（降序）。"""
    if not RESULTS_DIR.exists():
        return []
    results = []
    for f in sorted(RESULTS_DIR.glob("*.json"), reverse=True)[:limit]:
        try:
            results.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return results


def get_result(result_id: str):
    """按 ID 获取单条结果。"""
    path = RESULTS_DIR / f"{result_id}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def get_stats() -> dict:
    """获取处理统计。"""
    if not RESULTS_DIR.exists():
        return {"total": 0, "done": 0, "error": 0, "timeout": 0}
    files = list(RESULTS_DIR.glob("*.json"))
    stats = {"total": len(files), "done": 0, "error": 0, "timeout": 0}
    for f in files:
        try:
            record = json.loads(f.read_text(encoding="utf-8"))
            status = record.get("status", "done")
            if status in stats:
                stats[status] += 1
        except Exception:
            pass
    return stats
