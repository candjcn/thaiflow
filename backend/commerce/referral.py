"""
邀请返利模块

公开接口：
  get_ref_code(user_id)                       → str   8位邀请码（从user_id哈希派生）
  resolve_ref_code(db, code)                  → str | None  邀请码 → referrer user_id
  bind_referral(db, referred_id, ref_code)    → bool  绑定邀请关系（幂等，已绑定返回False）
  try_activate_referral(db, referred_id)      → bool  首次AI使用时激活，发放双方奖励
  get_referral_stats(db, user_id)             → dict  用户邀请统计（Profile页用）
  get_admin_stats(db)                         → dict  全局邀请统计（Admin用）

奖励规则：
  - 注册奖励：邀请人+100 Credits，被邀请人+100 Credits（首次AI功能触发）
  - 购买返利：被邀请人充值时，邀请人得10%（在wallet.add_credits后调用on_purchase）
  - 防滥用：激活门槛（注册即得→首次AI使用才得）
"""
import hashlib
import base64
import re
import datetime

from config import settings, get_logger
from commerce.wallet import add_credits, get_or_create_wallet

logger = get_logger(__name__)

REFERRAL_SIGNUP_CREDITS = settings.REFERRAL_GIFT_CREDITS
CASHBACK_RATE           = settings.REFERRAL_CASHBACK_RATE


def _gift_expires_at() -> str:
    return (datetime.datetime.utcnow() + datetime.timedelta(
        days=settings.GIFT_CREDITS_DAYS
    )).strftime("%Y-%m-%d %H:%M:%S")


# ── 邀请码生成 ────────────────────────────────────────────────────────────────

def get_ref_code(user_id: str) -> str:
    """从 user_id 生成固定 8 位邀请码（base62字符集，不存储，可随时重新生成）。"""
    digest = hashlib.sha256(f"ref:{user_id}:reelspeak".encode()).digest()
    b64 = base64.b64encode(digest).decode()
    code = re.sub(r'[^A-Za-z0-9]', '', b64)[:8].upper()
    return code


def resolve_ref_code(db, code: str) -> str | None:
    """邀请码反查 user_id：遍历 users 表匹配（码是从 user_id 派生的，无需单独存储）。"""
    code = code.strip().upper()
    if not code or len(code) != 8:
        return None
    # 在 users 中扫描，数据量小时性能可接受；用户量大时可加 ref_code 列+索引
    rows = db.execute("SELECT user_id FROM users").fetchall()
    for row in rows:
        if get_ref_code(row["user_id"]) == code:
            return row["user_id"]
    return None


# ── 绑定邀请关系 ───────────────────────────────────────────────────────────────

def bind_referral(db, referred_id: str, ref_code: str) -> bool:
    """
    将被邀请人与邀请码绑定。幂等：已有绑定则返回 False。

    防滥用检查：
    - 不能绑定自己的邀请码
    - 每个被邀请人只能绑定一次（referred_id UNIQUE）
    - 邀请码必须对应有效用户
    """
    ref_code = (ref_code or "").strip().upper()
    if not ref_code:
        return False

    # 检查是否已绑定
    existing = db.execute(
        "SELECT id FROM referrals WHERE referred_id = ?", (referred_id,)
    ).fetchone()
    if existing:
        logger.debug(f"[referral] {referred_id} already bound, skip")
        return False

    # 解析邀请码 → referrer_id
    referrer_id = resolve_ref_code(db, ref_code)
    if not referrer_id:
        logger.info(f"[referral] invalid ref_code={ref_code!r}, skip")
        return False

    # 防止自我邀请
    if referrer_id == referred_id:
        logger.info(f"[referral] self-referral blocked for {referred_id}")
        return False

    try:
        db.execute(
            """INSERT OR IGNORE INTO referrals
               (referrer_id, referred_id, ref_code, status, created_at)
               VALUES (?, ?, ?, 'pending', datetime('now'))""",
            (referrer_id, referred_id, ref_code),
        )
        db.commit()
    except Exception as e:
        logger.info(f"[referral] bind failed for referred={referred_id}: {e}")
        return False
    logger.info(f"[referral] bound: referrer={referrer_id} referred={referred_id}")
    return True


