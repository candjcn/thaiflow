"""
Commerce 数据库初始化与连接管理。

- init_db(path)  → 创建/连接数据库，执行 schema.sql，返回 Connection
- get_db()       → 返回 app-level 单例连接（供 Flask 路由使用）
- close_db()     → 关闭连接（Flask teardown 时调用）

SQLite 并发注意：
- WAL 模式开启，支持多读单写
- foreign_keys 强制开启
- 事务由调用方控制（wallet 乐观锁需要显式 BEGIN/COMMIT）
"""
import sqlite3
import threading
from pathlib import Path

from config import get_logger

logger = get_logger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# app-level 连接（线程本地，避免跨线程共享）
_local = threading.local()


def init_db(path: str = ":memory:") -> sqlite3.Connection:
    """
    初始化数据库连接并执行 schema。

    Args:
        path: 数据库文件路径，默认 ":memory:"（测试用）。
              生产环境传入 settings.COMMERCE_DB_PATH。

    Returns:
        配置好的 sqlite3.Connection（Row factory = dict-like）
    """
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")   # 等待锁最多 5 秒

    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema_sql)

    # ── 迁移：为旧版 DB 添加新列（CREATE TABLE IF NOT EXISTS 不会自动加列）
    for _migration in [
        "ALTER TABLE wallets ADD COLUMN gift_expires_at TEXT",
    ]:
        try:
            conn.execute(_migration)
        except Exception:
            pass   # 列已存在，跳过

    conn.commit()

    logger.info(f"[commerce.db] initialized: {path}")
    return conn


def get_db() -> sqlite3.Connection:
    """
    返回当前线程的 app-level 数据库连接。
    首次调用时自动初始化（懒加载）。

    在 Flask 应用中，由 commerce/__init__.py 在 app startup 设置
    DB_PATH，并在 teardown 时调用 close_db()。
    """
    if not hasattr(_local, "conn") or _local.conn is None:
        from config import settings
        path = getattr(settings, "COMMERCE_DB_PATH", ":memory:")
        _local.conn = init_db(path)
    return _local.conn


def close_db() -> None:
    """关闭当前线程的连接（Flask teardown 注册用）。"""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None
