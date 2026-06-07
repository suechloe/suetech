"""
Elle 飞书机器人
收到消息 → 直接调用 Elle Agent → 自动回复
智能识别：提到 Elle 或法律相关关键词自动响应，无需 @
"""
import json, asyncio, threading, time, logging, re
import lark_oapi as lark
from lark_oapi.api.im.v1 import *
from config import FEISHU_ELLE_APP_ID, FEISHU_ELLE_APP_SECRET
from tools.feishu_connection import FeishuConnectionManager
from agents.elle import elle as elle_fn
from task_handler import save_conversation

LABEL = "⚖️ Elle [法律]"

# Elle 响应关键词：提到名字 或 法律相关
ELLE_KEYWORDS = ["elle", "法律", "合同", "协议", "维权", "起草", "条款", "纠纷", "投诉", "律师", "法规", "权益", "诉讼"]

logger = logging.getLogger("bot_elle")

def run_async(coro):
    loop = asyncio.new_event_loop()
    threading.Thread(target=lambda: loop.run_until_complete(coro), daemon=True).start()

client = lark.Client.builder().app_id(FEISHU_ELLE_APP_ID).app_secret(FEISHU_ELLE_APP_SECRET).build()

connection_manager: FeishuConnectionManager = None

def send_message(chat_id, text):
    """发送新消息（不引用），避免出现 Chloe: 的前缀"""
    try:
        req = CreateMessageRequest.builder() \
            .receive_id_type("chat_id") \
            .request_body(
                CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .content(json.dumps({"text": text}))
                    .msg_type("text")
                    .build()
            ).build()
        client.im.v1.message.create(req)
    except Exception as e:
        logger.error(f"[Send Error] {e}")

def clean_text(text: str) -> str:
    """清理飞书 @mention 占位符"""
    return re.sub(r'@_user_\d+', '', text).strip()

def should_respond(text: str) -> bool:
    """判断 Elle 是否应该响应这条消息"""
    text_lower = text.lower()
    return any(kw in text_lower for kw in ELLE_KEYWORDS)

def on_message(data: P2ImMessageReceiveV1):
    try:
        raw = json.loads(data.event.message.content).get("text", "").strip()
        text = clean_text(raw)
        message_id = data.event.message.message_id
        chat_id = data.event.message.chat_id
    except Exception:
        return

    if connection_manager:
        connection_manager.update_heartbeat()

    if not text:
        return

    if not should_respond(text):
        return

    print(f"[Elle] 收到消息: {text[:80]}")
    send_message(chat_id, "⏳ 处理中...")

    async def run():
        try:
            t0 = time.time()
            result = await elle_fn(text)
            elapsed = time.time() - t0
            save_conversation(text, result, source="feishu_elle", elapsed=elapsed)
            send_message(chat_id, f"{LABEL}\n\n{result}")
        except Exception as e:
            send_message(chat_id, f"❌ 出错了：{e}")

    run_async(run())

if __name__ == "__main__":
    print(f"{LABEL} 启动（智能识别模式，无需 @）")

    connection_manager = FeishuConnectionManager(
        app_id=FEISHU_ELLE_APP_ID,
        app_secret=FEISHU_ELLE_APP_SECRET,
        on_message_handler=on_message,
        bot_name="Elle"
    )

    connection_manager.start()
