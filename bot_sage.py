"""
Sage 飞书机器人
收到消息 → 直接调用 Sage Agent → 自动回复
自动重连、心跳保活
"""
import json, asyncio, threading, time, logging
import lark_oapi as lark
from lark_oapi.api.im.v1 import *
from config import FEISHU_SAGE_APP_ID, FEISHU_SAGE_APP_SECRET
from tools.feishu_connection import FeishuConnectionManager
from agents.sage import sage as sage_fn
from task_handler import save_conversation

LABEL = "💻 Sage [代码]"

logger = logging.getLogger("bot_sage")

def run_async(coro):
    loop = asyncio.new_event_loop()
    threading.Thread(target=lambda: loop.run_until_complete(coro), daemon=True).start()

client = lark.Client.builder().app_id(FEISHU_SAGE_APP_ID).app_secret(FEISHU_SAGE_APP_SECRET).build()

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
    except Exception:
        return

    # 更新心跳
    if connection_manager:
        connection_manager.update_heartbeat()

    print(f"[Sage] {text[:80]}...")
    if not text:
        return

    reply(message_id, "⏳ 处理中...")

    async def run():
        try:
            t0 = time.time()
            result = await sage_fn(text)
            elapsed = time.time() - t0
            save_conversation(text, result, source="feishu_sage", elapsed=elapsed)
            reply(message_id, f"{LABEL}\n\n{result}")
        except Exception as e:
            reply(message_id, f"❌ 出错了：{e}")

    run_async(run())

if __name__ == "__main__":
    print(f"{LABEL} 启动 → 直接调用 Sage Agent (自动重连)")

    connection_manager = FeishuConnectionManager(
        app_id=FEISHU_SAGE_APP_ID,
        app_secret=FEISHU_SAGE_APP_SECRET,
        on_message_handler=on_message,
        bot_name="Sage"
    )

    connection_manager.start()
