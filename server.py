"""
Sue Tech Dashboard & API Server
================================
提供：
  - Dashboard HTML 页面 (/)
  - RESTful API（Agent / Model / Task / Project 管理）
  - CrewAI 多 Agent 对话 (/api/crew/chat)
  - 飞书事件 Webhook (/api/feishu/event) → CrewAI 处理 → 自动回复
  - 处理结果查询 (/api/crew/results)

启动：python server.py  →  http://localhost:8080
"""
import json
import os
import subprocess
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from tools.api_logger import (
    get_stats, get_recent, get_model_breakdown, get_agent_breakdown,
    get_period_stats, get_daily_breakdown,
)
from task_handler import (
    list_results, get_result, process_message as task_process_message,
)

# 跨 Bot 共享上下文模块
from tools.shared_context import (
    get_conversation_history, add_to_history, clear_history,
    get_bot_context,
)

from config import (
    DEEPSEEK_API_KEY, ANTHROPIC_API_KEY,
    FEISHU_NORA_APP_ID, FEISHU_NORA_APP_SECRET,
    FEISHU_SAGE_APP_ID, FEISHU_SAGE_APP_SECRET,
    FEISHU_ELLE_APP_ID, FEISHU_ELLE_APP_SECRET,
)
from agents.nora import nora as nora_fn
from agents.sage import sage as sage_fn
from agents.elle import elle as elle_fn
from orchestrator import run_multi_agent, NORA_META, SAGE_META, ELLE_META
import lark_oapi as lark

# ── 日志 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sue-tech.server")

