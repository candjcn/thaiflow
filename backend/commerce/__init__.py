"""
ReelSpeak Commerce Platform

公开导出：
  get_db()    → 当前线程的 SQLite 连接（懒加载）
  close_db()  → 关闭连接（Flask teardown 用）

完整调用链：Reserve → Provider → UsageLog → Wallet.Confirm
详见 ARCHITECTURE.md Section 5.2
"""
from commerce.db import get_db, close_db, init_db

__all__ = ["get_db", "close_db", "init_db"]
