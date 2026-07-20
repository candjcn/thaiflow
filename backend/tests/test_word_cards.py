"""账号级单词学习卡片 API 测试。"""
import io
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

for _mod in ("boto3", "botocore", "botocore.config"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

import pytest

from commerce.db import init_db, _local as _db_local
from commerce.seed import run_seed
from commerce.identity import create_user, get_or_create_anonymous
import commerce.auth as auth
from app import app as flask_app


@pytest.fixture
def db():
    conn = init_db(":memory:")
    run_seed(conn)
    get_or_create_anonymous(conn)
    yield conn
    conn.close()


@pytest.fixture
def client(db):
    _db_local.conn = db
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as value:
        yield value
    _db_local.conn = None


def login(client, db):
    user_id = create_user(db, email="word-learner@example.com")
    token = auth.create_session(db, user_id, "pytest")
    client.set_cookie(auth.COOKIE_NAME, token, domain="localhost")
    return user_id


def test_word_cards_require_login(client):
    assert client.get("/api/word-cards").status_code == 401
    assert client.post("/api/word-cards/missing/review", json={"result": "mastered"}).status_code == 401
    assert client.delete("/api/word-cards/missing").status_code == 401


def test_bookmark_word_audio_review_and_delete(client, db, monkeypatch, tmp_path):
    import app as app_module

    login(client, db)
    monkeypatch.setattr(app_module, "VIDEOS_DIR", str(tmp_path))
    monkeypatch.setattr(app_module.subprocess, "run", lambda *_a, **_k: SimpleNamespace(returncode=0, stderr=""))
    monkeypatch.setattr(app_module, "upload_audio", lambda _path, key: f"https://audio.example/{key}")
    deleted_keys = []
    monkeypatch.setattr(app_module, "delete_audio", lambda key: deleted_keys.append(key))
    form = {
        "audio": (io.BytesIO(b"fake wav"), "word.wav"),
        "word": "competitive", "meaning": "竞争激烈的", "part_of_speech": "adj.",
        "language": "en", "context": "It is so competitive.", "source_video": "lesson.mp4",
        "audio_start": "1.5", "audio_end": "2.2", "audio_duration": "3.7",
    }
    created = client.post("/api/bookmark-word-audio", data=form, content_type="multipart/form-data")
    assert created.status_code == 200
    card = created.get_json()["card"]
    assert card["word"] == "competitive"
    assert client.get("/api/word-cards").get_json()["due_count"] == 1

    monkeypatch.setattr(app_module, "get_audio", lambda key, byte_range=None: {
        "Body": io.BytesIO(b"word-mp3"), "ContentType": "audio/mpeg",
    })
    audio = client.get(f"/api/word-cards/{card['card_id']}/audio")
    assert audio.status_code == 200
    assert audio.data == b"word-mp3"
    assert audio.headers["Content-Type"] == "audio/mpeg"

    trimmed = client.patch(
        f"/api/word-cards/{card['card_id']}/audio-range",
        json={"start": 1.35, "end": 2.45},
    )
    assert trimmed.status_code == 200
    assert trimmed.get_json()["card"]["audio_start"] == 1.35
    assert trimmed.get_json()["card"]["audio_end"] == 2.45
    invalid_trim = client.patch(
        f"/api/word-cards/{card['card_id']}/audio-range",
        json={"start": 2.0, "end": 4.0},
    )
    assert invalid_trim.status_code == 400

    reviewed = client.post(f"/api/word-cards/{card['card_id']}/review", json={"result": "mastered"})
    assert reviewed.status_code == 200
    assert reviewed.get_json()["card"]["status"] == "mastered"
    assert reviewed.get_json()["due_count"] == 0

    deleted = client.delete(f"/api/word-cards/{card['card_id']}")
    assert deleted.status_code == 200
    assert deleted_keys == [card["audio_key"]]