app = FastAPI(title="Sue Tech Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

TZ = timezone(timedelta(hours=8))


# ── JSON 文件工具 ──

def load_json(filename):
    path = DATA_DIR / filename
    if not path.exists():
        return [] if "tasks" in filename or "projects" in filename else {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []

def save_json(filename, data):
    with open(DATA_DIR / filename, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


# ── 飞书回复工具 ──
_feishu_clients = {}

def _get_feishu_client(app_id, app_secret):
    if app_id not in _feishu_clients:
        _feishu_clients[app_id] = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .build()
        )
    return _feishu_clients[app_id]

def _reply_feishu(app_id, app_secret, message_id, text):
    from lark_oapi.api.im.v1 import ReplyMessageRequest, ReplyMessageRequestBody
    if not message_id or not text:
        return False
    try:
        client = _get_feishu_client(app_id, app_secret)
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
            logger.warning(f"[Feishu] 回复失败: {resp.code} {resp.msg}")
            return False
        return True
    except Exception as e:
        logger.error(f"[Feishu] 回复异常: {e}")
        return False


# ═══ Dashboard HTML ═══

@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = Path(__file__).parent / "dashboard.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h1>Sue Tech Dashboard</h1><p>dashboard.html 未找到</p>"


@app.get("/favicon.svg")
@app.get("/favicon.ico")
async def favicon():
    """品牌图标（浏览器标签页 logo）。"""
    from fastapi.responses import Response
    path = Path(__file__).parent / "favicon.svg"
    if path.exists():
        return Response(
            path.read_text(encoding="utf-8"),
            media_type="image/svg+xml",
        )
    raise HTTPException(404, "favicon 未找到")


# ═══ Agents ═══

@app.get("/api/agents")
async def get_agents():
    agents = load_json("agents.json")
    if isinstance(agents, dict) or (isinstance(agents, list) and len(agents) == 0):
        agents = [
            {"id": "nora", "name": "Nora", "role": "CEO / 协调官", "model": "DeepSeek", "status": "online"},
            {"id": "sage", "name": "Sage", "role": "首席工程师", "model": "Claude" if ANTHROPIC_API_KEY else "DeepSeek", "status": "online"},
            {"id": "elle", "name": "Elle", "role": "法律顾问", "model": "DeepSeek", "status": "online"},
        ]
        save_json("agents.json", agents)
    return agents

@app.patch("/api/agents/{agent_id}")
async def update_agent(agent_id: str, request: Request):
    body = await request.json()
    agents = load_json("agents.json")
    if not isinstance(agents, list):
        agents = []
    for a in agents:
        if a.get("id") == agent_id:
            a.update(body)
            save_json("agents.json", agents)
            return a
    raise HTTPException(404, "Agent not found")


# ═══ Models ═══

@app.get("/api/models")
async def get_models():
    config = load_json("model_config.json")
    if isinstance(config, list) or not config.get("models"):
        config = {
            "active": "deepseek-chat",
            "models": [
                {"id": "deepseek-v4-pro",   "name": "DeepSeek V4 Pro",    "provider": "DeepSeek",   "desc": "高性能 · 推荐"},
                {"id": "deepseek-v4-flash",  "name": "DeepSeek V4 Flash",  "provider": "DeepSeek",   "desc": "快速 · 轻量"},
                {"id": "deepseek-chat",      "name": "DeepSeek V3",        "provider": "DeepSeek",   "desc": "经典稳定版"},
                {"id": "claude-sonnet-4-6",  "name": "Claude Sonnet 4.6",  "provider": "Anthropic",  "desc": "Sage 专用"},
            ]
        }
        save_json("model_config.json", config)
    # 根据是否配置了 Key，标记每个模型是否可用
    for m in config.get("models", []):
        if m.get("provider") == "Anthropic":
            m["configured"] = bool(ANTHROPIC_API_KEY)
        else:
            m["configured"] = bool(DEEPSEEK_API_KEY)
    return config

@app.post("/api/models/switch")
async def switch_model(request: Request):
    body = await request.json()
    model_id = body.get("active")
    config = load_json("model_config.json")
    valid_ids = [m["id"] for m in config.get("models", [])]
    if model_id not in valid_ids:
        raise HTTPException(400, f"Invalid model. Valid: {valid_ids}")
    config["active"] = model_id
    save_json("model_config.json", config)
    return config


# ═══ API Usage ═══

@app.get("/api/api-usage")
async def get_api_usage():
    stats = load_json("api_stats.json")
    if isinstance(stats, list):
        stats = {}
    stats["deepseek_configured"] = bool(DEEPSEEK_API_KEY)
    stats["anthropic_configured"] = bool(ANTHROPIC_API_KEY)
    stats["deepseek_key_preview"] = (
        DEEPSEEK_API_KEY[:6] + "..." + DEEPSEEK_API_KEY[-4:]
        if len(DEEPSEEK_API_KEY) >= 10 else DEEPSEEK_API_KEY
    ) if DEEPSEEK_API_KEY else ""
    stats["anthropic_key_preview"] = (
        ANTHROPIC_API_KEY[:10] + "..." + ANTHROPIC_API_KEY[-4:]
        if len(ANTHROPIC_API_KEY) >= 14 else ANTHROPIC_API_KEY
    ) if ANTHROPIC_API_KEY else ""
    return stats

@app.post("/api/api-usage/record")
async def record_api_call(request: Request):
    body = await request.json()
    stats = load_json("api_stats.json")
    if isinstance(stats, list):
        stats = {}
    stats["total_calls"] = stats.get("total_calls", 0) + 1
    stats["total_tokens"] = stats.get("total_tokens", 0) + body.get("tokens", 0)
    stats["estimated_cost"] = round(stats.get("estimated_cost", 0.0) + body.get("cost", 0.0), 6)
    stats["last_updated"] = datetime.now(tz=TZ).isoformat()
    save_json("api_stats.json", stats)
    return stats


# ═══ Tasks ═══

@app.get("/api/tasks")
async def get_tasks():
    return load_json("tasks.json")

@app.post("/api/tasks")
async def create_task(request: Request):
    body = await request.json()
    tasks = load_json("tasks.json")
    if not isinstance(tasks, list):
        tasks = []
    new_id = max((t.get("id", 0) for t in tasks), default=0) + 1
    task = {
        "id": new_id,
        "title": body.get("title", ""),
        "agent": body.get("agent", "nora"),
        "status": body.get("status", "pending"),
        "date": body.get("date", datetime.now(tz=TZ).strftime("%Y-%m-%d")),
        "description": body.get("description", ""),
    }
    tasks.append(task)
    save_json("tasks.json", tasks)
    return task

@app.patch("/api/tasks/{task_id}")
async def update_task(task_id: int, request: Request):
    body = await request.json()
    tasks = load_json("tasks.json")
    if not isinstance(tasks, list):
        raise HTTPException(404, "No tasks found")
    for t in tasks:
        if t.get("id") == task_id:
            t.update(body)
            save_json("tasks.json", tasks)
            return t
    raise HTTPException(404, "Task not found")

@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: int):
    tasks = load_json("tasks.json")
    if not isinstance(tasks, list):
        tasks = []
    tasks = [t for t in tasks if t.get("id") != task_id]
    save_json("tasks.json", tasks)
    return {"ok": True}


# ═══ Projects ═══

@app.get("/api/projects")
async def get_projects():
    return load_json("projects.json")

@app.post("/api/projects")
async def create_project(request: Request):
    body = await request.json()
    projects = load_json("projects.json")
    if not isinstance(projects, list):
        projects = []
    project = {
        "name": body.get("name", ""),
        "progress": body.get("progress", 0),
        "color": body.get("color", "blue"),
    }
    projects.append(project)
    save_json("projects.json", projects)
    return project

@app.patch("/api/projects/{index}")
async def update_project(index: int, request: Request):
    body = await request.json()
    projects = load_json("projects.json")
    if not isinstance(projects, list) or index < 0 or index >= len(projects):
        raise HTTPException(404, "Project not found")
    projects[index].update(body)
    save_json("projects.json", projects)
    return projects[index]


# ═══ 处理结果（跨 Bot 数据共享）═══

@app.get("/api/results")
async def get_results(bot: str = None, limit: int = 50):
    """
    列出最近的处理结果，支持按 bot 过滤。

    bot 可选值: nora / sage / elle
    不传则返回全部。
    """
    results = list_results(limit=limit * 3)  # 多取一些再过滤

    def _result_bot(r):
        """取 bot 字段；旧记录无此字段时从 source 推导。"""
        if r.get("bot"):
            return r["bot"]
        src = r.get("source", "")
        for p in ("feishu_", "dashboard_", "web_"):
            if src.startswith(p):
                name = src[len(p):]
                if name in ("nora", "sage", "elle"):
                    return name
        return "nora"

    if bot:
        results = [r for r in results if _result_bot(r) == bot]
    return {
        "total": len(results),
        "bot": bot or "all",
        "results": results[:limit],
    }

@app.get("/api/results/stats")
async def get_results_stats():
    """按 Bot 统计处理数量。"""
    results = list_results(limit=1000)  # 全量统计
    stats = {"total": len(results), "by_bot": {}, "by_status": {}}
    for r in results:
        bot_name = r.get("bot", "unknown")
        status = r.get("status", "unknown")
        stats["by_bot"][bot_name] = stats["by_bot"].get(bot_name, 0) + 1
        stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
    return stats

@app.get("/api/results/{result_id}")
async def get_single_result(result_id: str):
    """按 ID 获取单条处理结果。"""
    result = get_result(result_id)
    if result is None:
        raise HTTPException(404, f"Result not found: {result_id}")
    return result


# ═══ 共享上下文（跨 Bot 记忆）═══

@app.get("/api/context")
async def get_shared_context(limit: int = 50):
    """获取跨 Bot 共享对话历史。"""
    return {
        "history": get_conversation_history(limit),
        "bot_contexts": get_bot_context(),
    }

@app.post("/api/context")
async def add_to_context(request: Request):
    """向共享上下文追加一条记录。"""
    body = await request.json()
    message = body.get("message", "").strip()
    bot_name = body.get("bot", "nora")
    if not message:
        raise HTTPException(400, "message is required")
    add_to_history(bot_name, message)
    return {"ok": True, "bot": bot_name, "total": len(get_conversation_history())}


# ═══ Chat (单 Agent) ═══

AGENT_FNS = {"sage": sage_fn, "elle": elle_fn}

async def _chat_with_history(agent_id: str, message: str, source: str) -> str:
    """带历史记录的 Agent 对话，确保网页端与飞书端上下文一致。"""
    from agents.base import chat as deepseek_chat
    from tools.memory import get_history, add_turn

    history = get_history(agent_id)

    import time
    t0 = time.time()

    if agent_id == "sage":
        # Sage 优先走 Claude，回退到带历史的 DeepSeek
        from agents.sage import sage as _sage
        # sage() 函数内部有 Claude 调用，但我们还需要传历史
        # 重新实现：带历史的 Sage 调用
        from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL
        from agents.sage import SYSTEM as SAGE_SYSTEM
        if ANTHROPIC_API_KEY and history:
            # Claude 不支持历史拼接，用 message list 代替
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
            msgs = []
            for h in history:
                msgs.append({"role": h["role"], "content": h["content"]})
            msgs.append({"role": "user", "content": message})
            msg = await client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=4096,
                system=SAGE_SYSTEM,
                messages=msgs,
            )
            result = msg.content[0].text.strip()
        elif ANTHROPIC_API_KEY:
            # 无历史走原始的 sage()
            result = await _sage(message)
        else:
            # DeepSeek 带历史
            result = await deepseek_chat(SAGE_SYSTEM, message, agent=agent_id, history=history)
    elif agent_id == "elle":
        from agents.elle import SYSTEM as ELLE_SYSTEM
        result = await deepseek_chat(ELLE_SYSTEM, message, agent=agent_id, history=history)
    else:
        result = message  # fallback

    elapsed = time.time() - t0
    add_turn(agent_id, message, result)
    try:
        from task_handler import save_conversation
        save_conversation(message, result, source=source, elapsed=elapsed)
    except Exception as e:
        logger.warning(f"[chat] 保存对话失败: {e}")
    return result


