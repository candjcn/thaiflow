"""
Identity 模块：用户身份管理。

过渡期约定：
  - 所有无认证请求使用 user_id = ANONYMOUS_USER_ID ("anonymous")
  - Phase 3 集成时替换为真实 JWT/session 用户 ID

公开函数：
  create_user(db, email=None) → str
  get_user(db, user_id) → dict | None
  get_user_plan(db, user_id) → str
  get_or_create_anonymous(db) → str
  set_user_subscription(db, user_id, plan_id, expires_at, credits_quota) → None
"""
import uuid
from config import get_logger

logger = get_logger(__name__)

ANONYMOUS_USER_ID = "anonymous"
DEFAULT_PLAN = "free"


def create_user(db, email: str = None) -> str:
    """
    创建新用户，返回 user_id（UUID）。
    同时创建对应的 wallet 和默认 free 订阅。
    """
    user_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO users (user_id, email) VALUES (?, ?)",
        (user_id, email),
    )
    _create_wallet(db, user_id)
    _create_default_subscription(db, user_id)
    db.commit()
    logger.info(f"[identity] created user {user_id}")
    return user_id


def get_user(db, user_id: str) -> dict | None:
    """返回用户信息 dict，不存在时返回 None。"""
    row = db.execute(
        "SELECT user_id, email, status, created_at FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def get_user_plan(db, user_id: str) -> str:
    """返回用户当前有效套餐 ID，无订阅时返回 'free'。"""
    row = db.execute(
        """
        SELECT plan_id FROM user_subscriptions
        WHERE user_id = ? AND status = 'active'
          AND (expires_at IS NULL OR expires_at > datetime('now'))
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    return row["plan_id"] if row else DEFAULT_PLAN


def get_or_create_anonymous(db) -> str:
    """
    返回匿名用户 ID（幂等）。
    若 anonymous 用户不存在则自动创建。
    """
    row = db.execute(
        "SELECT user_id FROM users WHERE user_id = ?",
        (ANONYMOUS_USER_ID,),
    ).fetchone()
    if row:
        return ANONYMOUS_USER_ID

    db.execute(
        "INSERT INTO users (user_id, email, status) VALUES (?, NULL, 'active')",
        (ANONYMOUS_USER_ID,),
    )
    _create_wallet(db, ANONYMOUS_USER_ID)
    _create_default_subscription(db, ANONYMOUS_USER_ID)
    db.commit()
    logger.info("[identity] created anonymous user")
    return ANONYMOUS_USER_ID


def set_user_subscription(
    db,
    user_id: str,
    plan_id: str,
    expires_at: str,
    credits_quota: int,
) -> None:
    """
    设置（或更新）用户订阅套餐。
    将旧的 active 订阅标记为 cancelled，插入新订阅。
    同步更新 wallet.subscription_credits。
    """
    import datetime as _dt

    db.execute(
        "UPDATE user_subscriptions SET status = 'cancelled' WHERE user_id = ? AND status = 'active'",
        (user_id,),
    )
    sub_id = str(uuid.uuid4())
    now = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        """
        INSERT INTO user_subscriptions
            (sub_id, user_id, plan_id, status, started_at, expires_at, credits_quota)
        VALUES (?, ?, ?, 'active', ?, ?, ?)
        """,
        (sub_id, user_id, plan_id, now, expires_at, credits_quota),
    )
    # 同步 wallet 的订阅 credits
    db.execute(
        """
        UPDATE wallets
        SET subscription_credits    = ?,
            subscription_expires_at = ?,
            updated_at              = ?
        WHERE user_id = ?
        """,
        (credits_quota, expires_at, now, user_id),
    )
    db.commit()
    logger.info(f"[identity] user {user_id} → plan {plan_id} (credits={credits_quota})")


# ── 内部辅助 ──────────────────────────────────────────────────────────────────

def _create_wallet(db, user_id: str) -> None:
    """创建用户 wallet（仅内部调用）。"""
    wallet_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO wallets (wallet_id, user_id) VALUES (?, ?)",
        (wallet_id, user_id),
    )


def _create_default_subscription(db, user_id: str) -> None:
    """创建默认 free 订阅（仅内部调用）。"""
    import datetime as _dt
    sub_id = str(uuid.uuid4())
    now = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        """
        INSERT INTO user_subscriptions
            (sub_id, user_id, plan_id, status, started_at, credits_quota)
        VALUES (?, ?, 'free', 'active', ?, 0)
        """,
        (sub_id, user_id, now),
    )
