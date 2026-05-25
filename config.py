import os
from dotenv import load_dotenv

load_dotenv()

FEISHU_NORA_APP_ID     = os.getenv("FEISHU_NORA_APP_ID", "")
FEISHU_NORA_APP_SECRET = os.getenv("FEISHU_NORA_APP_SECRET", "")

FEISHU_ELLE_APP_ID     = os.getenv("FEISHU_ELLE_APP_ID", "")
FEISHU_ELLE_APP_SECRET = os.getenv("FEISHU_ELLE_APP_SECRET", "")

FEISHU_SAGE_APP_ID     = os.getenv("FEISHU_SAGE_APP_ID", "")
FEISHU_SAGE_APP_SECRET = os.getenv("FEISHU_SAGE_APP_SECRET", "")

DEEPSEEK_API_KEY  = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL    = "deepseek-chat"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL   = "claude-sonnet-4-6"

LOW_BALANCE_THRESHOLD = float(os.getenv("LOW_BALANCE_THRESHOLD", "20.0"))
ALERT_USER_ID = os.getenv("ALERT_USER_ID", "")

# ── 向后兼容：旧版 feishu_client.py 使用统一 key ──
FEISHU_APP_ID     = FEISHU_NORA_APP_ID
FEISHU_APP_SECRET = FEISHU_NORA_APP_SECRET
