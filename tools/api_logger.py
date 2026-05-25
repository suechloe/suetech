"""
API 调用本地数据库
==================
使用 SQLite 记录每次 AI API 调用：
  时间戳 / Agent 名称 / 使用模型 / 输入输出 Token / 预估费用 / 耗时

安全：只记录用量数据，不存储 API Key。

使用方式：
    from tools.api_logger import log_call, get_stats, get_recent
"""
import sqlite3
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger("sue-tech.api_logger")

DB_PATH = Path(__file__).parent.parent / "data" / "api_calls.db"
TZ = timezone(timedelta(hours=8))

# ── DeepSeek & Anthropic 定价（每百万 token，人民币）──
# 参考 2025 年官方定价，Claude 按 USD→CNY ≈ 7.2 换算
PRICE_TABLE = {
    "deepseek-chat":       {"in": 1.0,   "out": 2.0},    # DeepSeek V3
    "deepseek-v4-pro":     {"in": 2.0,   "out": 8.0},    # V4 Pro 估算
    "deepseek-v4-flash":   {"in": 0.5,   "out": 1.5},    # V4 Flash 估算
    "deepseek-reasoner":   {"in": 4.0,   "out": 16.0},   # R1
    "claude-opus-4-5":     {"in": 108.0, "out": 540.0},  # $15/$75 * 7.2
    "claude-sonnet-4-6":   {"in": 21.6,  "out": 108.0},  # $3/$15 * 7.2
    "claude-haiku-3-5":    {"in": 5.76,  "out": 28.8},   # $0.8/$4 * 7.2
}

DEFAULT_PRICE = {"in": 2.0, "out": 8.0}