@app.post("/api/chat/{agent_id}")
async def chat_with_agent(agent_id: str, request: Request):
    """
    与 Agent 对话（带上下文记忆）：
    - nora → 走完整四阶段编排
    - sage / elle → 直接调用各自 Agent，带对话历史
    """
    if agent_id not in ("nora", "sage", "elle"):
        raise HTTPException(404, f"Agent not found. Available: nora, sage, elle")
    body = await request.json()
    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(400, "Message is required")

    stats = load_json("api_stats.json")
    stats["total_calls"] = stats.get("total_calls", 0) + 1
    save_json("api_stats.json", stats)

    if agent_id == "nora":
        result = await task_process_message(message, source="dashboard_nora")
    else:
        result = await _chat_with_history(agent_id, message, source=f"dashboard_{agent_id}")

    return {"agent": agent_id, "response": result}


# ═══ API Config ═══

@app.get("/api/api-config")
async def get_api_config():
    path = DATA_DIR / "api_config.json"
    if path.exists():
        config = json.loads(path.read_text(encoding="utf-8"))
        for k in ["deepseek_key", "anthropic_key"]:
            v = config.get(k, "")
            config[k + "_preview"] = (v[:6] + "..." + v[-4:]) if len(v) > 10 else v
        return config
    return {
        "deepseek_key": "", "deepseek_key_preview": "",
        "deepseek_base_url": "https://api.deepseek.com",
        "anthropic_key": "", "anthropic_key_preview": "",
        "anthropic_model": "claude-sonnet-4-6",
    }

