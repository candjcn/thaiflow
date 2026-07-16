"""
月末 Credits 重置 Cron（Task 5.3）

月初 UTC 00:00 自动执行：
  1. 过期 subscription_credits 清零（subscription_expires_at < now）
  2. 为仍有效订阅重新发放本月配额
  3. 过期 gift_credits 清零（gift_expires_at < now）

后台线程版本：Flask 启动时调用 start_cron(db_factory)，
daemon 线程自动计算下次月初并 sleep。

手动触发版本：reset_month_credits(db) 直接调用（Admin API 或测试）。
"""
import datetime
import threading
import time
from config import get_logger

logger = get_logger(__name__)


# ── 主逻辑 ────────────────────────────────────────────────────────────────────

def reset_month_credits(db) -> dict:
    """
    执行月末 Credits 重置，返回统计信息。

    Returns:
        {
            "expired_subscription": int,  # 清零的 sub_credits 钱包数
            "renewed":              int,  # 重新发放配额的用户数
            "expired_gift":         int,  # 清零的 gift_credits 钱包数
            "ran_at":               str,
        }
    """
    now     = datetime.datetime.utcnow()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    stats   = {"expired_subscription": 0, "renewed": 0, "expired_gift": 0,
               "ran_at": now_str}

    # ── 1. 过期 subscription_credits 清零 ────────────────────────────────────
    cur = db.execute(
        """
        UPDATE wallets
        SET subscription_credits = 0,
            version              = version + 1,
            updated_at           = ?
        WHERE subscription_expires_at IS NOT NULL
          AND subscription_expires_at < ?
          AND subscription_credits > 0
        """,
        (now_str, now_str),
    )
    stats["expired_subscription"] = cur.rowcount
    logger.info(f"[cron] expired subscription credits: {cur.rowcount} wallets")

    # ── 2. 活跃订阅重新发放本月配额 ─────────────────────────────────────────
    # 仅处理本月尚未重置的订阅（credits_reset_at < 本月 1 日）
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_start_str = month_start.strftime("%Y-%m-%d %H:%M:%S")

    active_subs = db.execute(
        """
        SELECT us.sub_id, us.user_id, us.credits_quota, us.expires_at,
               pd.monthly_credits
        FROM user_subscriptions us
        JOIN plan_definitions pd ON pd.plan_id = us.plan_id
        WHERE us.status = 'active'
          AND (us.expires_at IS NULL OR us.expires_at > ?)
          AND (us.credits_reset_at IS NULL OR us.credits_reset_at < ?)
        """,
        (now_str, month_start_str),
    ).fetchall()

    for sub in active_subs:
        quota = sub["credits_quota"] or sub["monthly_credits"]
        if quota <= 0:
            continue
        db.execute(
            """
            UPDATE wallets
            SET subscription_credits    = ?,
                subscription_expires_at = ?,
                version                 = version + 1,
                updated_at              = ?
            WHERE user_id = ?
            """,
            (quota, sub["expires_at"], now_str, sub["user_id"]),
        )
        # 记录本次重置时间，防止同月重复发放
        db.execute(
            "UPDATE user_subscriptions SET credits_reset_at = ? WHERE sub_id = ?",
            (now_str, sub["sub_id"]),
        )
        stats["renewed"] += 1

    logger.info(f"[cron] renewed subscription credits: {stats['renewed']} users")

    # ── 3. 过期 gift_credits 清零 ─────────────────────────────────────────────
    cur = db.execute(
        """
        UPDATE wallets
        SET gift_credits    = 0,
            gift_expires_at = NULL,
            version         = version + 1,
            updated_at      = ?
        WHERE gift_expires_at IS NOT NULL
          AND gift_expires_at < ?
          AND gift_credits > 0
        """,
        (now_str, now_str),
    )
    stats["expired_gift"] = cur.rowcount
    logger.info(f"[cron] expired gift credits: {cur.rowcount} wallets")

    db.commit()
    logger.info(f"[cron] month reset complete: {stats}")
    return stats


# ── 后台线程 ──────────────────────────────────────────────────────────────────

def start_cron(db_factory) -> threading.Thread:
    """
    启动月末 Credits 重置后台守护线程。

    Args:
        db_factory: 无参函数，返回 SQLite connection（使用 commerce.db.get_db）

    Returns:
        Thread 对象（daemon=True，随主进程退出）
    """
    def _run():
        logger.info("[cron] thread started, waiting for next month boundary")
        while True:
            sleep_sec = _seconds_until_next_month()
            logger.info(f"[cron] next reset in {sleep_sec:.0f}s "
                        f"({sleep_sec / 3600:.1f}h)")
            time.sleep(sleep_sec)
            try:
                db = db_factory()
                result = reset_month_credits(db)
                logger.info(f"[cron] month reset done: {result}")
            except Exception as exc:
                logger.error(f"[cron] month reset failed: {exc}")

    t = threading.Thread(target=_run, daemon=True, name="commerce-cron")
    t.start()
    return t


def _seconds_until_next_month() -> float:
    """计算到下一个月初 UTC 00:00:00 的秒数（最少 60 秒）。"""
    now = datetime.datetime.utcnow()
    # 下月 1 日 00:00 UTC
    if now.month == 12:
        next_month = datetime.datetime(now.year + 1, 1, 1)
    else:
        next_month = datetime.datetime(now.year, now.month + 1, 1)

    delta = (next_month - now).total_seconds()
    return max(delta, 60.0)
