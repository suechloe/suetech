from agents.base import chat, get_deepseek_client
from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, DEEPSEEK_MODEL

SYSTEM = """你是 Claude，Sue Tech 的代码工程师。你负责：
- 编写、调试、重构各类代码
- 解决技术问题，提供系统架构建议
- 编写自动化脚本
- 代码审查和优化

风格：代码优先，给出可直接运行的示例，附简短说明。"""

async def claude_agent(task: str, use_claude: bool = False) -> str:
    if use_claude and ANTHROPIC_API_KEY:
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            msg = await client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=4096,
                system=SYSTEM,
                messages=[{"role": "user", "content": task}],
            )
            return msg.content[0].text.strip()
        except Exception as e:
            return f"Claude API 调用失败：{e}\n\n切换到 DeepSeek 重试...\n\n" + await chat(SYSTEM, task)
    return await chat(SYSTEM, task)