@app.post("/api/api-config")
async def save_api_config(request: Request):
    body = await request.json()
    path = DATA_DIR / "api_config.json"
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True}


# ═══ 多 Agent 协作对话（orchestrator 驱动，无需 CrewAI）═══

@app.post("/api/crew/chat")
async def crew_chat(request: Request):
    """多 Agent 协作：Nora 分析意图 → 委派 Sage/Elle → Nora 审核回复"""
    body = await request.json()
    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(400, "Message is required")
    result = await run_multi_agent(message)
    stats = load_json("api_stats.json")
    if isinstance(stats, list): stats = {}
    stats["total_calls"] = stats.get("total_calls", 0) + 1
    save_json("api_stats.json", stats)
    # 保存到统一记录（多 Agent 模式由 Nora 主导）
    try:
        from task_handler import save_conversation
        save_conversation(message, result, source="dashboard_nora")
    except Exception as e:
        logger.warning(f"[crew] 保存对话失败: {e}")
    return {"response": result, "mode": "multi-agent"}

@app.get("/api/crew/stats")
async def crew_stats():
    stats = load_json("api_stats.json")
    if isinstance(stats, list): stats = {}
    return stats


# ═══ 飞书事件 Webhook ═══

@app.post("/api/feishu/event")
async def feishu_event(request: Request):
    """飞书事件订阅 Webhook - 智能路由到对应 Bot。

    根据事件中的 app_id 路由到对应的 Agent：
      - app_id == FEISHU_NORA_APP_ID → Nora
      - app_id == FEISHU_SAGE_APP_ID → Sage
      - app_id == FEISHU_ELLE_APP_ID → Elle
    默认走 Nora。
    """
    body = await request.json()
    challenge = body.get("challenge")
    if challenge:
        return JSONResponse({"challenge": challenge})
    event_type = body.get("header", {}).get("event_type", "")
    if event_type != "im.message.receive_v1":
        return JSONResponse({"code": 0, "msg": "ignored"})
    event = body.get("event", {})
    message = event.get("message", {})
    message_id = message.get("message_id", "")
    content_str = message.get("content", "{}")
    try:
        content = json.loads(content_str)
        text = content.get("text", "").strip()
    except Exception:
        text = ""
    if not text or not message_id:
        return JSONResponse({"code": 0, "msg": "empty"})

    # 智能路由：根据 app_id 匹配对应 Bot
    raw_app_id = body.get("event", {}).get("header", {}).get("app_id", "")
    # 飞书 webhook payload 中通常不直接包含 app_id，用回调 URL 或 token 区分
    # 这里通过 body 中的 tenant_key 等字段推断，或直接用 Nora 作为默认
    # 实际发布时建议为每个 Bot 配置独立的 webhook 路径
    source = "feishu"  # webhook 来源默认走 Nora 协调

    logger.info(f"[Feishu] text={text[:80]}... source={source}")

    # 确定回复用的 app_id/app_secret
    reply_app_id = FEISHU_NORA_APP_ID
    reply_app_secret = FEISHU_NORA_APP_SECRET

    _reply_feishu(reply_app_id, reply_app_secret, message_id, "⏳ 处理中...")
    try:
        result_text = await task_process_message(text, source=source)
        if len(result_text) > 19000:
            result_text = result_text[:19000] + "\n\n…（内容过长已截断）"
        _reply_feishu(reply_app_id, reply_app_secret, message_id,
                      f"📋 CrewAI\n\n{result_text}")
        logger.info(f"[Feishu] 回复成功")
        # 记录到共享上下文
        add_to_history("nora", f"[入] {text[:100]}")
        add_to_history("nora", f"[出] {result_text[:200]}")
    except Exception as e:
        logger.error(f"[Feishu] 处理失败: {e}")
        _reply_feishu(reply_app_id, reply_app_secret, message_id,
                      f"❌ 处理出错: {e}")
    return JSONResponse({"code": 0})


