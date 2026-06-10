"""
主动推送模块 — 让 Nora 主动给 Chloe 发飞书消息
用法：
  from tools.push import send_to_chloe
  send_to_chloe(client, "早安 Chloe！今日汇报...")
"""
import json
import logging
import os
from pathlib import Path
from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

logger = logging.getLogger("sue-tech.push")


def _data_dir() -> Path:
    """Return the writable data directory used by local PM2 and Railway."""
    configured = os.environ.get("SUE_TECH_DATA_DIR")
    if configured:
        path = Path(configured)
    elif Path("/data").exists():
        path = Path("/data")
    else:
        path = Path(__file__).resolve().parents[1] / "data"

    path.mkdir(parents=True, exist_ok=True)
    return path


CHLOE_OPEN_ID_FILE = _data_dir() / "chloe_open_id.txt"


def get_chloe_open_id() -> str:
    """Resolve Chloe's Feishu Open ID from env first, then persisted runtime state."""
    env_value = os.environ.get("CHLOE_OPEN_ID", "").strip()
    if env_value:
        return env_value

    try:
        return CHLOE_OPEN_ID_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except Exception as e:
        logger.error(f"[Push] 读取 Chloe Open ID 失败: {e}")
        return ""


def save_chloe_open_id(open_id: str) -> bool:
    """Persist Chloe's Feishu Open ID so Railway restarts do not disable reports."""
    open_id = (open_id or "").strip()
    if not open_id:
        return False

    try:
        CHLOE_OPEN_ID_FILE.write_text(open_id, encoding="utf-8")
        logger.info("[Push] ✅ Chloe Open ID 已保存")
        return True
    except Exception as e:
        logger.error(f"[Push] 保存 Chloe Open ID 失败: {e}")
        return False


def send_to_chloe(client, text: str) -> bool:
    """
    主动给 Chloe 发飞书私信。
    优先使用 CHLOE_OPEN_ID 环境变量；没有变量时读取运行时保存的 Open ID。
    """
    chloe_open_id = get_chloe_open_id()
    if not chloe_open_id:
        logger.warning("[Push] Chloe Open ID 未配置，无法主动推送。请让 Chloe 给 Nora 发送 '激活晨报'。")
        return False

    try:
        req = CreateMessageRequest.builder() \
            .receive_id_type("open_id") \
            .request_body(
                CreateMessageRequestBody.builder()
                    .receive_id(chloe_open_id)
                    .content(json.dumps({"text": text}))
                    .msg_type("text")
                    .build()
            ).build()
        resp = client.im.v1.message.create(req)
        if resp.success():
            logger.info(f"[Push] ✅ 主动推送成功")
            return True
        else:
            logger.error(f"[Push] ❌ 推送失败: {resp.msg}")
            return False
    except Exception as e:
        logger.error(f"[Push] 异常: {e}")
        return False


def send_to_chat(client, chat_id: str, text: str) -> bool:
    """发送消息到群聊（已有功能的封装）"""
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
        resp = client.im.v1.message.create(req)
        return resp.success()
    except Exception as e:
        logger.error(f"[Push] 群发异常: {e}")
        return False
