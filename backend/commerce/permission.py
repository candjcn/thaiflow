"""
Permission Engine：权限检查与管理。

核心原则（VISION.md 原则四）：
  权限由能力定义，不由身份定义。
  不能有 if VIP / if plan == "pro" 散落在代码里。
  权限是命名的能力集合，由本模块统一管理。

权限来源（优先级从高到低）：
  1. permission_grants 表手动授权（管理员操作，可超越套餐）
  2. plan_definitions.features_json 中 permissions 字段（套餐权限）

公开函数：
  check(db, user_id, permission) → bool
  check_all(db, user_id, permissions) → dict[str, bool]
  get_user_permissions(db, user_id) → set[str]
  grant(db, user_id, permission, expires_at=None) → None
  revoke(db, user_id, permission) → None
"""
import json
import uuid
import datetime
from config import get_logger
from commerce.identity import get_user_plan

logger = get_logger(__name__)

# 全部已知权限枚举（Permission Engine 管理的命名能力集合）
ALL_PERMISSIONS: frozenset = frozenset({
    "CanTranscribe",
    "CanTranslate",
    "CanTTS",
    "CanTTSContent",
    "CanPronunciationAssess",
    "CanRomanize",
    "CanWordDefine",
    "CanExport",
    "CanOCR",
    "CanShadowing",
    "CanImageGen",
    "CanUseStandardQuality",
    "CanUsePremiumQuality",
    "CanProcessLongVideo",   # > 5 min
})


def check(db, user_id: str, permission: str) -> bool:
    """
    检查用户是否拥有指定权限。

    先查手动授权（未过期），再查套餐权限。
    套餐为 pro/enterprise 且 permissions=["ALL"] 时返回 True。
    """
    # 1. 手动授权（优先级最高）
    row = db.execute(
        """
        SELECT grant_id FROM permission_grants
        WHERE user_id = ? AND permission = ?
          AND (expires_at IS NULL OR expires_at > datetime('now'))
        """,
        (user_id, permission),
    ).fetchone()
    if row:
        return True

    # 2. 套餐权限
    return permission in _get_plan_permissions(db, get_user_plan(db, user_id))


def check_all(db, user_id: str, permissions: list) -> dict:
    """
    批量检查多个权限，返回 {permission: bool} dict。
    比逐一调用 check() 更高效（plan permissions 只查一次）。
    """
    # 一次性拿手动授权
    rows = db.execute(
        """
        SELECT permission FROM permission_grants
        WHERE user_id = ?
          AND (expires_at IS NULL OR expires_at > datetime('now'))
        """,
        (user_id,),
    ).fetchall()
    granted = {r["permission"] for r in rows}

    # 套餐权限
    plan_perms = _get_plan_permissions(db, get_user_plan(db, user_id))

    return {
        p: (p in granted or p in plan_perms)
        for p in permissions
    }


def get_user_permissions(db, user_id: str) -> set:
    """返回用户当前拥有的所有权限（手动授权 ∪ 套餐权限）。"""
    rows = db.execute(
        """
        SELECT permission FROM permission_grants
        WHERE user_id = ?
          AND (expires_at IS NULL OR expires_at > datetime('now'))
        """,
        (user_id,),
    ).fetchall()
    granted = {r["permission"] for r in rows}
    plan_perms = _get_plan_permissions(db, get_user_plan(db, user_id))
    return granted | plan_perms


def grant(db, user_id: str, permission: str, expires_at: str = None) -> None:
    """
    手动授予权限（可超越套餐限制）。
    同一 user_id + permission 已存在时先删除旧记录再插入（覆盖语义）。

    Args:
        expires_at: 过期时间（"YYYY-MM-DD HH:MM:SS"），None = 永不过期
    """
    if permission not in ALL_PERMISSIONS:
        raise ValueError(f"unknown permission: {permission}")

    # 删除旧的同名授权（覆盖）
    db.execute(
        "DELETE FROM permission_grants WHERE user_id = ? AND permission = ?",
        (user_id, permission),
    )
    grant_id = str(uuid.uuid4())
    db.execute(
        """
        INSERT INTO permission_grants (grant_id, user_id, permission, granted_by, expires_at)
        VALUES (?, ?, ?, 'admin', ?)
        """,
        (grant_id, user_id, permission, expires_at),
    )
    db.commit()
    logger.info(f"[permission] granted {permission} to {user_id} (expires={expires_at})")


def revoke(db, user_id: str, permission: str) -> None:
    """
    撤销手动授权。
    若该权限来自套餐，撤销后仍由套餐覆盖（check 会返回 True）。
    若该权限不在套餐中，撤销后 check 返回 False。
    """
    db.execute(
        "DELETE FROM permission_grants WHERE user_id = ? AND permission = ?",
        (user_id, permission),
    )
    db.commit()
    logger.info(f"[permission] revoked manual grant {permission} from {user_id}")


# ── 内部：套餐权限解析 ────────────────────────────────────────────────────────

def _get_plan_permissions(db, plan_id: str) -> set:
    """
    从 plan_definitions.features_json 读取套餐权限集合。
    features_json.permissions = ["ALL"] 表示拥有全部权限。
    """
    row = db.execute(
        "SELECT features_json FROM plan_definitions WHERE plan_id = ?",
        (plan_id,),
    ).fetchone()
    if not row or not row["features_json"]:
        logger.debug(f"[permission] plan {plan_id} not found, no permissions")
        return set()

    try:
        features = json.loads(row["features_json"])
    except Exception:
        logger.warning(f"[permission] plan {plan_id} features_json invalid")
        return set()

    perms = features.get("permissions", [])
    if perms == ["ALL"] or "ALL" in perms:
        return set(ALL_PERMISSIONS)

    return set(perms) & ALL_PERMISSIONS   # 只返回已知权限