# ═══ 分 Bot Webhook（为 Sage/Elle/Nora 独立配置）═══

@app.post("/api/feishu/nora")
async def feishu_nora(request: Request):
    """Nora 专属 Webhook。"""
    return await _feishu_bot_webhook(request, "feishu_nora",
                                      FEISHU_NORA_APP_ID, FEISHU_NORA_APP_SECRET)

@app.post("/api/feishu/sage")
async def feishu_sage(request: Request):
    """Sage 专属 Webhook。"""
    return await _feishu_bot_webhook(request, "feishu_sage",
                                      FEISHU_SAGE_APP_ID, FEISHU_SAGE_APP_SECRET)

@app.post("/api/feishu/elle")
async def feishu_elle(request: Request):
    """Elle 专属 Webhook。"""
    return await _feishu_bot_webhook(request, "feishu_elle",
                                      FEISHU_ELLE_APP_ID, FEISHU_ELLE_APP_SECRET)

async def _feishu_bot_webhook(request: Request, source: str,
                                app_id: str, app_secret: str):
    """通用飞书 Bot Webhook 处理器。"""
    body = await request.json()
    challenge = body.get("challenge")
    if challenge:
        return JSONResponse({"challenge": challenge})
    event_type = body.get("header", {}).get("event_type", "")
    if event_type != "im.message.receive_v1":
        return JSONResponse({"code": 0, "msg": "ignored"})
    event = body.get("event", {})
    message = event.get("message", {})
    message_id = message.get("message_id", "")
    content_str = message.get("content", "{}")
    try:
        content = json.loads(content_str)
        text = content.get("text", "").strip()
    except Exception:
        text = ""
    if not text or not message_id:
        return JSONResponse({"code": 0, "msg": "empty"})

    bot_name = source.replace("feishu_", "")
    logger.info(f"[{bot_name}] webhook text={text[:80]}...")
    _reply_feishu(app_id, app_secret, message_id, "⏳ 处理中...")
    try:
        result_text = await task_process_message(text, source=source)
        if len(result_text) > 19000:
            result_text = result_text[:19000] + "\n\n…（内容过长已截断）"
        _reply_feishu(app_id, app_secret, message_id,
                      f"{bot_name.title()}\n\n{result_text}")
        # 记录到共享上下文
        add_to_history(bot_name, f"[入] {text[:100]}")
        add_to_history(bot_name, f"[出] {result_text[:200]}")
        logger.info(f"[{bot_name}] webhook 回复成功")
    except Exception as e:
        logger.error(f"[{bot_name}] webhook 处理失败: {e}")
        _reply_feishu(app_id, app_secret, message_id,
                      f"❌ 处理出错: {e}")
    return JSONResponse({"code": 0})


