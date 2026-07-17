"""
Google OAuth 2.0 + Session 管理

公开接口：
  google_login_url(state)                            → str
  google_exchange_code(code)                         → dict  {sub,email,name,picture}
  upsert_user(db, provider, uid, email, name, pic)   → str   user_id
  create_session(db, user_id, user_agent)            → str   token
  validate_session(db, token)                        → dict | None
  logout(db, token)                                  → None
  get_current_user(db, request)                      → dict | None

会话方案：HttpOnly Cookie "session"，30 天有效，随机 token 存 user_sessions 表。
"""
import datetime
import json
import secrets
import urllib.parse
import urllib.request
import uuid

from config import settings, get_logger

logger = get_logger(__name__)

_GOOGLE_AUTH_URL     = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL    = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

SESSION_DAYS  = 30
COOKIE_NAME   = "session"


# ── OAuth 流程 ────────────────────────────────────────────────────────────────

def google_login_url(state: str) -> str:
    """构造 Google 授权页 URL（带 state 防 CSRF）。"""
    params = {
        "client_id":     settings.GOOGLE_CLIENT_ID,
        "redirect_uri":  settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope":         "openid email profile",
        "state":         state,
        "access_type":   "online",
        "prompt":        "select_account",
    }
    return _GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params)


def google_exchange_code(code: str) -> dict:
    """
    用 authorization code 换取 Google 用户信息。

    Returns:
        {"sub": str, "email": str, "name": str, "picture": str}

    Raises:
        ValueError: Google 返回错误或字段缺失
    """
    # 1. code → access_token
    payload = urllib.parse.urlencode({
        "code":          code,
        "client_id":     settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri":  settings.GOOGLE_REDIRECT_URI,
        "grant_type":    "authorization_code",
    }).encode()

    req = urllib.request.Request(
        _GOOGLE_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        token_data = json.loads(resp.read())

    access_token = token_data.get("access_token")
    if not access_token:
        raise ValueError(f"Google token exchange failed: {token_data.get('error')}")

    # 2. access_token → userinfo
    req2 = urllib.request.Request(
        _GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urllib.request.urlopen(req2, timeout=15) as resp2:
        info = json.loads(resp2.read())

    if "sub" not in info:
        raise ValueError(f"Google userinfo missing 'sub': {info}")

    return {
        "sub":     info["sub"],
        "email":   info.get("email", ""),
        "name":    info.get("name", ""),
        "picture": info.get("picture", ""),
    }


# ── 用户 Upsert ───────────────────────────────────────────────────────────────

def upsert_user(
    db,
    provider: str,
    provider_uid: str,
    email: str,
    name: str,
    picture_url: str = None,
) -> str:
    """
    找到或创建用户，返回 user_id。
    新用户自动创建 Free 月度额度。
    """
    # 已有 identity → 更新信息，直接返回
    row = db.execute(
        "SELECT user_id FROM user_identities WHERE provider = ? AND provider_uid = ?",
        (provider, provider_uid),
    ).fetchone()

    if row:
        db.execute(
            """
            UPDATE user_identities SET name = ?, picture_url = ?
            WHERE provider = ? AND provider_uid = ?
            """,
            (name, picture_url, provider, provider_uid),
        )
        db.commit()
        logger.debug(f"[auth] existing user {row['user_id']} via {provider}")
        return row["user_id"]

    # 新用户：创建 user + identity + Free 订阅
    from commerce.identity import create_user
    user_id = create_user(db, email=email or None)

    identity_id = str(uuid.uuid4())
    db.execute(
        """
        INSERT INTO user_identities
            (identity_id, user_id, provider, provider_uid, email, name, picture_url)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (identity_id, user_id, provider, provider_uid, email, name, picture_url),
    )
    db.commit()

    logger.info(f"[auth] new user created: {user_id} ({email}) via {provider}")
    return user_id


# ── Session 管理 ──────────────────────────────────────────────────────────────

def create_session(db, user_id: str, user_agent: str = None) -> str:
    """创建登录 Session，返回 token（存入 Cookie）。"""
    token      = secrets.token_urlsafe(32)
    expires_at = (
        datetime.datetime.utcnow() + datetime.timedelta(days=SESSION_DAYS)
    ).strftime("%Y-%m-%d %H:%M:%S")

    db.execute(
        """
        INSERT INTO user_sessions (token, user_id, expires_at, user_agent)
        VALUES (?, ?, ?, ?)
        """,
        (token, user_id, expires_at, user_agent),
    )
    db.commit()
    logger.debug(f"[auth] session created for {user_id}")
    return token


def validate_session(db, token: str) -> dict | None:
    """
    验证 token 并返回用户信息 dict。
    同时更新 last_used_at（best-effort，不影响主逻辑）。

    Returns:
        {"user_id", "email", "name", "picture_url"} 或 None
    """
    row = db.execute(
        """
        SELECT s.user_id, i.email, i.name, i.picture_url
        FROM user_sessions s
        LEFT JOIN user_identities i ON i.user_id = s.user_id
        WHERE s.token = ?
          AND s.expires_at > datetime('now')
        ORDER BY i.created_at DESC
        LIMIT 1
        """,
        (token,),
    ).fetchone()

    if not row:
        return None

    try:
        now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        db.execute(
            "UPDATE user_sessions SET last_used_at = ? WHERE token = ?",
            (now, token),
        )
        db.commit()
    except Exception:
        pass

    return {
        "user_id":     row["user_id"],
        "email":       row["email"] or "",
        "name":        row["name"] or "",
        "picture_url": row["picture_url"] or "",
    }


def logout(db, token: str) -> None:
    """删除 Session（登出）。"""
    db.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
    db.commit()
    logger.debug(f"[auth] session deleted")


def get_current_user(db, request) -> dict | None:
    """从 Flask request Cookie 中解析并验证当前用户，未登录返回 None。"""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return validate_session(db, token)
