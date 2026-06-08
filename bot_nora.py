"""
Nora 飞书机器人
收到消息 → CrewAI 多 Agent 处理 → 自动回复
智能识别：提到 Nora 或日程/规划关键词自动响应，无需 @
支持：主动推送每日晨报给 Chloe（需 CHLOE_OPEN_ID 环境变量）
"""
import json, asyncio, threading, logging, re, time, datetime, os
import lark_oapi as lark
from lark_oapi.api.im.v1 import *
from config import FEISHU_NORA_APP_ID, FEISHU_NORA_APP_SECRET
from tools.api_monitor import check_and_alert
from tools.feishu_connection import FeishuConnectionManager
from tools.push import send_to_chloe
from task_handler import process_message as crew_process

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] %(levelname)s: %(message)s',
    stream=__import__('sys').stdout,
)

LABEL = "📋 Nora [CEO]"
BALANCE_KEYWORDS = ["余额", "额度", "balance"]

# Nora 响应关键词：三个 agent 的关键词全部覆盖
# Sage 和 Elle 不是独立飞书 bot，消息统一由 Nora 接收后内部路由
NORA_KEYWORDS = [
    # Nora 自己
    "nora", "诺拉", "日程", "安排", "规划", "计划", "会议", "提醒", "任务", "进度", "汇报", "总结",
    # Sage（技术/代码）
    "sage", "代码", "程序", "bug", "错误", "修改", "网站", "系统", "技术", "部署", "服务器", "脚本", "开发", "功能",
    # Elle（法律）
    "elle", "法律", "合同", "协议", "维权", "起草", "条款", "纠纷", "投诉", "律师", "法规", "权益", "诉讼",
]

logger = logging.getLogger("bot_nora")

def run_async(coro):
    loop = asyncio.new_event_loop()
    threading.Thread(target=lambda: loop.run_until_complete(coro), daemon=True).start()

client = lark.Client.builder().app_id(FEISHU_NORA_APP_ID).app_secret(FEISHU_NORA_APP_SECRET).build()

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
    """判断 Nora 是否应该响应这条消息"""
    text_lower = text.lower()
    return any(kw in text_lower for kw in NORA_KEYWORDS)

def on_message(data: P2ImMessageReceiveV1):
    try:
        raw = json.loads(data.event.message.content).get("text", "").strip()
        text = clean_text(raw)
        chat_id = data.event.message.chat_id
        # 记录发送者 Open ID（用于主动推送功能）
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
            f"📋 Nora [CEO]\n\n"
            f"Chloe，你的飞书 Open ID 是：\n`{sender_open_id}`\n\n"
            f"把这个 ID 告诉 Sage，他会帮你配置主动推送功能。"
        )
        logger.info(f"[Nora] 用户 Open ID 查询：{sender_open_id}")
        return

    if not should_respond(text):
        return

    print(f"[Nora] 收到消息: chat={chat_id[:12]}... text={text[:80]}", flush=True)
    send_message(chat_id, "⏳ 处理中...")

    async def run():
        try:
            if any(kw in text for kw in BALANCE_KEYWORDS):
                result = await check_and_alert(lambda m: None)
                label = LABEL
            elif any(kw in text.lower() for kw in ["sage", "代码", "程序", "bug", "错误", "修改", "网站", "系统", "技术", "部署", "服务器", "脚本", "开发", "功能"]):
                # 技术问题 → 直接调用 Sage agent
                from agents.sage import sage as sage_fn
                result = await sage_fn(text)
                label = "💻 Sage [代码]"
            elif any(kw in text.lower() for kw in ["elle", "法律", "合同", "协议", "维权", "起草", "条款", "纠纷", "投诉", "律师", "法规", "权益", "诉讼"]):
                # 法律问题 → 直接调用 Elle agent
                from agents.elle import elle as elle_fn
                result = await elle_fn(text)
                label = "⚖️ Elle [法律]"
            else:
                result = await crew_process(text, source="feishu_nora")
                label = LABEL
            send_message(chat_id, f"{label}\n\n{result}")
        except Exception as e:
            send_message(chat_id, f"❌ 出错了：{e}")

    run_async(run())

def morning_report_scheduler():
    """
    每天早上 9:00（北京时间）给 Chloe 发晨报。
    以后台线程运行，不阻塞主进程。
    """
    REPORT_HOUR_UTC = 1  # UTC 01:00 = 北京 09:00
    last_sent_date = None

    while True:
        now_utc = datetime.datetime.utcnow()
        today = now_utc.date()

        if now_utc.hour == REPORT_HOUR_UTC and last_sent_date != today:
            last_sent_date = today
            try:
                report = (
                    f"📋 Nora 晨报 — {today.strftime('%Y年%m月%d日')}\n\n"
                    f"早安 Chloe！\n\n"
                    f"三位助手今天都在线：\n"
                    f"  📋 Nora（CEO/协调）— 随时待命\n"
                    f"  💻 Sage（首席工程师）— 随时待命\n"
                    f"  ⚖️ Elle（法律顾问）— 随时待命\n\n"
                    f"有什么需要直接在群里说，我们会自动识别关键词回应。\n"
                    f"今天也加油！💪"
                )
                send_to_chloe(client, report)
                logger.info(f"[Nora] ✅ 晨报已发送 ({today})")
            except Exception as e:
                logger.error(f"[Nora] 晨报发送失败: {e}")

        time.sleep(60)  # 每分钟检查一次


if __name__ == "__main__":
    print(f"{LABEL} 启动（智能识别模式，无需 @）")

    # 启动晨报调度器（后台线程）
    if os.environ.get("CHLOE_OPEN_ID"):
        report_thread = threading.Thread(target=morning_report_scheduler, daemon=True, name="nora-morning-report")
        report_thread.start()
        print(f"[Nora] ✅ 晨报调度器已启动（每天北京时间 09:00 推送）")
    else:
        print(f"[Nora] ⚠️  CHLOE_OPEN_ID 未设置，晨报功能待激活。让 Chloe 发 '我的id' 获取。")

    connection_manager = FeishuConnectionManager(
        app_id=FEISHU_NORA_APP_ID,
        app_secret=FEISHU_NORA_APP_SECRET,
        on_message_handler=on_message,
        bot_name="Nora"
    )

    connection_manager.start()