# ═══ Health ═══

@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "service": "Sue Tech Dashboard",
        "mode": "crewai",
        "agents": ["nora", "sage", "elle"],
        "deepseek": bool(DEEPSEEK_API_KEY),
        "anthropic": bool(ANTHROPIC_API_KEY),
        "feishu": bool(FEISHU_NORA_APP_ID and FEISHU_NORA_APP_SECRET),
        "timestamp": datetime.now(tz=TZ).isoformat(),
    }



# ═══ DeepSeek 余额查询 ═══

@app.get("/api/balance")
async def get_balance():
    """实时查询 DeepSeek 账户余额（不暴露 API Key）。"""
    if not DEEPSEEK_API_KEY:
        return {"error": "未配置 DeepSeek API Key", "available": False}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.deepseek.com/user/balance",
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
            )
            data = resp.json()
            infos = data.get("balance_infos", [])
            cny = next((x for x in infos if x.get("currency") == "CNY"), None)
            if cny:
                return {
                    "available": data.get("is_available", False),
                    "total_balance": float(cny.get("total_balance", 0)),
                    "granted_balance": float(cny.get("granted_balance", 0)),
                    "topped_up_balance": float(cny.get("topped_up_balance", 0)),
                    "currency": "CNY",
                    "queried_at": datetime.now(tz=TZ).isoformat(),
                }
            return {"error": "余额信息格式异常", "raw": data}
    except Exception as e:
        logger.error(f"[balance] 查询失败: {e}")
        return {"error": str(e), "available": False}


# ═══ 系统状态（pm2 bot 在线情况）═══

