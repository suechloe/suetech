"""
Nora 飞书机器人
收到消息 → CrewAI 多 Agent 处理 → 自动回复
智能识别：提到 Nora 或日程/规划关键词自动响应，无需 @
支持：主动推送每日晨报给 Chloe（CHLOE_OPEN_ID 环境变量或运行时激活）
"""
import json, asyncio, threading, logging, re, time, datetime, os
from pathlib import Path
from zoneinfo import ZoneInfo
import lark_oapi as lark
from lark_oapi.api.im.v1 import *
from config import FEISHU_NORA_APP_ID, FEISHU_NORA_APP_SECRET
from tools.api_monitor import check_and_alert
from tools.feishu_connection import FeishuConnectionManager
from tools.push import get_chloe_open_id, save_chloe_open_id, send_to_chloe
from task_handler import process_message as crew_process

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] %(levelname)s: %(message)s',
    stream=__import__('sys').stdout,
)

LABEL = "📋 Nora [CEO]"
BALANCE_KEYWORDS = ["余额", "额度", "balance"]
REPORT_TEST_KEYWORDS = ["测试晨报", "测试日报", "测试推送", "激活晨报", "激活日报"]

# Nora 只响应自己的关键词（Sage 和 Elle 是独立飞书 bot，各自处理自己的话题）
NORA_KEYWORDS = [
    "nora", "诺拉", "日程", "安排", "规划", "计划", "会议", "提醒", "任务", "进度", "汇报", "总结",
]

logger = logging.getLogger("bot_nora")

def run_async(coro):
    loop = asyncio.new_event_loop()
    threading.Thread(target=lambda: loop.run_until_complete(coro), daemon=True).start()

client = lark.Client.builder().app_id(FEISHU_NORA_APP_ID).app_secret(FEISHU_NORA_APP_SECRET).build()

connection_manager: FeishuConnectionManager = None
BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def _data_dir() -> Path:
    configured = os.environ.get("SUE_TECH_DATA_DIR")
    if configured:
        path = Path(configured)
    elif Path("/data").exists():
        path = Path("/data")
    else:
        path = Path(__file__).resolve().parent / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


LAST_REPORT_FILE = _data_dir() / "nora_last_morning_report.txt"

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


def build_morning_report(today: datetime.date) -> str:
    return (
        f"📋 Nora 晨报 — {today.strftime('%Y年%m月%d日')}\n\n"
        f"早安 Chloe！\n\n"
        f"三位助手今天都在线：\n"
        f"  📋 Nora（CEO/协调）— 随时待命\n"
        f"  💻 Sage（首席工程师）— 随时待命\n"
        f"  ⚖️ Elle（法律顾问）— 随时待命\n\n"
        f"有什么需要直接在群里说，我们会自动识别关键词回应。"
    )


def _last_report_date() -> str:
    try:
        return LAST_REPORT_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except Exception as e:
        logger.error(f"[Nora] 读取晨报发送状态失败: {e}")
        return ""


def _mark_report_sent(date_str: str):
    try:
        LAST_REPORT_FILE.write_text(date_str, encoding="utf-8")
    except Exception as e:
        logger.error(f"[Nora] 保存晨报发送状态失败: {e}")


def send_morning_report(reason: str = "schedule") -> bool:
    today = datetime.datetime.now(BEIJING_TZ).date()
    report = build_morning_report(today)
    sent = send_to_chloe(client, report)
    if sent:
        _mark_report_sent(today.isoformat())
        logger.info(f"[Nora] ✅ 晨报已发送 ({today}, reason={reason})")
    else:
        logger.error(f"[Nora] ❌ 晨报发送失败：缺少 Open ID 或飞书推送失败 (reason={reason})")
    return sent

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

    text_lower = text.lower()

    # 特殊指令：保存并返回发送者的 Open ID
    if (
        "我的id" in text_lower
        or "我的open id" in text_lower
        or "myid" in text_lower
        or any(kw in text for kw in REPORT_TEST_KEYWORDS)
    ):
        saved = save_chloe_open_id(sender_open_id)

        if any(kw in text for kw in REPORT_TEST_KEYWORDS):
            sent = send_morning_report(reason="manual-test")
            status = "✅ 测试晨报已发送。" if sent else "❌ 测试晨报发送失败，请检查飞书权限或 Open ID。"
            send_message(chat_id, f"{LABEL}\n\n{status}\nOpen ID 保存状态：{'已保存' if saved else '未保存'}")
            return

        send_message(chat_id,
            f"📋 Nora [CEO]\n\n"
            f"Chloe，你的飞书 Open ID 已记录。\n\n"
            f"晨报状态：{'已激活' if saved or get_chloe_open_id() else '未激活'}\n"
            f"你可以发送「测试晨报」让我立即验证主动推送。"
        )
        logger.info(f"[Nora] 用户 Open ID 查询并保存：{'成功' if saved else '失败'}")
        return

    if not should_respond(text):
        return

    print(f"[Nora] 收到消息: chat={chat_id[:12]}... text={text[:80]}", flush=True)
    send_message(chat_id, "⏳ 处理中...")

    async def run():
        try:
            if any(kw in text for kw in BALANCE_KEYWORDS):
                result = await check_and_alert(lambda m: None)
            else:
                result = await crew_process(text, source="feishu_nora")
            send_message(chat_id, f"{LABEL}\n\n{result}")
        except Exception as e:
            send_message(chat_id, f"❌ 出错了：{e}")

    run_async(run())

def morning_report_scheduler():
    """
    每天早上 9:00（北京时间）给 Chloe 发晨报。
    以后台线程运行，不阻塞主进程。
    """
    REPORT_HOUR_BEIJING = 9
    last_missing_id_log_at = 0

    while True:
        now = datetime.datetime.now(BEIJING_TZ)
        today = now.date().isoformat()

        if not get_chloe_open_id():
            if time.time() - last_missing_id_log_at > 3600:
                logger.warning("[Nora] 晨报调度器运行中，但 Chloe Open ID 未激活。发送「激活晨报」即可激活。")
                last_missing_id_log_at = time.time()
        elif now.hour == REPORT_HOUR_BEIJING and _last_report_date() != today:
            send_morning_report(reason="schedule")

        time.sleep(60)  # 每分钟检查一次


if __name__ == "__main__":
    print(f"{LABEL} 启动（智能识别模式，无需 @）")

    # 始终启动晨报调度器。Open ID 可通过「激活晨报」在运行时保存。
    report_thread = threading.Thread(target=morning_report_scheduler, daemon=True, name="nora-morning-report")
    report_thread.start()
    if get_chloe_open_id():
        print(f"[Nora] ✅ 晨报调度器已启动并激活（每天北京时间 09:00 推送）")
    else:
        print(f"[Nora] ⚠️  晨报调度器已启动，但缺少 Chloe Open ID。请在飞书给 Nora 发送「激活晨报」。")

    connection_manager = FeishuConnectionManager(
        app_id=FEISHU_NORA_APP_ID,
        app_secret=FEISHU_NORA_APP_SECRET,
        on_message_handler=on_message,
        bot_name="Nora"
    )

    connection_manager.start()
