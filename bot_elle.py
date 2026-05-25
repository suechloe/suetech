"""
Elle 飞书机器人
收到消息 → 直接调用 Elle Agent → 自动回复
（不走 Nora 编排，保持与网页版 Elle 行为一致）
"""
import json, asyncio, threading, time
import lark_oapi as lark
from lark_oapi.api.im.v1 import *
from config import FEISHU_ELLE_APP_ID, FEISHU_ELLE_APP_SECRET
from agents.elle import elle as elle_fn
from task_handler import save_conversation

LABEL = "⚖️ Elle [法律]"

def run_async(coro):
    loop = asyncio.new_event_loop()
    threading.Thread(target=lambda: loop.run_until_complete(coro), daemon=True).start()

client = lark.Client.builder().app_id(FEISHU_ELLE_APP_ID).app_secret(FEISHU_ELLE_APP_SECRET).build()

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
    print(f"[Elle] {text[:80]}...")
    if not text:
        return

    reply(message_id, "⏳ 处理中...")

    async def run():
        try:
            t0 = time.time()
            result = await elle_fn(text)
            elapsed = time.time() - t0
            save_conversation(text, result, source="feishu_elle", elapsed=elapsed)
            reply(message_id, f"{LABEL}\n\n{result}")
        except Exception as e:
            reply(message_id, f"❌ 出错了：{e}")

    run_async(run())

if __name__ == "__main__":
    print(f"{LABEL} 启动 → 直接调用 Elle Agent")
    handler = lark.EventDispatcherHandler.builder("", "").register_p2_im_message_receive_v1(on_message).build()
    lark.ws.Client(FEISHU_ELLE_APP_ID, FEISHU_ELLE_APP_SECRET, event_handler=handler, log_level=lark.LogLevel.INFO).start()
