"""
Nora 飞书机器人
收到消息 → CrewAI 多 Agent 处理 → 自动回复
"""
import json, asyncio, threading
import lark_oapi as lark
from lark_oapi.api.im.v1 import *
from config import FEISHU_NORA_APP_ID, FEISHU_NORA_APP_SECRET
from tools.api_monitor import check_and_alert
from task_handler import process_message as crew_process

LABEL = "📋 Nora [CEO]"
BALANCE_KEYWORDS = ["余额", "额度", "balance"]

def run_async(coro):
    loop = asyncio.new_event_loop()
    threading.Thread(target=lambda: loop.run_until_complete(coro), daemon=True).start()

client = lark.Client.builder().app_id(FEISHU_NORA_APP_ID).app_secret(FEISHU_NORA_APP_SECRET).build()

def reply(message_id, text):
    try:
        req = ReplyMessageRequest.builder().message_id(message_id).request_body(
            ReplyMessageRequestBody.builder().content(json.dumps({"text": text})).msg_type("text").build()
        ).build()
        client.im.v1.message.reply(req)
    except Exception as e:
        print(f"[Reply Error] {e}")

def on_message(data: P2ImMessageReceiveV1):
    try:
        text = json.loads(data.event.message.content).get("text", "").strip()
        message_id = data.event.message.message_id
    except Exception:
        return
    print(f"[Nora] {text[:80]}...")
    if not text:
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
    print(f"{LABEL} 启动 → CrewAI 多 Agent 模式")
    handler = lark.EventDispatcherHandler.builder("", "").register_p2_im_message_receive_v1(on_message).build()
    lark.ws.Client(FEISHU_NORA_APP_ID, FEISHU_NORA_APP_SECRET, event_handler=handler, log_level=lark.LogLevel.INFO).start()
