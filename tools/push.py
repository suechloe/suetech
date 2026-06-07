"""
主动推送模块 — 让 Nora 主动给 Chloe 发飞书消息
用法：
  from tools.push import send_to_chloe
  await send_to_chloe(client, "早安 Chloe！今日汇报...")
"""
import json
import logging
import os
from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

logger = logging.getLogger("sue-tech.push")

# Chloe 的飞书 Open ID（通过 "我的id" 指令获取后填入 Railway 环境变量）
CHLOE_OPEN_ID = os.environ.get("CHLOE_OPEN_ID", "")


def send_to_chloe(client, text: str) -> bool:
    """
    主动给 Chloe 发飞书私信。
    需要先在 Railway 设置 CHLOE_OPEN_ID 环境变量。
    """
    if not CHLOE_OPEN_ID:
        logger.warning("[Push] CHLOE_OPEN_ID 未设置，无法主动推送。请让 Chloe 发 '我的id' 获取。")
        return False

    try:
        req = CreateMessageRequest.builder() \
            .receive_id_type("open_id") \
            .request_body(
                CreateMessageRequestBody.builder()
                    .receive_id(CHLOE_OPEN_ID)
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
