"""账号级句子学习卡片的持久化操作。"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone


def source_key(source_video: str, start_time: float, end_time: float, original_text: str) -> str:
    raw = f"{source_video.strip()}|{start_time:.3f}|{end_time:.3f}|{original_text.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _to_dict(row) -> dict | None:
    return dict(row) if row else None


def find_existing(db, user_id: str, key: str) -> dict | None:
    return _to_dict(db.execute(
        "SELECT * FROM sentence_cards WHERE user_id = ? AND source_key = ?",
        (user_id, key),
    ).fetchone())


def create(
    db,
    user_id: str,
    *,
    key: str,
    original_text: str,
    translation: str = "",
    romanization: str = "",
    language: str = "",
    audio_url: str,
    audio_key: str,
    source_video: str = "",
    start_time: float = 0,
    end_time: float = 0,
) -> dict:
    existing = find_existing(db, user_id, key)
    if existing:
        return existing
    card_id = str(uuid.uuid4())
    db.execute(
        """
        INSERT INTO sentence_cards (
            card_id, user_id, source_key, original_text, translation,
            romanization, language, audio_url, audio_key, source_video,
            start_time, end_time
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            card_id, user_id, key, original_text.strip(), translation.strip(),
            romanization.strip(), language.strip(), audio_url, audio_key,
            source_video.strip(), start_time, end_time,
        ),
    )
    db.commit()
    return get(db, user_id, card_id)


def get(db, user_id: str, card_id: str) -> dict | None:
    return _to_dict(db.execute(
        "SELECT * FROM sentence_cards WHERE user_id = ? AND card_id = ?",
        (user_id, card_id),
    ).fetchone())


def list_for_user(db, user_id: str, limit: int = 100, due_only: bool = False) -> list[dict]:
    safe_limit = min(max(int(limit), 1), 500)
    if due_only:
        rows = db.execute(
            """
            SELECT * FROM sentence_cards
            WHERE user_id = ?
              AND (next_review_at IS NULL OR next_review_at <= datetime('now'))
            ORDER BY
                CASE WHEN next_review_at IS NULL THEN 0 ELSE 1 END,
                next_review_at ASC,
                created_at ASC,
                card_id ASC
            LIMIT ?
            """,
            (user_id, safe_limit),
        ).fetchall()
    else:
        rows = db.execute(
            """
            SELECT * FROM sentence_cards
            WHERE user_id = ?
            ORDER BY created_at DESC, card_id DESC
            LIMIT ?
            """,
            (user_id, safe_limit),
        ).fetchall()
    return [dict(row) for row in rows]


def due_count(db, user_id: str) -> int:
    row = db.execute(
        """
        SELECT COUNT(*) AS count
        FROM sentence_cards
        WHERE user_id = ?
          AND (next_review_at IS NULL OR next_review_at <= datetime('now'))
        """,
        (user_id,),
    ).fetchone()
    return int(row["count"] if row else 0)


def review(db, user_id: str, card_id: str, result: str) -> dict | None:
    card = get(db, user_id, card_id)
    if not card:
        return None
    if result not in {"practice", "mastered"}:
        raise ValueError("无效的复习结果")

    review_count = int(card.get("review_count") or 0) + 1
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    if result == "practice":
        next_review = now + timedelta(minutes=10)
        status = "practicing"
    else:
        # 简单间隔复习：前五次逐步拉长，之后维持 30 天。
        intervals = (1, 3, 7, 14, 30)
        mastered_index = 0 if card.get("status") != "mastered" else min(review_count - 1, len(intervals) - 1)
        next_review = now + timedelta(days=intervals[mastered_index])
        status = "mastered"

    db.execute(
        """
        UPDATE sentence_cards
        SET status = ?, review_count = ?, last_reviewed_at = ?,
            next_review_at = ?, updated_at = datetime('now')
        WHERE user_id = ? AND card_id = ?
        """,
        (
            status,
            review_count,
            now.strftime("%Y-%m-%d %H:%M:%S"),
            next_review.strftime("%Y-%m-%d %H:%M:%S"),
            user_id,
            card_id,
        ),
    )
    db.commit()
    return get(db, user_id, card_id)


def delete(db, user_id: str, card_id: str) -> dict | None:
    card = get(db, user_id, card_id)
    if not card:
        return None
    db.execute(
        "DELETE FROM sentence_cards WHERE user_id = ? AND card_id = ?",
        (user_id, card_id),
    )
    db.commit()
    return card
