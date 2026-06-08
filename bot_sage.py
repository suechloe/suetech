"""
Sage 飞书机器人
收到消息 → 直接调用 Sage Agent → 自动回复
智能识别：提到 Sage 或技术/代码关键词自动响应，无需 @
"""
import json, asyncio, threading, time, logging, re
import lark_oapi as lark
from lark_oapi.api.im.v1 import *
from config import FEISHU_SAGE_APP_ID, FEISHU_SAGE_APP_SECRET
from tools.feishu_connection import FeishuConnectionManager
from agents.sage import sage as sage_fn
from task_handler import save_conversation

LABEL = "💻 Sage [代码]"

# Sage 响应关键词：提到名字 或 技术/代码相关
SAGE_KEYWORDS = ["sage", "代码", "程序", "bug", "错误", "修改", "网站", "系统", "技术", "部署", "服务器", "脚本", "开发", "功能"]

logger = logging.getLogger("bot_sage")
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] %(levelname)s: %(message)s',
    stream=__import__('sys').stdout,
)

def run_async(coro):
    loop = asyncio.new_event_loop()
    threading.Thread(target=lambda: loop.run_until_complete(coro), daemon=True).start()

client = lark.Client.builder().app_id(FEISHU_SAGE_APP_ID).app_secret(FEISHU_SAGE_APP_SECRET).build()

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
    """判断 Sage 是否应该响应这条消息"""
    text_lower = text.lower()
    return any(kw in text_lower for kw in SAGE_KEYWORDS)

def on_message(data: P2ImMessageReceiveV1):
    try:
        raw = json.loads(data.event.message.content).get("text", "").strip()
        text = clean_text(raw)
        chat_id = data.event.message.chat_id
        sender_open_id = data.event.sender.sender_id.open_id or ""
    except Exception:
        return

    if connection_manager:
        connection_manager.update_heartbeat()

    if not text:
        return

    # 特殊指令：返回发送者的 Open ID
    if "我的id" in text.lower() or "我的open id" in text.lower() or "myid" in text.lower():
        send_message(chat_id,
            f"💻 Sage [代码]\n\n"
            f"Chloe，你的飞书 Open ID 是：\n`{sender_open_id}`\n\n"
            f"把这个告诉我，我帮你配置好主动推送，让 Nora 每天早上给你发汇报。"
        )
        logger.info(f"[Sage] 用户 Open ID 查询：{sender_open_id}")
        return

    if not should_respond(text):
        return

    print(f"[Sage] 收到消息: chat={chat_id[:12]}... text={text[:80]}", flush=True)
    send_message(chat_id, "⏳ 处理中...")

    async def run():
        try:
            t0 = time.time()
            result = await sage_fn(text)
            elapsed = time.time() - t0
            save_conversation(text, result, source="feishu_sage", elapsed=elapsed)
            send_message(chat_id, f"{LABEL}\n\n{result}")
        except Exception as e:
            send_message(chat_id, f"❌ 出错了：{e}")

    run_async(run())

if __name__ == "__main__":
    print(f"{LABEL} 启动（智能识别模式，无需 @）")

    connection_manager = FeishuConnectionManager(
        app_id=FEISHU_SAGE_APP_ID,
        app_secret=FEISHU_SAGE_APP_SECRET,
        on_message_handler=on_message,
        bot_name="Sage"
    )

    connection_manager.start()