# ── DB 初始化 ─────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    """建表（已存在则忽略）。在模块导入时自动调用。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        c = _conn()
        # API 调用成本记录
        c.execute("""
            CREATE TABLE IF NOT EXISTS api_calls (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT    NOT NULL,
                agent       TEXT    NOT NULL DEFAULT '',
                model       TEXT    NOT NULL DEFAULT '',
                input_tok   INTEGER NOT NULL DEFAULT 0,
                output_tok  INTEGER NOT NULL DEFAULT 0,
                cost_cny    REAL    NOT NULL DEFAULT 0.0,
                duration_ms INTEGER NOT NULL DEFAULT 0
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_ts ON api_calls(ts)")

        # 统一对话记录（飞书 + 网页）
        c.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ts           TEXT    NOT NULL,
                source       TEXT    NOT NULL DEFAULT 'web',
                agent        TEXT    NOT NULL DEFAULT '',
                user_msg     TEXT    NOT NULL DEFAULT '',
                agent_reply  TEXT             DEFAULT '',
                task_id      TEXT             DEFAULT '',
                status       TEXT    NOT NULL DEFAULT 'done'
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_conv_ts ON conversations(ts)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_conv_agent ON conversations(agent)")

        c.commit()
        c.close()
        logger.info(f"[api_logger] DB 就绪: {DB_PATH.name}")
    except Exception as e:
        logger.error(f"[api_logger] 初始化 DB 失败: {e}")


# ── 写入 ──────────────────────────────────────────────────────────────

def calc_cost(model: str, input_tok: int, output_tok: int) -> float:
    """根据模型和 token 数计算预估费用（人民币）。"""
    p = PRICE_TABLE.get(model, DEFAULT_PRICE)
    return (input_tok * p["in"] + output_tok * p["out"]) / 1_000_000


def log_call(
    agent: str,
    model: str,
    input_tok: int,
    output_tok: int,
    duration_ms: int,
) -> None:
    """记录一次 API 调用到本地数据库（不含 Key，只记录用量）。"""
    cost = calc_cost(model, input_tok, output_tok)
    ts = datetime.now(TZ).isoformat()
    try:
        c = _conn()
        c.execute(
            "INSERT INTO api_calls (ts, agent, model, input_tok, output_tok, cost_cny, duration_ms)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ts, agent, model, input_tok, output_tok, cost, duration_ms),
        )
        c.commit()
        c.close()
    except Exception as e:
        logger.warning(f"[api_logger] 写入失败（已忽略）: {e}")


# ── 读取 ──────────────────────────────────────────────────────────────

def get_stats() -> dict:
    """返回全局汇总统计。"""
    try:
        c = _conn()
        row = c.execute(
            "SELECT COUNT(*) calls, SUM(input_tok+output_tok) tokens, SUM(cost_cny) cost"
            " FROM api_calls"
        ).fetchone()
        c.close()
        return {
            "total_calls":    int(row["calls"] or 0),
            "total_tokens":   int(row["tokens"] or 0),
            "total_cost_cny": round(float(row["cost"] or 0), 4),
        }
    except Exception as e:
        logger.warning(f"[api_logger] get_stats 失败: {e}")
        return {"total_calls": 0, "total_tokens": 0, "total_cost_cny": 0.0}


def get_recent(limit: int = 50) -> list:
    """返回最近 N 条调用记录（新→旧）。"""
    try:
        c = _conn()
        rows = c.execute(
            "SELECT id, ts, agent, model, input_tok, output_tok, cost_cny, duration_ms"
            " FROM api_calls ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        c.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"[api_logger] get_recent 失败: {e}")
        return []


def get_model_breakdown() -> list:
    """按模型分组的用量统计。"""
    try:
        c = _conn()
        rows = c.execute(
            "SELECT model, COUNT(*) calls, SUM(input_tok+output_tok) tokens, SUM(cost_cny) cost"
            " FROM api_calls GROUP BY model ORDER BY calls DESC"
        ).fetchall()
        c.close()
        return [
            {
                "model":   r["model"],
                "calls":   int(r["calls"] or 0),
                "tokens":  int(r["tokens"] or 0),
                "cost_cny": round(float(r["cost"] or 0), 4),
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"[api_logger] get_model_breakdown 失败: {e}")
        return []


def get_agent_breakdown() -> list:
    """按 agent 分组的用量统计。"""
    try:
        c = _conn()
        rows = c.execute(
            "SELECT agent, COUNT(*) calls, SUM(input_tok+output_tok) tokens, SUM(cost_cny) cost"
            " FROM api_calls GROUP BY agent ORDER BY calls DESC"
        ).fetchall()
        c.close()
        return [
            {
                "agent":  r["agent"],
                "calls":  int(r["calls"] or 0),
                "tokens": int(r["tokens"] or 0),
                "cost_cny": round(float(r["cost"] or 0), 4),
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"[api_logger] get_agent_breakdown 失败: {e}")
        return []


def get_period_stats(period: str = "today") -> dict:
    """
    按时间段返回统计。
    period: "today" | "week" | "month" | "all"
    ts 格式：2026-05-18T07:22:46+08:00，substr(ts,1,10) 取日期部分。
    """
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    # 计算起始日期字符串
    if period == "today":
        where = f"WHERE substr(ts,1,10) = '{today}'"
    elif period == "week":
        from datetime import date, timedelta as td
        start = (datetime.now(TZ) - td(days=6)).strftime("%Y-%m-%d")
        where = f"WHERE substr(ts,1,10) >= '{start}'"
    elif period == "month":
        start = datetime.now(TZ).strftime("%Y-%m-01")
        where = f"WHERE substr(ts,1,10) >= '{start}'"
    else:
        where = ""
    try:
        c = _conn()
        row = c.execute(
            f"SELECT COUNT(*) calls, SUM(input_tok+output_tok) tokens, SUM(cost_cny) cost"
            f" FROM api_calls {where}"
        ).fetchone()
        c.close()
        return {
            "period":       period,
            "total_calls":  int(row["calls"] or 0),
            "total_tokens": int(row["tokens"] or 0),
            "total_cost_cny": round(float(row["cost"] or 0), 2),
        }
    except Exception as e:
        logger.warning(f"[api_logger] get_period_stats 失败: {e}")
        return {"period": period, "total_calls": 0, "total_tokens": 0, "total_cost_cny": 0.0}


def get_daily_breakdown(days: int = 7) -> list:
    """
    返回最近 N 天每日用量（含今天）。
    返回格式：[{"date":"2026-05-18","calls":5,"tokens":3200,"cost_cny":0.02}, ...]
    """
    from datetime import timedelta as td
    dates = [
        (datetime.now(TZ) - td(days=i)).strftime("%Y-%m-%d")
        for i in range(days - 1, -1, -1)
    ]
    try:
        c = _conn()
        rows = c.execute(
            "SELECT substr(ts,1,10) day, COUNT(*) calls,"
            " SUM(input_tok+output_tok) tokens, SUM(cost_cny) cost"
            " FROM api_calls"
            f" WHERE substr(ts,1,10) >= '{dates[0]}'"
            " GROUP BY substr(ts,1,10)"
        ).fetchall()
        c.close()
        row_map = {r["day"]: r for r in rows}
        return [
            {
                "date":     d,
                "calls":    int((row_map[d]["calls"] if d in row_map else 0) or 0),
                "tokens":   int((row_map[d]["tokens"] if d in row_map else 0) or 0),
                "cost_cny": round(float((row_map[d]["cost"] if d in row_map else 0) or 0), 2),
            }
            for d in dates
        ]
    except Exception as e:
        logger.warning(f"[api_logger] get_daily_breakdown 失败: {e}")
        return [{"date": d, "calls": 0, "tokens": 0, "cost_cny": 0.0} for d in dates]


# 模块加载时自动初始化
init_db()
