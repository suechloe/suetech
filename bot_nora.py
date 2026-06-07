"""
Nora 飞书机器人
收到消息 → CrewAI 多 Agent 处理 → 自动回复
自动重连、心跳保活
"""
import json, asyncio, threading, logging
import lark_oapi as lark
from lark_oapi.api.im.v1 import *
from config import FEISHU_NORA_APP_ID, FEISHU_NORA_APP_SECRET
from tools.api_monitor import check_and_alert
from tools.feishu_connection import FeishuConnectionManager
from task_handler import process_message as crew_process

LABEL = "📋 Nora [CEO]"
BALANCE_KEYWORDS = ["余额", "额度", "balance"]

logger = logging.getLogger("bot_nora")

def run_async(coro):
    loop = asyncio.new_event_loop()
    threading.Thread(target=lambda: loop.run_until_complete(coro), daemon=True).start()

client = lark.Client.builder().app_id(FEISHU_NORA_APP_ID).app_secret(FEISHU_NORA_APP_SECRET).build()

# 全局连接管理器引用
connection_manager: FeishuConnectionManager = None

def reply(message_id, text):
    try:
        req = ReplyMessageRequest.builder().message_id(message_id).request_body(
            ReplyMessageRequestBody.builder().content(json.dumps({"text": text})).msg_type("text").build()
        ).build()
        client.im.v1.message.reply(req)
    except Exception as e:
        logger.error(f"[Reply Error] {e}")

def clean_text(text: str) -> str:
    """清理飞书消息中的 @mention 占位符"""
    import re
    text = re.sub(r'@_user_\d+', '', text)
    return text.strip()

def on_message(data: P2ImMessageReceiveV1):
    try:
        raw = json.loads(data.event.message.content).get("text", "").strip()
        text = clean_text(raw)
        message_id = data.event.message.message_id
        chat_id = data.event.message.chat_id
    except Exception:
        return

    # 更新心跳（连接管理器用）
    if connection_manager:
        connection_manager.update_heartbeat()

    print(f"[Nora] {text[:80]}...")
    if not text:
        return

    # 只在被 @nora 时才响应
    # 检查是否被 @mention（飞书中 @mention 会包含 <at...>nora</at> 或 @nora 文本）
    is_mentioned = "@nora" in text.lower() or ("<at" in text and "nora" in text.lower())

    if not is_mentioned:
        print(f"[Nora] 消息未 @nora，忽略")
        return

    reply(message_id, "⏳ 处理中...")

    async def run():
        try:
            if any(kw in text for kw in BALANCE_KEYWORDS):
                result = await check_and_alert(lambda m: None)
            else:
                result = await crew_process(text, source="feishu_nora")
            reply(message_id, f"{LABEL}\n\n{result}")
        except Exception as e:
            reply(message_id, f"❌ 出错了：{e}")

    run_async(run())

if __name__ == "__main__":
    print(f"{LABEL} 启动 → CrewAI 多 Agent 模式 (自动重连)")

    connection_manager = FeishuConnectionManager(
        app_id=FEISHU_NORA_APP_ID,
        app_secret=FEISHU_NORA_APP_SECRET,
        on_message_handler=on_message,
        bot_name="Nora"
    )

    connection_manager.start()