# ── 激活（首次AI功能使用） ────────────────────────────────────────────────────

def try_activate_referral(db, referred_id: str) -> bool:
    """
    被邀请人首次使用AI功能时调用此函数。
    - 若有待激活的邀请关系，发放双方各100 Credits，标记已激活。
    - 已激活或无邀请关系则静默返回 False。
    """
    row = db.execute(
        """SELECT id, referrer_id FROM referrals
           WHERE referred_id = ? AND status = 'pending'""",
        (referred_id,),
    ).fetchone()
    if not row:
        return False

    ref_id      = row["id"]
    referrer_id = row["referrer_id"]
    now         = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    try:
        # 确保双方 wallet 存在
        get_or_create_wallet(db, referrer_id)
        get_or_create_wallet(db, referred_id)

        # 发放邀请人奖励
        expires_at = _gift_expires_at()
        add_credits(db, referrer_id, REFERRAL_SIGNUP_CREDITS,
                    credit_type="gift", source="referral_register", expires_at=expires_at)
        # 发放被邀请人欢迎奖励
        add_credits(db, referred_id, REFERRAL_SIGNUP_CREDITS,
                    credit_type="gift", source="referral_welcome", expires_at=expires_at)

        # 更新状态
        db.execute(
            """UPDATE referrals
               SET status='activated', activated_at=?,
                   referrer_rewarded=1, referred_rewarded=1
               WHERE id=?""",
            (now, ref_id),
        )
        db.commit()
        logger.info(f"[referral] activated: referrer={referrer_id} referred={referred_id}, "
                    f"each +{REFERRAL_SIGNUP_CREDITS} credits")
        return True
    except Exception as e:
        logger.error(f"[referral] activation error: {e}", exc_info=True)
        return False


# ── 购买返利 ───────────────────────────────────────────────────────────────────

def on_purchase(db, buyer_id: str, credits_purchased: int) -> None:
    """
    被邀请人充值后调用，给邀请人发放10%返利。
    仅适用于直接充值（paid credits），不适用于赠送积分。
    """
    row = db.execute(
        "SELECT referrer_id FROM referrals WHERE referred_id = ? AND status = 'activated'",
        (buyer_id,),
    ).fetchone()
    if not row:
        return

    referrer_id = row["referrer_id"]
    cashback = max(1, int(credits_purchased * CASHBACK_RATE))

    try:
        get_or_create_wallet(db, referrer_id)
        add_credits(db, referrer_id, cashback,
                    credit_type="gift", source="referral_cashback",
                    expires_at=_gift_expires_at())
        logger.info(f"[referral] cashback: buyer={buyer_id} referrer={referrer_id} "
                    f"purchase={credits_purchased} cashback={cashback}")
    except Exception as e:
        logger.error(f"[referral] cashback error: {e}", exc_info=True)


# ── 统计查询 ───────────────────────────────────────────────────────────────────

def get_referral_stats(db, user_id: str) -> dict:
    """返回用户邀请统计（Profile页展示用）。"""
    rows = db.execute(
        """SELECT status, referrer_rewarded FROM referrals WHERE referrer_id = ?""",
        (user_id,),
    ).fetchall()

    total     = len(rows)
    activated = sum(1 for r in rows if r["status"] == "activated")

    # 统计从 wallet_transactions 拿到的返利总额
    cashback_row = db.execute(
        """SELECT COALESCE(SUM(amount), 0) AS total
           FROM wallet_transactions wt
           JOIN wallets w ON wt.wallet_id = w.wallet_id
           WHERE w.user_id = ?
             AND wt.note IN ('referral_register cashback', 'referral_cashback cashback')
             AND wt.tx_type = 'add'""",
        (user_id,),
    ).fetchone()
    # 改用 note LIKE 匹配更宽松
    credits_row = db.execute(
        """SELECT COALESCE(SUM(amount), 0) AS total
           FROM wallet_transactions wt
           JOIN wallets w ON wt.wallet_id = w.wallet_id
           WHERE w.user_id = ? AND wt.tx_type = 'add'
             AND wt.note LIKE '%referral%'""",
        (user_id,),
    ).fetchone()

    ref_code = get_ref_code(user_id)
    return {
        "ref_code":         ref_code,
        "total_invited":    total,
        "total_activated":  activated,
        "credits_earned":   credits_row["total"] if credits_row else 0,
    }


