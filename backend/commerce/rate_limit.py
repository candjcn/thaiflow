"""
Rate Limiter（Task 5.2 + 设备匿名限流扩展）

基于内存计数，重启清零（对免费/匿名用户可接受）。

Free 用户（已登录）每日最多：
  transcription: 3 次
  tts_synthesis: 2 次
  pronunciation: 5 次

匿名设备（plan_id="device"，key 以 "device:" 开头）总计最多（不重置）：
  transcription: 5 次
  tts_synthesis: 5 次
  pronunciation: 10 次

其他套餐（plus/pro/enterprise）不限制。

公开接口：
  check_rate_limit(user_id, capability, plan_id) → bool  True=允许
  increment(user_id, capability)                  → int   累计次数
  get_usage(user_id, capability)                  → int   已使用次数
  get_limit(capability, plan_id)                  → int | None
  reset_all()                                     → None  仅测试用
"""
import threading
import datetime
from config import get_logger

logger = get_logger(__name__)

# ── 限额配置 ──────────────────────────────────────────────────────────────────

# Free 套餐日限额（capability → max_calls_per_day）
_FREE_DAILY_LIMITS: dict[str, int] = {
    "transcription": 3,
    "tts_synthesis": 2,
    "pronunciation": 5,
}

# 匿名设备总限额（capability → max_calls_total，不重置）
_ANON_TOTAL_LIMITS: dict[str, int] = {
    "transcription": 3,
    "tts_synthesis": 5,
    "pronunciation": 10,
    "content_gen":   5,
}

# ── 内存计数器 ────────────────────────────────────────────────────────────────
# key: (user_id, capability, date_str)  →  count
_counters: dict[tuple, int] = {}
_lock = threading.Lock()


# ── 公开 API ──────────────────────────────────────────────────────────────────

def check_rate_limit(user_id: str, capability: str, plan_id: str) -> bool:
    """
    检查该用户今日对该 capability 是否还有剩余配额。

    Returns:
        True  = 允许（未超限，或该套餐无限制）
        False = 拒绝（已达上限）
    """
    limit = _get_limit(capability, plan_id)
    if limit is None:
        return True   # 非 free 套餐或非受限 capability，直接放行

    key = _make_key(user_id, capability)
    with _lock:
        return _counters.get(key, 0) < limit


def increment(user_id: str, capability: str) -> int:
    """
    记录一次成功调用，返回当日累计次数。
    应在 reserve() 成功、Provider 调用前执行。
    """
    key = _make_key(user_id, capability)
    with _lock:
        _counters[key] = _counters.get(key, 0) + 1
        count = _counters[key]

    logger.debug(
        f"[rate_limit] {user_id} {capability} today={count}"
    )
    return count


def get_usage(user_id: str, capability: str) -> int:
    """返回今日已使用次数（0 = 未使用）。"""
    key = _make_key(user_id, capability)
    with _lock:
        return _counters.get(key, 0)


def get_limit(capability: str, plan_id: str) -> int | None:
    """返回日限额；None 表示无限制。"""
    return _get_limit(capability, plan_id)


def reset_all() -> None:
    """清空所有计数器（仅供测试使用）。"""
    with _lock:
        _counters.clear()


# ── 内部辅助 ──────────────────────────────────────────────────────────────────

def _make_key(user_id: str, capability: str) -> tuple:
    # 匿名设备 key 不含日期（总计限额，不重置）
    if user_id.startswith("device:"):
        return (user_id, capability)
    today = datetime.date.today().isoformat()
    return (user_id, capability, today)


def _get_limit(capability: str, plan_id: str) -> int | None:
    """返回限额：device=设备总量，free=日限，其他套餐=None（无限制）。"""
    if plan_id == "device":
        return _ANON_TOTAL_LIMITS.get(capability)
    if plan_id != "free":
        return None
    return _FREE_DAILY_LIMITS.get(capability)  # None = 该 capability 不限
