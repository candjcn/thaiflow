"""账号级单词学习卡片的持久化操作。"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone


def source_key(word: str, language: str, meaning: str) -> str:
    # 同一语言的同一单词只保留一张卡；不同视频上下文不重复收藏。
    raw = f"{language.strip().lower()}|{word.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _row(row) -> dict | None:
    return dict(row) if row else None


def get(db, user_id: str, card_id: str) -> dict | None:
    return _row(db.execute(
        "SELECT * FROM word_cards WHERE user_id = ? AND card_id = ?",
        (user_id, card_id),
    ).fetchone())


def find_existing(db, user_id: str, key: str) -> dict | None:
    return _row(db.execute(
        "SELECT * FROM word_cards WHERE user_id = ? AND source_key = ?",
        (user_id, key),
    ).fetchone())


def create(db, user_id: str, *, key: str, word: str, meaning: str,
           part_of_speech: str = "", language: str = "", context: str = "",
           audio_url: str = "", audio_key: str = "", source_video: str = "") -> dict:
    existing = find_existing(db, user_id, key)
    if existing:
        return existing
    card_id = str(uuid.uuid4())
    db.execute(
        """
        INSERT INTO word_cards (
            card_id, user_id, source_key, word, meaning, part_of_speech,
            language, context, audio_url, audio_key, source_video
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (card_id, user_id, key, word.strip(), meaning.strip(), part_of_speech.strip(),
         language.strip(), context.strip(), audio_url, audio_key, source_video.strip()),
    )
    db.commit()
    return get(db, user_id, card_id)


def list_for_user(db, user_id: str, limit: int = 100, due_only: bool = False) -> list[dict]:
    safe_limit = min(max(int(limit), 1), 500)
    due_sql = "AND (next_review_at IS NULL OR next_review_at <= datetime('now'))" if due_only else ""
    order_sql = (
        "CASE WHEN next_review_at IS NULL THEN 0 ELSE 1 END, next_review_at ASC, created_at ASC"
        if due_only else "created_at DESC"
    )
    rows = db.execute(
        f"SELECT * FROM word_cards WHERE user_id = ? {due_sql} ORDER BY {order_sql}, card_id ASC LIMIT ?",
        (user_id, safe_limit),
    ).fetchall()
    return [dict(row) for row in rows]


def due_count(db, user_id: str) -> int:
    row = db.execute(
        """SELECT COUNT(*) AS count FROM word_cards WHERE user_id = ?
           AND (next_review_at IS NULL OR next_review_at <= datetime('now'))""",
        (user_id,),
    ).fetchone()
    return int(row["count"] if row else 0)


def review(db, user_id: str, card_id: str, result: str) -> dict | None:
    card = get(db, user_id, card_id)
    if not card:
        return None
    if result not in {"practice", "mastered"}:
        raise ValueError("无效的复习结果")
    count = int(card.get("review_count") or 0) + 1
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    if result == "practice":
        next_review, status = now + timedelta(minutes=10), "practicing"
    else:
        intervals = (1, 3, 7, 14, 30)
        index = 0 if card.get("status") != "mastered" else min(count - 1, len(intervals) - 1)
        next_review, status = now + timedelta(days=intervals[index]), "mastered"
    db.execute(
        """UPDATE word_cards SET status = ?, review_count = ?, last_reviewed_at = ?,
           next_review_at = ?, updated_at = datetime('now') WHERE user_id = ? AND card_id = ?""",
        (status, count, now.strftime("%Y-%m-%d %H:%M:%S"),
         next_review.strftime("%Y-%m-%d %H:%M:%S"), user_id, card_id),
    )
    db.commit()
    return get(db, user_id, card_id)


def delete(db, user_id: str, card_id: str) -> dict | None:
    card = get(db, user_id, card_id)
    if not card:
        return None
    db.execute("DELETE FROM word_cards WHERE user_id = ? AND card_id = ?", (user_id, card_id))
    db.commit()
    return card
