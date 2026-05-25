import httpx
from config import DEEPSEEK_API_KEY, LOW_BALANCE_THRESHOLD

async def get_deepseek_balance() -> dict:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.deepseek.com/user/balance",
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                timeout=10,
            )
            data = resp.json()
            infos = data.get("balance_infos", [])
            cny = next((x for x in infos if x.get("currency") == "CNY"), None)
            if cny:
                return {
                    "available": data.get("is_available", False),
                    "total": float(cny.get("total_balance", 0)),
                    "currency": "CNY",
                }
    except Exception as e:
        return {"error": str(e)}
    return {}

async def check_and_alert(send_alert_fn):
    balance = await get_deepseek_balance()
    if "error" in balance:
        return f"查询余额失败: {balance['error']}"
    total = balance.get("total", 0)
    status = "✅ 正常" if balance.get("available") else "❌ 不可用"
    msg = f"DeepSeek 余额：¥{total:.2f}  {status}"
    if total < LOW_BALANCE_THRESHOLD:
        alert = f"⚠️ 余额不足提醒\n{msg}\n低于阈值 ¥{LOW_BALANCE_THRESHOLD}，请及时充值。"
        await send_alert_fn(alert)
    return msg
