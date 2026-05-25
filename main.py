"""
Sue Tech 飞书机器人主入口
==========================
启动 3 个飞书 WebSocket 长连接，分别对应 Nora / Sage / Elle 三个机器人。

所有消息统一经过 CrewAI 多 Agent 系统处理：
  收到消息 → Nora 分析意图 → 指派 Sage/Elle → 审核结果 → 存储 → 回复

用法：
  python main.py          # 启动全部三个 bot
  python main.py nora     # 只启动 Nora
  python main.py sage     # 只启动 Sage
  python main.py elle     # 只启动 Elle
"""
import asyncio
import json
import logging
import sys
import threading
import time
import uuid

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    P2ImMessageReceiveV1,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)

from config import (
    FEISHU_NORA_APP_ID, FEISHU_NORA_APP_SECRET,
    FEISHU_SAGE_APP_ID, FEISHU_SAGE_APP_SECRET,
    FEISHU_ELLE_APP_ID, FEISHU_ELLE_APP_SECRET,
)
from tools.api_monitor import check_and_alert
from tools import task_queue
from tools.feishu_push import push_to_chat
import worker

# ── 日志 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sue-tech.bot")

# ── 余额查询关键词 ──
BALANCE_KEYWORDS = ["余额", "额度", "balance", "用量", "使用量"]


def make_client(app_id: str, app_secret: str) -> lark.Client:
    """创建飞书 Client。"""
    return lark.Client.builder().app_id(app_id).app_secret(app_secret).build()


def send_reply(client: lark.Client, message_id: str, text: str) -> bool:
    """向飞书消息发送回复。成功返回 True。"""
    try:
        req = ReplyMessageRequest.builder() \
            .message_id(message_id) \
            .request_body(
                ReplyMessageRequestBody.builder()
                .content(json.dumps({"text": text}))
                .msg_type("text")
                .build()
            ).build()
        resp = client.im.v1.message.reply(req)
        if not resp.success():
            logger.warning(f"[Reply] 失败: {resp.code} {resp.msg}")
            return False
        return True
    except Exception as e:
        logger.error(f"[Reply] 异常: {e}")
        return False


def get_text(event: P2ImMessageReceiveV1) -> str:
    """从飞书事件中提取消息文本。"""
    try:
        raw = event.event.message.content
        return json.loads(raw).get("text", "").strip()
    except Exception:
        return ""


def get_msg_id(event: P2ImMessageReceiveV1) -> str:
    """从飞书事件中提取消息 ID。"""
    try:
        return event.event.message.message_id
    except Exception:
        return ""


def get_chat_id(event: P2ImMessageReceiveV1) -> str:
    """从飞书事件中提取 chat_id。"""
    try:
        return event.event.message.chat_id
    except Exception:
        return ""


def get_open_id(event: P2ImMessageReceiveV1) -> str:
    """从飞书事件中提取发送者 open_id。"""
    try:
        return event.event.sender.sender_id.open_id
    except Exception:
        return ""


def make_handler(name: str, label: str, app_id: str, app_secret: str):
    """
    创建一个飞书消息处理器。

    余额查询走专用通道，其余消息入任务队列异步处理。
    返回 (handler_fn, client) 元组。
    """
    client = make_client(app_id, app_secret)

    def on_message(data: P2ImMessageReceiveV1) -> None:
        text = get_text(data)
        message_id = get_msg_id(data)
        chat_id = get_chat_id(data)
        open_id = get_open_id(data)

        if not text or not message_id:
            return

        logger.info(f"[{name}] 收到: {text[:80]}...")

        # 余额查询走同步通道（立即回复）
        if any(kw in text for kw in BALANCE_KEYWORDS):
            send_reply(client, message_id, "⏳ 正在查询余额...")

            def run_balance_check():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    async def _alert_fn(msg: str) -> None:
                        send_reply(client, message_id, f"⚠️ API 余额告警\n\n{msg}")
                    result = loop.run_until_complete(check_and_alert(_alert_fn))
                    send_reply(client, message_id, f"{label}\n\n{result}")
                except Exception as e:
                    logger.error(f"[{name}] 余额查询出错: {e}", exc_info=True)
                    send_reply(client, message_id, f"❌ 余额查询出错：{e}")
                finally:
                    loop.close()

            threading.Thread(target=run_balance_check, daemon=True).start()
            return

        # 普通消息：入队列，立即回复确认
        task_id = uuid.uuid4().hex
        task_queue.enqueue(
            task_id=task_id,
            text=text,
            chat_id=chat_id,
            open_id=open_id,
            app_id=app_id,
            app_secret=app_secret,
            bot_name=name,
        )
        send_reply(client, message_id, "✅ 收到！正在排队处理，完成后主动通知你 🔔")
        logger.info(f"[{name}] 任务已入队: {task_id}")

    return on_message, client


def run_bot(name: str, label: str, app_id: str, app_secret: str) -> None:
    """在新线程中运行一个飞书 WebSocket Bot。"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    on_message, _ = make_handler(name, label, app_id, app_secret)

    event_handler = lark.EventDispatcherHandler.builder("", "") \
        .register_p2_im_message_receive_v1(on_message) \
        .build()

    ws = lark.ws.Client(
        app_id, app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )
    print(f"  {label} 上线 ({app_id[:20]}...)")
    try:
        ws.start()
    except Exception as e:
        logger.error(f"[{name}] WebSocket 崩溃: {e}", exc_info=True)
        print(f"  {label} 离线: {e}")


def main() -> None:
    """启动所有飞书 Bot。"""
    print("=" * 60)
    print("  🚀 Sue Tech AI 团队启动中...")
    print("  模式：CrewAI 多 Agent 协作（Nora 统一调度）")
    print("=" * 60)

    # 启动后台任务执行器
    worker.start_worker()
    print("  ✅ 后台 Worker 已启动（任务队列模式）")

    bots = [
        ("nora", "📋 Nora [CEO]",   FEISHU_NORA_APP_ID, FEISHU_NORA_APP_SECRET),
    ]

    # 命令行参数过滤：python main.py nora → 只启动 Nora
    if len(sys.argv) > 1:
        target = sys.argv[1].lower()
        bots = [(n, l, aid, ase) for n, l, aid, ase in bots if n == target]
        if not bots:
            print(f"  未知 bot: {target}。可选: nora, sage, elle")
            return

    # 启动所有 bot 线程
    threads = []
    for name, label, app_id, app_secret in bots:
        t = threading.Thread(
            target=run_bot,
            args=(name, label, app_id, app_secret),
            daemon=True,
        )
        t.start()
        threads.append(t)
        time.sleep(1)  # 错开启动，减少飞书限流

    print()
    print("  三位 agent 已就位，等待飞书消息...")
    print("  📋 收到消息 → Nora 分析 → Sage/Elle 执行")
    print("  💾 处理结果自动存储到 data/results/")
    print("  📊 Dashboard → http://localhost:8080")
    print("=" * 60)
    print()

    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("\n  👋 Sue Tech AI 团队已下线")


if __name__ == "__main__":
    main()
