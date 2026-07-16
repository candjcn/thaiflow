"""
对账机制（Task 5.1）

每日运行：usage_logs.credits_charged 之和应等于
wallet_transactions 中 confirm 类型的扣款之和。
误差 > 0.1% 时写日志告警，可选 webhook 通知。

调用方式：
    from commerce.reconcile import run_reconciliation
    result = run_reconciliation(db, since_days=1)
    # result["ok"] is True/False
"""
import datetime
import json
from config import get_logger

logger = get_logger(__name__)

THRESHOLD_RATIO = 0.001   # 0.1%


def run_reconciliation(
    db,
    since_days: int = 1,
    webhook_url: str = None,
) -> dict:
    """
    对账：usage_logs 已收费之和 vs wallet_transactions confirm 之和。

    逻辑：
      - usage 侧: SUM(credits_charged) WHERE status='success' AND requested_at >= since
      - wallet 侧: SUM(ABS(amount))    WHERE tx_type='confirm'  AND created_at  >= since
      （confirm 流水的 amount 是负数，即原 reserve 扣款额）

    Args:
        db:          数据库连接
        since_days:  回溯天数（默认 1 = 过去 24 小时）
        webhook_url: 告警 webhook URL（可选，POST JSON）

    Returns:
        {
            "since":             str,
            "since_days":        int,
            "usage_total":       int,
            "wallet_total":      int,
            "discrepancy":       int,
            "discrepancy_ratio": float,
            "ok":                bool,
            "message":           str,
        }
    """
    since = datetime.datetime.utcnow() - datetime.timedelta(days=since_days)
    since_str = since.strftime("%Y-%m-%d %H:%M:%S")

    # ── usage_logs 侧 ─────────────────────────────────────────────────────────
    usage_row = db.execute(
        """
        SELECT COALESCE(SUM(credits_charged), 0) AS total
        FROM usage_logs
        WHERE status = 'success'
          AND requested_at >= ?
        """,
        (since_str,),
    ).fetchone()
    usage_total = int(usage_row["total"]) if usage_row else 0

    # ── wallet_transactions 侧 ────────────────────────────────────────────────
    # confirm 流水的 amount 是负数（预扣时写入），取 ABS 得实际扣款量
    wallet_row = db.execute(
        """
        SELECT COALESCE(SUM(ABS(amount)), 0) AS total
        FROM wallet_transactions
        WHERE tx_type = 'confirm'
          AND created_at >= ?
        """,
        (since_str,),
    ).fetchone()
    wallet_total = int(wallet_row["total"]) if wallet_row else 0

    # ── 误差计算 ──────────────────────────────────────────────────────────────
    discrepancy = abs(usage_total - wallet_total)
    denominator = max(usage_total, wallet_total, 1)
    ratio = discrepancy / denominator

    ok = ratio <= THRESHOLD_RATIO
    if ok:
        message = (
            f"OK (usage={usage_total} wallet={wallet_total} "
            f"since={since_str})"
        )
        logger.info(f"[reconcile] {message}")
    else:
        message = (
            f"DISCREPANCY: usage={usage_total} wallet={wallet_total} "
            f"diff={discrepancy} ratio={ratio:.4%} since={since_str}"
        )
        logger.warning(f"[reconcile] {message}")

    result = {
        "since":             since_str,
        "since_days":        since_days,
        "usage_total":       usage_total,
        "wallet_total":      wallet_total,
        "discrepancy":       discrepancy,
        "discrepancy_ratio": round(ratio, 6),
        "ok":                ok,
        "message":           message,
    }

    if not ok and webhook_url:
        _send_webhook(webhook_url, result)

    return result


# ── 内部辅助 ──────────────────────────────────────────────────────────────────

def _send_webhook(url: str, payload: dict) -> None:
    """告警 webhook（可选，fire-and-forget）。"""
    try:
        import urllib.request
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        logger.info(f"[reconcile] webhook sent → {url}")
    except Exception as e:
        logger.error(f"[reconcile] webhook failed: {e}")
