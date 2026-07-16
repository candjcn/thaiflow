"""
Wallet 模块：Credits 账本操作。

调用链位置（ARCHITECTURE.md v1.1）：
  Reserve(estimate) → Provider → UsageLog(actual) → Wallet.Confirm

公开函数：
  get_or_create_wallet(db, user_id) → dict
  get_balance(db, user_id) → dict
  reserve(db, user_id, amount) → reservation_id
  confirm(db, reservation_id) → None
  release(db, reservation_id) → None
  add_credits(db, user_id, amount, credit_type, source, expires_at=None) → None
  refund(db, usage_log_id, amount, reason) → None
  get_history(db, user_id, limit=50) → list[dict]

并发安全：
  reserve() 使用乐观锁（wallets.version），失败最多重试 3 次。
  SQLite WAL 模式 + PRAGMA busy_timeout 保证多线程安全。

Credits 消费优先级（VISION.md）：
  subscription_credits → gift_credits → paid_credits
"""
import uuid
import datetime
from config import get_logger

logger = get_logger(__name__)

_MAX_RETRIES = 3


class InsufficientFundsError(Exception):
    """余额不足，无法完成预扣。"""


class WalletNotFoundError(Exception):
    """用户 wallet 不存在。"""


class ReservationNotFoundError(Exception):
    """reservation_id 对应的流水记录不存在。"""


# ── 读取 ──────────────────────────────────────────────────────────────────────

def get_or_create_wallet(db, user_id: str) -> dict:
    """返回 wallet dict，不存在时自动创建。"""
    row = db.execute(
        "SELECT * FROM wallets WHERE user_id = ?", (user_id,)
    ).fetchone()
    if row:
        return dict(row)

    wallet_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO wallets (wallet_id, user_id) VALUES (?, ?)",
        (wallet_id, user_id),
    )
    db.commit()
    return dict(db.execute(
        "SELECT * FROM wallets WHERE user_id = ?", (user_id,)
    ).fetchone())


