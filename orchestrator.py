"""
Sue Tech 多 Agent 编排引擎
==========================
不依赖 CrewAI（Python 3.9 兼容），自己实现层级化多 Agent 协作：

  Nora (协调官) ──委派──▶ Sage (技术) / Elle (法律)
       │                        │
       └──── 审核 ◀─────────────┘
       │
       ▼
   最终回复（大白话）

Agent 分工：
  - Nora: CEO，分析意图、分配任务、审核结果、生成最终回复
  - Sage: 首席工程师，处理代码/系统/架构等技术问题
  - Elle: 法律顾问，处理合同/维权/合规等法律问题
"""
import logging
from agents.nora import nora as _nora_chat, nora_internal as _nora_internal
from agents.sage import sage as _sage_chat
from agents.elle import elle as _elle_chat

logger = logging.getLogger("sue-tech.agents")

# ── Agent 元数据（供 Dashboard 展示） ──

NORA_META = {
    "id": "nora",
    "name": "Nora",
    "role": "CEO / 首席协调官",
    "model": "DeepSeek",
    "status": "online",
    "description": "分析用户意图，分配任务给 Sage/Elle，审核结果，用大白话回复",
}

SAGE_META = {
    "id": "sage",
    "name": "Sage",
    "role": "首席工程师",
    "model": "DeepSeek (Claude 备用)",
    "status": "online",
    "description": "编写代码、解决技术问题、设计系统架构、搭建自动化工具",
}

ELLE_META = {
    "id": "elle",
    "name": "Elle",
    "role": "法律顾问",
    "model": "DeepSeek",
    "status": "online",
    "description": "审查合同、提供法律建议、起草律师函、评估法律风险",
}

# ── 意图分析关键词 ──

TECH_KEYWORDS = [
    "代码", "编程", "脚本", "程序", "bug", "报错", "错误", "部署",
    "服务器", "数据库", "api", "接口", "自动化", "爬虫", "网站",
    "前端", "后端", "python", "js", "html", "css", "docker",
    "nginx", "域名", "dns", "ssl", "https", "git", "命令行",
    "安装", "配置", "环境", "终端", "linux", "mac", "windows",
    "app", "小程序", "h5", "网页", "数据", "算法", "架构",
    "怎么写", "怎么改", "怎么部署", "怎么搭建", "怎么做",
]

LEGAL_KEYWORDS = [
    "合同", "法律", "律师", "起诉", "诉讼", "仲裁", "维权",
    "投诉", "退款", "赔偿", "侵权", "版权", "商标", "专利",
    "劳动法", "劳动合同", "社保", "离职", "竞业", "裁员",
    "隐私", "用户协议", "条款", "违规", "罚款", "监管",
    "消费者", "权益", "欺诈", "虚假", "公司法", "股权",
    "民法典", "法规", "合法", "违法", "合规", "风险",
]


def classify_intent(text: str) -> str:
    """
    根据关键词分类用户意图。

    Returns:
        "tech"  - 技术问题，委派 Sage
        "legal" - 法律问题，委派 Elle
        "general" - 一般问题，Nora 自己回答
    """
    text_lower = text.lower()

    # 先检查法律（避免法律技术混合误判）
    legal_score = sum(1 for kw in LEGAL_KEYWORDS if kw in text_lower)
    tech_score = sum(1 for kw in TECH_KEYWORDS if kw in text_lower)

    if legal_score >= 2 or (legal_score >= 1 and tech_score == 0):
        return "legal"
    if tech_score >= 2 or (tech_score >= 1 and legal_score == 0):
        return "tech"
    if legal_score > tech_score:
        return "legal"
    if tech_score > legal_score:
        return "tech"
    return "general"


