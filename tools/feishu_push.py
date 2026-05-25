"""
飞书主动推送工具
================
区别于 reply（只能回复已有消息），push 可以主动发消息给用户/群。
用于任务进度通知、完成汇报等场景。
"""
import json
import logging
import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)

logger = logging.getLogger("sue-tech.feishu_push")

_clients: dict = {}

def _get_client(app_id: str, app_secret: str) -> lark.Client:
    if app_id not in _clients:
        _clients[app_id] = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()
    return _clients[app_id]


def reply_msg(client: lark.Client, message_id: str, text: str) -> bool:
    """回复某条消息（用于即时确认）。"""
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
            logger.warning(f"[reply] 失败: {resp.code} {resp.msg}")
            return False
        return True
    except Exception as e:
        logger.error(f"[reply] 异常: {e}")
        return False


def push_to_chat(app_id: str, app_secret: str, chat_id: str, text: str) -> bool:
    """主动发消息到指定 chat_id（群或私聊）。"""
    client = _get_client(app_id, app_secret)
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
        if not resp.success():
            logger.warning(f"[push] 失败: {resp.code} {resp.msg}")
            return False
        return True
    except Exception as e:
        logger.error(f"[push] 异常: {e}")
        return False


def push_to_user(app_id: str, app_secret: str, open_id: str, text: str) -> bool:
    """主动发消息给指定用户（open_id）。"""
    client = _get_client(app_id, app_secret)
    try:
        req = CreateMessageRequest.builder() \
            .receive_id_type("open_id") \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(open_id)
                .content(json.dumps({"text": text}))
                .msg_type("text")
                .build()
            ).build()
        resp = client.im.v1.message.create(req)
        if not resp.success():
            logger.warning(f"[push_user] 失败: {resp.code} {resp.msg}")
            return False
        return True
    except Exception as e:
        logger.error(f"[push_user] 异常: {e}")
        return False