def get_balance(db, user_id: str) -> dict:
    """
    返回当前余额（不含 reserved 状态的预扣）。

    Returns:
        {subscription: int, gift: int, paid: int, total: int}
    """
    row = db.execute(
        """
        SELECT subscription_credits, gift_credits, paid_credits
        FROM wallets WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()
    if not row:
        raise WalletNotFoundError(f"wallet not found for user {user_id}")

    sub  = row["subscription_credits"]
    gift = row["gift_credits"]
    paid = row["paid_credits"]
    return {
        "subscription": sub,
        "gift":         gift,
        "paid":         paid,
        "total":        sub + gift + paid,
    }


# ── 预扣 ──────────────────────────────────────────────────────────────────────

def reserve(db, user_id: str, amount: int) -> str:
    """
    预扣 amount Credits，返回 reservation_id。

    消费顺序：subscription → gift → paid
    使用乐观锁（version 字段），并发冲突时最多重试 _MAX_RETRIES 次。

    Raises:
        WalletNotFoundError: wallet 不存在
        InsufficientFundsError: 余额不足
    """
    if amount <= 0:
        raise ValueError(f"reserve amount must be > 0, got {amount}")

    for attempt in range(_MAX_RETRIES):
        row = db.execute(
            """
            SELECT wallet_id, subscription_credits, gift_credits, paid_credits, version
            FROM wallets WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        if not row:
            raise WalletNotFoundError(f"wallet not found for user {user_id}")

        sub, gift, paid, ver = (
            row["subscription_credits"],
            row["gift_credits"],
            row["paid_credits"],
            row["version"],
        )
        total = sub + gift + paid
        if total < amount:
            raise InsufficientFundsError(
                f"insufficient credits: need {amount}, have {total}"
            )

        # 按优先级分配扣减量
        sub_deduct  = min(amount, sub)
        remaining   = amount - sub_deduct
        gift_deduct = min(remaining, gift)
        remaining  -= gift_deduct
        paid_deduct = remaining   # 此时 remaining <= paid（已通过总量检查）

        now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        cursor = db.execute(
            """
            UPDATE wallets
            SET subscription_credits = subscription_credits - ?,
                gift_credits         = gift_credits         - ?,
                paid_credits         = paid_credits         - ?,
                version              = version + 1,
                updated_at           = ?
            WHERE user_id = ? AND version = ?
            """,
            (sub_deduct, gift_deduct, paid_deduct, now, user_id, ver),
        )
        db.commit()

        if cursor.rowcount == 1:
            # 乐观锁成功，写流水
            reservation_id = _record_transaction(
                db,
                wallet_id=row["wallet_id"],
                tx_type="reserve",
                amount=-amount,
                credit_type=_primary_credit_type(sub_deduct, gift_deduct, paid_deduct),
                note=f"reserve {amount} credits",
            )
            logger.debug(
                f"[wallet] reserved {amount} for {user_id}, rid={reservation_id}"
            )
            return reservation_id

        # 乐观锁冲突，重试
        logger.debug(f"[wallet] reserve CAS miss (attempt {attempt + 1})")

    raise RuntimeError(
        f"reserve failed after {_MAX_RETRIES} retries (concurrent conflict)"
    )


# ── 确认 / 释放 ───────────────────────────────────────────────────────────────

def confirm(db, reservation_id: str) -> None:
    """
    确认预扣为最终扣款。
    不重新计算 credits——estimate 即为最终扣款额（ARCHITECTURE.md v1.1）。
    将 wallet_transactions 中对应记录的 tx_type 从 'reserve' 改为 'confirm'。
    """
    cursor = db.execute(
        """
        UPDATE wallet_transactions
        SET tx_type = 'confirm'
        WHERE tx_id = ? AND tx_type = 'reserve'
        """,
        (reservation_id,),
    )
    db.commit()
    if cursor.rowcount == 0:
        raise ReservationNotFoundError(
            f"reservation {reservation_id} not found or already confirmed/released"
        )
    logger.debug(f"[wallet] confirmed reservation {reservation_id}")


def release(db, reservation_id: str) -> None:
    """
    AI 调用失败时，释放预扣（全额退还）。
    读取原 reserve 流水的扣款量，按原 credit_type 退回 wallet。
    将 tx_type 改为 'release'。
    """
    row = db.execute(
        """
        SELECT tx_id, wallet_id, amount, credit_type
        FROM wallet_transactions
        WHERE tx_id = ? AND tx_type = 'reserve'
        """,
        (reservation_id,),
    ).fetchone()
    if not row:
        raise ReservationNotFoundError(
            f"reservation {reservation_id} not found or already confirmed/released"
        )

    refund_amount = -row["amount"]   # amount 是负数（扣款），取反得退款量
    credit_type   = row["credit_type"]
    wallet_id     = row["wallet_id"]

    col_map = {
        "subscription": "subscription_credits",
        "gift":         "gift_credits",
        "paid":         "paid_credits",
    }
    col = col_map.get(credit_type, "subscription_credits")

    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        f"""
        UPDATE wallets
        SET {col}    = {col} + ?,
            version  = version + 1,
            updated_at = ?
        WHERE wallet_id = ?
        """,
        (refund_amount, now, wallet_id),
    )
    db.execute(
        "UPDATE wallet_transactions SET tx_type = 'release' WHERE tx_id = ?",
        (reservation_id,),
    )
    _record_transaction(
        db,
        wallet_id=wallet_id,
        tx_type="release",
        amount=refund_amount,
        credit_type=credit_type,
        ref_id=reservation_id,
        note=f"release {refund_amount} credits",
    )
    db.commit()
    logger.debug(f"[wallet] released reservation {reservation_id} (+{refund_amount})")


# ── 充值 / 退款 ───────────────────────────────────────────────────────────────

