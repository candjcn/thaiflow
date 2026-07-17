"""
Usage Log v2：AI 调用结构化记录。

调用链位置（ARCHITECTURE.md v1.1）：
  Reserve → Provider → UsageLog.record(actual_units) → Wallet.Confirm

公开函数：
  record(db, ...)        → log_id
  get_log(db, log_id)    → dict | None
  get_user_history(db, user_id, limit) → list[dict]
  get_summary(db, user_id, since_days) → dict

本模块不写 Wallet——Confirm/Release 由调用方（CommerceContext）负责。
"""
import uuid
import json
import datetime
from config import get_logger

logger = get_logger(__name__)


def record(
    db,
    *,
    user_id: str,
    capability: str,
    quality_tier: str = "standard",
    provider_id: str,
    model_id: str,
    plan_id: str,
    input_units: float = None,
    input_unit_type: str = None,
    provider_cost_usd: float = 0.0,
    credits_reserved: int = 0,
    credits_charged: int = 0,
    credits_refunded: int = 0,
    latency_ms: int = None,
    status: str = "success",
    error_code: str = None,
    retry_count: int = 0,
    fallback_used: bool = False,
    fallback_from: str = None,
    requested_at: str = None,
    completed_at: str = None,
    reservation_id: str = None,
    request_id: str = None,
    extra: dict = None,
) -> str:
    """
    写入一条 usage_log 记录，返回 log_id。

    Args:
        extra: 任意附加元数据（video_name, language 等），存为 JSON。
    """
    log_id = str(uuid.uuid4())
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    db.execute(
        """
        INSERT INTO usage_logs (
            log_id, user_id, capability, quality_tier,
            provider_id, model_id, plan_id,
            input_units, input_unit_type,
            provider_cost_usd,
            credits_reserved, credits_charged, credits_refunded,
            latency_ms, status, error_code,
            retry_count, fallback_used, fallback_from,
            requested_at, completed_at,
            reservation_id, request_id, extra_json
        ) VALUES (
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?,
            ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?, ?
        )
        """,
        (
            log_id, user_id, capability, quality_tier,
            provider_id, model_id, plan_id,
            input_units, input_unit_type,
            provider_cost_usd,
            credits_reserved, credits_charged, credits_refunded,
            latency_ms, status, error_code,
            retry_count, 1 if fallback_used else 0, fallback_from,
            requested_at or now, completed_at or now,
            reservation_id, request_id,
            json.dumps(extra, ensure_ascii=False) if extra else None,
        ),
    )
    db.commit()
    logger.debug(
        f"[usage_log] {log_id} user={user_id} cap={capability} "
        f"credits={credits_charged} status={status}"
    )
    return log_id


def get_log(db, log_id: str) -> dict | None:
    """返回单条 usage_log，不存在时返回 None。"""
    row = db.execute(
        "SELECT * FROM usage_logs WHERE log_id = ?", (log_id,)
    ).fetchone()
    if not row:
        return None
    result = dict(row)
    if result.get("extra_json"):
        try:
            result["extra"] = json.loads(result["extra_json"])
        except Exception:
            result["extra"] = None
    return result


def get_user_history(db, user_id: str, limit: int = 50, offset: int = 0) -> list:
    """返回用户最近 limit 条调用记录（倒序，支持分页）。"""
    rows = db.execute(
        """
        SELECT log_id, capability, quality_tier, provider_id,
               credits_charged, status, requested_at, latency_ms
        FROM usage_logs
        WHERE user_id = ?
        ORDER BY requested_at DESC
        LIMIT ? OFFSET ?
        """,
        (user_id, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def get_user_history_count(db, user_id: str) -> int:
    """返回用户历史记录总条数。"""
    row = db.execute(
        "SELECT COUNT(*) AS cnt FROM usage_logs WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return row["cnt"] if row else 0


def get_summary(db, user_id: str, since_days: int = 30) -> dict:
    """
    汇总用户最近 since_days 天的用量。

    Returns:
        {
            "total_credits": int,
            "by_capability": {"transcription": 18, "translation": 5, ...},
            "by_provider":   {"groq": 12, "deepseek": 11, ...},
        }
    """
    since = (
        datetime.datetime.utcnow() - datetime.timedelta(days=since_days)
    ).strftime("%Y-%m-%d %H:%M:%S")

    rows = db.execute(
        """
        SELECT capability, provider_id, SUM(credits_charged) AS total
        FROM usage_logs
        WHERE user_id = ? AND requested_at >= ? AND status = 'success'
        GROUP BY capability, provider_id
        """,
        (user_id, since),
    ).fetchall()

    total = 0
    by_cap: dict = {}
    by_prov: dict = {}

    for row in rows:
        cap   = row["capability"]
        prov  = row["provider_id"] or "unknown"
        amt   = row["total"] or 0

        total           += amt
        by_cap[cap]      = by_cap.get(cap, 0)  + amt
        by_prov[prov]    = by_prov.get(prov, 0) + amt

    return {
        "total_credits": total,
        "by_capability": by_cap,
        "by_provider":   by_prov,
    }
