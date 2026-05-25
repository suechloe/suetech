import json
import lark_oapi as lark
from lark_oapi.api.im.v1 import *
from config import FEISHU_APP_ID, FEISHU_APP_SECRET

_client = None

def get_client() -> lark.Client:
    global _client
    if _client is None:
        _client = lark.Client.builder() \
            .app_id(FEISHU_APP_ID) \
            .app_secret(FEISHU_APP_SECRET) \
            .build()
    return _client

def send_message(receive_id: str, text: str, receive_id_type: str = "open_id"):
    client = get_client()
    request = CreateMessageRequest.builder() \
        .receive_id_type(receive_id_type) \
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(receive_id)
            .msg_type("text")
            .content(json.dumps({"text": text}))
            .build()
        ).build()
    resp = client.im.v1.message.create(request)
    if not resp.success():
        print(f"[Feishu] 发送消息失败: {resp.code} {resp.msg}")

def reply_message(message_id: str, text: str):
    client = get_client()
    request = ReplyMessageRequest.builder() \
        .message_id(message_id) \
        .request_body(
            ReplyMessageRequestBody.builder()
            .content(json.dumps({"text": text}))
            .msg_type("text")
            .build()
        ).build()
    resp = client.im.v1.message.reply(request)
    if not resp.success():
        print(f"[Feishu] 回复消息失败: {resp.code} {resp.msg}")

def get_user_open_id_from_event(event) -> str:
    try:
        return event.event.sender.sender_id.open_id
    except Exception:
        return ""

def get_message_text(event) -> str:
    try:
        content = json.loads(event.event.message.content)
        return content.get("text", "").strip()
    except Exception:
        return ""

def get_message_id(event) -> str:
    try:
        return event.event.message.message_id
    except Exception:
        return ""

def get_chat_id(event) -> str:
    try:
        return event.event.message.chat_id
    except Exception:
        return ""