def add_credits(
    db,
    user_id: str,
    amount: int,
    credit_type: str,
    source: str,
    expires_at: str = None,
) -> None:
    """
    给用户充值。

    Args:
        credit_type: "subscription" / "gift" / "paid"
        source:      说明来源（管理员操作、订单 ID 等）
        expires_at:  仅 gift 类型有意义（格式 "YYYY-MM-DD HH:MM:SS"）
    """
    if credit_type not in ("subscription", "gift", "paid"):
        raise ValueError(f"invalid credit_type: {credit_type}")
    if amount <= 0:
        raise ValueError(f"add_credits amount must be > 0, got {amount}")

    col_map = {
        "subscription": "subscription_credits",
        "gift":         "gift_credits",
        "paid":         "paid_credits",
    }
    col = col_map[credit_type]
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    row = db.execute("SELECT wallet_id FROM wallets WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        raise WalletNotFoundError(f"wallet not found for user {user_id}")

    extra_set = ""
    params: list = [amount, now, user_id]
    if credit_type == "subscription" and expires_at:
        extra_set = ", subscription_expires_at = ?"
        params = [amount, now] + [expires_at] + [user_id]

    db.execute(
        f"""
        UPDATE wallets
        SET {col}      = {col} + ?,
            version    = version + 1,
            updated_at = ?
            {extra_set}
        WHERE user_id = ?
        """,
        params,
    )
    _record_transaction(
        db,
        wallet_id=row["wallet_id"],
        tx_type="add",
        amount=amount,
        credit_type=credit_type,
        note=source,
    )
    db.commit()
    logger.info(f"[wallet] add {amount} {credit_type} credits to {user_id} ({source})")


def refund(db, usage_log_id: str, amount: int, reason: str) -> None:
    """
    退款到 gift_credits（30 天有效）。
    由管理员或对账机制调用。
    """
    if amount <= 0:
        raise ValueError(f"refund amount must be > 0, got {amount}")

    log = db.execute(
        "SELECT user_id FROM usage_logs WHERE log_id = ?", (usage_log_id,)
    ).fetchone()
    if not log:
        raise ValueError(f"usage_log {usage_log_id} not found")

    user_id = log["user_id"]
    row = db.execute("SELECT wallet_id FROM wallets WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        raise WalletNotFoundError(f"wallet not found for user {user_id}")

    now = datetime.datetime.utcnow()
    expires_at = (now + datetime.timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    db.execute(
        """
        UPDATE wallets
        SET gift_credits = gift_credits + ?,
            version      = version + 1,
            updated_at   = ?
        WHERE user_id = ?
        """,
        (amount, now_str, user_id),
    )
    db.execute(
        """
        UPDATE usage_logs
        SET credits_refunded = credits_refunded + ?,
            status           = 'refunded'
        WHERE log_id = ?
        """,
        (amount, usage_log_id),
    )
    _record_transaction(
        db,
        wallet_id=row["wallet_id"],
        tx_type="refund",
        amount=amount,
        credit_type="gift",
        ref_id=usage_log_id,
        note=reason,
    )
    db.commit()
    logger.info(f"[wallet] refund {amount} to {user_id} for log {usage_log_id}")


# ── 查询流水 ──────────────────────────────────────────────────────────────────

def get_history(db, user_id: str, limit: int = 50) -> list:
    """返回用户最近 limit 条 wallet 流水记录。"""
    row = db.execute("SELECT wallet_id FROM wallets WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        return []
    rows = db.execute(
        """
        SELECT tx_id, tx_type, amount, credit_type, ref_id, note, created_at
        FROM wallet_transactions
        WHERE wallet_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (row["wallet_id"], limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ── 内部辅助 ──────────────────────────────────────────────────────────────────

def _record_transaction(
    db,
    wallet_id: str,
    tx_type: str,
    amount: int,
    credit_type: str = None,
    ref_id: str = None,
    note: str = None,
) -> str:
    """写一条 wallet_transactions 流水，返回 tx_id（= reservation_id for reserve）。"""
    tx_id = str(uuid.uuid4())
    db.execute(
        """
        INSERT INTO wallet_transactions
            (tx_id, wallet_id, tx_type, amount, credit_type, ref_id, note)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (tx_id, wallet_id, tx_type, amount, credit_type, ref_id, note),
    )
    return tx_id


def _primary_credit_type(sub: int, gift: int, paid: int) -> str:
    """根据实际扣减量确定主 credit_type（用于流水记录）。"""
    if sub > 0:
        return "subscription"
    if gift > 0:
        return "gift"
    return "paid"