def get_admin_stats(db) -> dict:
    """全局邀请统计，供 Admin API 使用。"""
    summary = db.execute(
        """SELECT
             COUNT(*)                           AS total_referrals,
             SUM(CASE WHEN status='activated' THEN 1 ELSE 0 END) AS activated,
             SUM(CASE WHEN status='pending'   THEN 1 ELSE 0 END) AS pending
           FROM referrals"""
    ).fetchone()

    credits_summary = db.execute(
        """SELECT
             COALESCE(SUM(CASE WHEN wt.note LIKE '%referral_register%' AND w.user_id IN
                              (SELECT referrer_id FROM referrals) THEN wt.amount ELSE 0 END), 0) AS referrer_credits,
             COALESCE(SUM(CASE WHEN wt.note LIKE '%referral_welcome%' THEN wt.amount ELSE 0 END), 0) AS referred_credits,
             COALESCE(SUM(CASE WHEN wt.note LIKE '%referral_cashback%' THEN wt.amount ELSE 0 END), 0) AS cashback_credits
           FROM wallet_transactions wt
           JOIN wallets w ON wt.wallet_id = w.wallet_id
           WHERE wt.tx_type = 'add' AND wt.note LIKE '%referral%'"""
    ).fetchone()

    # Top referrers
    top = db.execute(
        """SELECT r.referrer_id,
                  u.email,
                  COUNT(*) AS invited,
                  SUM(CASE WHEN r.status='activated' THEN 1 ELSE 0 END) AS act
           FROM referrals r
           LEFT JOIN users u ON u.user_id = r.referrer_id
           GROUP BY r.referrer_id
           ORDER BY invited DESC
           LIMIT 10"""
    ).fetchall()

    top_list = []
    for t in top:
        cred_row = db.execute(
            """SELECT COALESCE(SUM(wt.amount), 0) AS total
               FROM wallet_transactions wt
               JOIN wallets w ON wt.wallet_id = w.wallet_id
               WHERE w.user_id = ? AND wt.tx_type='add' AND wt.note LIKE '%referral%'""",
            (t["referrer_id"],),
        ).fetchone()
        top_list.append({
            "user_id":       t["referrer_id"],
            "email":         t["email"],
            "invited":       t["invited"],
            "activated":     t["act"],
            "credits_earned": cred_row["total"] if cred_row else 0,
        })

    # Recent referrals
    recent_rows = db.execute(
        """SELECT r.status, r.created_at, r.activated_at,
                  u1.email AS referrer_email, u2.email AS referred_email
           FROM referrals r
           LEFT JOIN users u1 ON u1.user_id = r.referrer_id
           LEFT JOIN users u2 ON u2.user_id = r.referred_id
           ORDER BY r.created_at DESC LIMIT 20"""
    ).fetchall()

    recent = [dict(row) for row in recent_rows]

    return {
        "summary": {
            "total_referrals":               summary["total_referrals"] or 0,
            "activated":                     summary["activated"] or 0,
            "pending":                       summary["pending"] or 0,
            "total_referrer_credits_issued": credits_summary["referrer_credits"] or 0,
            "total_referred_credits_issued": credits_summary["referred_credits"] or 0,
            "total_cashback_issued":         credits_summary["cashback_credits"] or 0,
        },
        "top_referrers": top_list,
        "recent":        recent,
    }