async def nora_analyze(text: str) -> dict:
    """
    Nora 分析用户消息，判断意图并决定委派策略。

    Returns:
        {
            "intent": "tech" | "legal" | "general",
            "reason": "为什么这样判断",
            "task_for_expert": "如果需要委派，给专家的具体任务描述",
            "need_delegate": True/False,
        }
    """
    prompt = (
        f"用户发来一条消息：\n\n"
        f"「{text}」\n\n"
        f"请分析这条消息：\n\n"
        f"1. 判断意图：技术问题 / 法律问题 / 一般闲聊\n"
        f"2. 如果属于技术问题（要写代码/搭系统/排查bug等），交给 Sage\n"
        f"3. 如果属于法律问题（合同/维权/合规等），交给 Elle\n"
        f"4. 闲聊或简单问题自己回答，不需要走委派流程\n\n"
        f"请用 JSON 格式回复（不要多余内容）：\n"
        f'{{"intent": "tech或legal或general", "reason": "判断理由", '
        f'"task_for_expert": "给专家的任务（不需要委派时为空）", '
        f'"need_delegate": true或false}}'
    )

    try:
        resp = await _nora_internal(prompt)   # 内部调用，不写记忆
        # 尝试提取 JSON
        import json
        # 找 JSON 起止位置
        start = resp.find("{")
        end = resp.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(resp[start:end])
    except Exception as e:
        logger.warning(f"Nora 意图分析解析失败: {e}")

    # 回退到关键词分类
    intent = classify_intent(text)
    return {
        "intent": intent,
        "reason": f"关键词匹配判定为 {intent}",
        "task_for_expert": text,
        "need_delegate": intent != "general",
    }


async def nora_review(expert_name: str, expert_result: str, original_text: str) -> str:
    """
    Nora 审核专家输出，整合成最终大白话回复。
    """
    prompt = (
        f"用户原始问题：{original_text}\n\n"
        f"{expert_name} 给出的专业意见：\n{expert_result}\n\n"
        f"请整理成给用户的最终回复。要求：\n"
        f"1. 用大白话，用户编程零基础\n"
        f"2. 结构化呈现，便于阅读\n"
        f"3. 涉及操作时给出具体步骤\n"
        f"4. 法律类问题注明「参考意见，重大事项请咨询律师」\n"
        f"5. 简洁明了，控制在 500 字以内\n"
        f"6. 不要添加'我审核过了''我已确认'这类废话，直接输出整理后的内容"
    )
    return await _nora_internal(prompt)   # 内部调用，不写记忆


async def run_multi_agent(text: str) -> str:
    """
    执行多 Agent 协作流程。

    Phase 1: Nora 分析意图
    Phase 2: 如需委派 → 调用 Sage/Elle
    Phase 3: Nora 审核汇总
    Phase 4: 返回最终回复
    """
    # ── Phase 1: Nora 分析 ──
    logger.info(f"[Phase 1] Nora 分析: {text[:80]}...")
    analysis = await nora_analyze(text)

    intent = analysis.get("intent", "general")
    need_delegate = analysis.get("need_delegate", False)
    logger.info(f"[Phase 1] 意图={intent}, 需要委派={need_delegate}")

    # ── Phase 2: 专家执行 ──
    if need_delegate and intent == "tech":
        task_desc = analysis.get("task_for_expert", text)
        logger.info(f"[Phase 2] 委派 Sage: {task_desc[:80]}...")
        expert_result = await _sage_chat(task_desc)
        expert_name = "Sage（首席工程师）"

    elif need_delegate and intent == "legal":
        task_desc = analysis.get("task_for_expert", text)
        logger.info(f"[Phase 2] 委派 Elle: {task_desc[:80]}...")
        expert_result = await _elle_chat(task_desc)
        expert_name = "Elle（法律顾问）"

    else:
        # 闲聊或简单问题，Nora 直接回答
        logger.info(f"[Phase 2] Nora 直接回答")
        return await _nora_chat(text)

    # ── Phase 3: Nora 审核 ──
    logger.info(f"[Phase 3] Nora 审核 {expert_name} 的结果")
    final = await nora_review(expert_name, expert_result, text)

    return final
