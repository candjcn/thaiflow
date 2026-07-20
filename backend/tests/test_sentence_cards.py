"""账号级句子学习卡片 API 测试。"""
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
    user_id = create_user(db, email="learner@example.com")
    token = auth.create_session(db, user_id, "pytest")
    client.set_cookie(auth.COOKIE_NAME, token, domain="localhost")
    return user_id


def test_sentence_cards_require_login(client):
    assert client.get("/api/sentence-cards").status_code == 401
    assert client.delete("/api/sentence-cards/missing").status_code == 401
    assert client.post("/api/sentence-cards/missing/review", json={"result": "mastered"}).status_code == 401
    response = client.post(
        "/api/bookmark-audio",
        data={"audio": (io.BytesIO(b"wav"), "slice.wav")},
    )
    assert response.status_code == 401


def test_bookmark_list_deduplicate_and_delete(client, db, monkeypatch, tmp_path):
    import app as app_module

    user_id = login(client, db)
    monkeypatch.setattr(app_module, "VIDEOS_DIR", str(tmp_path))
    monkeypatch.setattr(
        app_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stderr=""),
    )
    uploads = []
    deletes = []
    monkeypatch.setattr(
        app_module,
        "upload_audio",
        lambda _path, key: uploads.append(key) or f"https://audio.example/{key}",
    )
    monkeypatch.setattr(app_module, "delete_audio", lambda key: deletes.append(key))

    form = {
        "audio": (io.BytesIO(b"fake wav"), "slice.wav"),
        "text": "สวัสดีครับ",
        "translation": "你好",
        "romanization": "sawatdi khrap",
        "language": "th",
        "source": "lesson.mp4",
        "start": "1.0",
        "end": "3.0",
    }
    created = client.post("/api/bookmark-audio", data=form, content_type="multipart/form-data")
    assert created.status_code == 200
    card = created.get_json()["card"]
    assert card["user_id"] == user_id
    assert card["original_text"] == "สวัสดีครับ"
    assert len(uploads) == 1

    duplicate_form = dict(form)
    duplicate_form["audio"] = (io.BytesIO(b"fake wav 2"), "slice.wav")
    duplicate = client.post(
        "/api/bookmark-audio", data=duplicate_form, content_type="multipart/form-data"
    )
    assert duplicate.status_code == 200
    assert duplicate.get_json()["already_saved"] is True
    assert len(uploads) == 1

    listed = client.get("/api/sentence-cards").get_json()["cards"]
    assert [item["card_id"] for item in listed] == [card["card_id"]]

    deleted = client.delete(f"/api/sentence-cards/{card['card_id']}")
    assert deleted.status_code == 200
    assert deletes == [card["audio_key"]]
    assert client.get("/api/sentence-cards").get_json()["cards"] == []


def test_user_cannot_delete_another_users_card(client, db):
    from commerce import sentence_cards

    owner = create_user(db, email="owner@example.com")
    other = login(client, db)
    card = sentence_cards.create(
        db,
        owner,
        key="owner-key",
        original_text="private sentence",
        audio_url="https://audio.example/private.mp3",
        audio_key="sentences/private.mp3",
    )
    assert other != owner
    assert client.delete(f"/api/sentence-cards/{card['card_id']}").status_code == 404


def test_review_schedule_and_due_count(client, db):
    from commerce import sentence_cards

    user_id = login(client, db)
    first = sentence_cards.create(
        db,
        user_id,
        key="first",
        original_text="ฟังอีกครั้ง",
        audio_url="https://audio.example/first.mp3",
        audio_key="sentences/first.mp3",
    )
    second = sentence_cards.create(
        db,
        user_id,
        key="second",
        original_text="เข้าใจแล้ว",
        audio_url="https://audio.example/second.mp3",
        audio_key="sentences/second.mp3",
    )

    initial = client.get("/api/sentence-cards?due=1").get_json()
    assert initial["due_count"] == 2
    assert {card["card_id"] for card in initial["cards"]} == {first["card_id"], second["card_id"]}

    practice = client.post(
        f"/api/sentence-cards/{first['card_id']}/review",
        json={"result": "practice"},
    )
    assert practice.status_code == 200
    assert practice.get_json()["card"]["status"] == "practicing"
    assert practice.get_json()["card"]["review_count"] == 1
    assert practice.get_json()["due_count"] == 1

    mastered = client.post(
        f"/api/sentence-cards/{second['card_id']}/review",
        json={"result": "mastered"},
    )
    assert mastered.status_code == 200
    assert mastered.get_json()["card"]["status"] == "mastered"
    assert mastered.get_json()["due_count"] == 0
    assert client.get("/api/sentence-cards?due=1").get_json()["cards"] == []

    invalid = client.post(
        f"/api/sentence-cards/{second['card_id']}/review",
        json={"result": "unknown"},
    )
    assert invalid.status_code == 400
