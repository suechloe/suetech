"""
Nora Agent — CEO / 首席协调官
================================
使用 DeepSeek V4 Pro，自动携带最近对话历史，让 Nora 记住你说过的话。
"""
import logging
from agents.base import chat
from tools.memory import get_history, add_turn

logger = logging.getLogger("sue-tech.nora")

SYSTEM = """你是 Sue Tech（岁科技）的 AI 助手 Nora。你的核心原则：

1. **以用户需求为中心**，而不是扮演某个角色。用户说什么就响应什么，不需要维持"CEO人设"。
2. **直接回答问题，不绕圈子**。能一句话说清楚的就不要三段话。
3. **需要分工时**：技术问题叫 Sage，法律问题叫 Elle，你会协调。但日常对话你自己回答就行，不用每次都走流程。
4. **用户（Chloe）编程零基础**，技术内容用大白话解释，告诉她具体操作步骤。
5. **记忆上下文**：对话历史已附在上方，前后连贯地回复，自由切换话题。
6. **诚实**：不知道就说不知道，不会就说不会，不要编造。

公司：Sue Tech（岁科技），创始人：Chloe（就是你现在对话的人）。"""


async def nora(task: str) -> str:
    """对外调用：带历史记忆，记录对话。供直接回复用户时使用。"""
    history = get_history("nora")
    result = await chat(SYSTEM, task, agent="nora", history=history)
    add_turn("nora", task, result)
    return result


async def nora_internal(task: str) -> str:
    """内部调用：不读写记忆，只完成编排任务（意图分析 / 审核汇总）。"""
    return await chat(SYSTEM, task, agent="nora")
