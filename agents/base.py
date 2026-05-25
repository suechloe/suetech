"""
Agent 基础调用层
================
所有 Agent 的 DeepSeek API 调用都走这里。
功能：
  1. 自动读取 model_config.json 中激活的模型（支持网页端实时切换）
  2. 每次调用完成后写入本地 SQLite 数据库（token 用量 + 费用）
  3. 不存储 API Key，安全可靠
"""
import json
import time
import logging
from pathlib import Path

from openai import AsyncOpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

logger = logging.getLogger("sue-tech.base")

_MODEL_CFG_PATH = Path(__file__).parent.parent / "data" / "model_config.json"


def get_active_model() -> str:
    """
    读取 data/model_config.json 中的 active 字段。
    切换模型时网页端写入这个文件，agent 下次调用即生效。
    """
    try:
        if _MODEL_CFG_PATH.exists():
            cfg = json.loads(_MODEL_CFG_PATH.read_text(encoding="utf-8"))
            active = cfg.get("active", "")
            # Claude 模型不走 DeepSeek，由 sage.py 单独处理
            if active and not active.startswith("claude"):
                return active
    except Exception:
        pass
    return DEEPSEEK_MODEL


def get_deepseek_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)


async def chat(
    system_prompt: str,
    user_message: str,
    model: str = None,
    agent: str = "unknown",
    history: list = None,
) -> str:
    """
    向 DeepSeek 发送一次对话请求。

    参数：
        system_prompt  - Agent 的系统提示词
        user_message   - 用户消息
        model          - 指定模型（默认读取 model_config.json）
        agent          - 调用方 agent 名称（用于日志统计）
        history        - 历史消息列表 [{"role": "user"/"assistant", "content": ...}, ...]
    """
    if model is None:
        model = get_active_model()

    # 组装消息：system + 历史 + 当前消息
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history[-20:])   # 最多带 20 条历史
    messages.append({"role": "user", "content": user_message})

    client = get_deepseek_client()
    t0 = time.time()

    resp = await client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=4096,
    )

    duration_ms = int((time.time() - t0) * 1000)

    # ── 写入本地数据库 ──
    try:
        from tools.api_logger import log_call
        usage = resp.usage
        log_call(
            agent=agent,
            model=model,
            input_tok=usage.prompt_tokens     if usage else 0,
            output_tok=usage.completion_tokens if usage else 0,
            duration_ms=duration_ms,
        )
    except Exception as e:
        logger.warning(f"[base] 记录 API 用量失败（已忽略）: {e}")

    return resp.choices[0].message.content.strip()