@app.get("/api/system-status")
async def get_system_status():
    """查询 pm2 管理的 bot 进程状态。"""
    bots = [
        {"name": "nora", "label": "Nora", "icon": "📋"},
        {"name": "sage", "label": "Sage", "icon": "💻"},
        {"name": "elle", "label": "Elle", "icon": "⚖️"},
    ]
    try:
        result = subprocess.run(
            ["pm2", "jlist"],
            capture_output=True, text=True, timeout=5
        )
        processes = json.loads(result.stdout or "[]")
        pm2_map = {p["name"]: p for p in processes}
        for bot in bots:
            proc = pm2_map.get(bot["name"])
            if proc:
                status = proc.get("pm2_env", {}).get("status", "unknown")
                bot["status"] = "online" if status == "online" else "offline"
                bot["uptime"] = proc.get("pm2_env", {}).get("pm_uptime", 0)
                bot["restarts"] = proc.get("pm2_env", {}).get("restart_time", 0)
                bot["memory_mb"] = round(proc.get("monit", {}).get("memory", 0) / 1024 / 1024, 1)
            else:
                bot["status"] = "not_found"
                bot["uptime"] = 0
                bot["restarts"] = 0
                bot["memory_mb"] = 0
    except Exception as e:
        logger.warning(f"[system-status] pm2 查询失败: {e}")
        for bot in bots:
            bot["status"] = "unknown"
            bot["uptime"] = 0
            bot["restarts"] = 0
            bot["memory_mb"] = 0

    return {
        "bots": bots,
        "server_time": datetime.now(tz=TZ).isoformat(),
    }


# ═══ API 调用日志（本地数据库）═══

@app.get("/api/api-logs")
async def get_api_logs(limit: int = 50):
    """返回最近的 API 调用记录（从本地 SQLite 数据库读取）。"""
    return {
        "records": get_recent(limit),
        "stats": get_stats(),
        "by_model": get_model_breakdown(),
        "by_agent": get_agent_breakdown(),
    }

@app.get("/api/api-stats")
async def get_api_stats():
    """返回 API 用量汇总统计（含密钥脱敏信息）。"""
    stats = get_stats()
    stats["deepseek_configured"] = bool(DEEPSEEK_API_KEY)
    stats["anthropic_configured"] = bool(ANTHROPIC_API_KEY)
    stats["deepseek_key_preview"] = (
        DEEPSEEK_API_KEY[:6] + "..." + DEEPSEEK_API_KEY[-4:]
        if len(DEEPSEEK_API_KEY) >= 10 else "未配置"
    ) if DEEPSEEK_API_KEY else "未配置"
    stats["anthropic_key_preview"] = (
        ANTHROPIC_API_KEY[:10] + "..." + ANTHROPIC_API_KEY[-4:]
        if len(ANTHROPIC_API_KEY) >= 14 else "未配置"
    ) if ANTHROPIC_API_KEY else "未配置"
    return stats


@app.get("/api/usage-summary")
async def get_usage_summary():
    """
    返回完整用量汇总：今天 / 本周 / 本月 / 全部 + 最近 7 天日历。
    用于 API 用量专属页面，前端每 30 秒轮询一次。
    """
    return {
        "today":    get_period_stats("today"),
        "week":     get_period_stats("week"),
        "month":    get_period_stats("month"),
        "all":      get_stats(),
        "daily":    get_daily_breakdown(7),
        "by_agent": get_agent_breakdown(),
        "by_model": get_model_breakdown(),
        "updated_at": datetime.now(tz=TZ).isoformat(),
    }


@app.get("/preview-sage", response_class=HTMLResponse)
async def preview_sage():
    return Path(__file__).parent.joinpath("dashboard-sage.html").read_text(encoding="utf-8")

# ═══ Start ═══

if __name__ == "__main__":
    print("=" * 60)
    print("  🚀 Sue Tech 控制台 → http://localhost:8080")
    print("  📚 API 文档      → http://localhost:8080/docs")
    print("=" * 60)
    print("  🤖 CrewAI 多 Agent 系统已就绪")
    print("  📋 Nora  (CEO/协调)   → DeepSeek")
    print(f"  💻 Sage  (首席工程师) → {'Claude' if ANTHROPIC_API_KEY else 'DeepSeek'}")
    print("  ⚖️ Elle  (法律顾问)   → DeepSeek")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
