"""
Sage Agent — 首席工程师
========================
优先使用 Claude（如果配置了 ANTHROPIC_API_KEY），否则使用 DeepSeek。
自动携带对话记忆，飞书与网页共享同一份历史。
"""
import logging
import time
from agents.base import chat
from tools.memory import get_history, add_turn
from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

logger = logging.getLogger("sue-tech.sage")

SYSTEM = """你是 Sage，Sue Tech 的首席工程师。

公司信息：
- 公司：Sue Tech（岁科技）
- 董事长：Chloe（你的老板，直接称呼她"Chloe"或"boss"）
- 你的职位：首席工程师，向 Chloe 负责

你的职责：
- 编写、调试、优化代码（Python、JavaScript、Shell 等）
- 解决系统和技术问题
- 自动化脚本、工具搭建
- 技术方案设计和评估

回复风格：
- 直接称呼对方为 Chloe 或 boss，绝对不要出现 @_user 这类无意义符号
- Chloe 编程零基础，解释技术内容时用大白话，明确告诉她在哪里操作、输入什么
- 简洁、精准、代码优先，给出可以直接运行的方案"""


async def sage(task: str) -> str:
    """
    优先使用 Claude，失败或未配置则回退到 DeepSeek。
    自动携带历史记忆，每次调用都记录到本地数据库。
    """
    history = get_history("sage")
    result = None

    if ANTHROPIC_API_KEY:
        try:
            import anthropic

            t0 = time.time()
            client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            msgs = [{"role": h["role"], "content": h["content"]} for h in history]
            msgs.append({"role": "user", "content": task})
            msg = await client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=4096,
                system=SYSTEM,
                messages=msgs,
            )
            duration_ms = int((time.time() - t0) * 1000)
            result = msg.content[0].text.strip()

            # 记录 Claude 调用
            try:
                from tools.api_logger import log_call
                usage = msg.usage
                log_call(
                    agent="sage",
                    model=ANTHROPIC_MODEL,
                    input_tok=usage.input_tokens  if usage else 0,
                    output_tok=usage.output_tokens if usage else 0,
                    duration_ms=duration_ms,
                )
            except Exception as e:
                logger.warning(f"[sage] 记录 Claude 用量失败: {e}")

        except Exception as e:
            logger.warning(f"[sage] Claude 调用失败，回退到 DeepSeek: {e}")
            result = None

    # 回退：使用 DeepSeek（带历史）
    if result is None:
        result = await chat(SYSTEM, task, agent="sage", history=history)

    add_turn("sage", task, result)
    return result
