"""
Phase 4 测试：Admin API + 用户余额 API
pytest backend/tests/test_phase4.py
"""
import json
import sys
from unittest.mock import MagicMock
from types import SimpleNamespace

# ── Mock external deps that may not be installed in test env ─────────────────
# boto3/botocore are needed by r2.py which app.py imports at module level
for _mod in ("boto3", "botocore", "botocore.config"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

import pytest

from commerce.db import init_db, _local as _db_local
from commerce.seed import run_seed
from commerce.identity import get_or_create_anonymous, ANONYMOUS_USER_ID
from commerce.wallet import add_credits, get_balance
from commerce import usage_log as _log

# Import app AFTER sys.modules patches are in place
from app import app as flask_app


# ── Fixtures ─────────────────────────────────────────────────────────────────

TEST_ADMIN_KEY = "test-secret-key"


@pytest.fixture
def db():
    conn = init_db(":memory:")
    run_seed(conn)
    get_or_create_anonymous(conn)
    yield conn
    conn.close()


@pytest.fixture
def client(db, monkeypatch):
    """Flask test client, injecting the in-memory DB and a known ADMIN_KEY."""
    import config.settings as _settings

    monkeypatch.setattr(_settings, "ADMIN_KEY", TEST_ADMIN_KEY)

    # Inject the test DB into the thread-local used by get_db()
    _db_local.conn = db

    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c

    # Restore the thread-local after test
    _db_local.conn = None


def _auth(key=TEST_ADMIN_KEY):
    return {"X-Admin-Key": key}


# ── Task 4.1：Admin API ───────────────────────────────────────────────────────

class TestAdminAuth:
    def test_no_key_returns_403(self, client):
        r = client.get("/api/admin/commerce/users")
        assert r.status_code == 403
        assert b"unauthorized" in r.data

    def test_wrong_key_returns_403(self, client):
        r = client.get("/api/admin/commerce/users",
                       headers={"X-Admin-Key": "wrong"})
        assert r.status_code == 403

    def test_key_via_query_param(self, client):
        r = client.get(f"/api/admin/commerce/users?key={TEST_ADMIN_KEY}")
        assert r.status_code == 200

    def test_key_via_header(self, client):
        r = client.get("/api/admin/commerce/users", headers=_auth())
        assert r.status_code == 200


# ── Google OAuth 安全边界 ────────────────────────────────────────────────────

class TestGoogleOAuthSecurity:
    def test_login_rejects_missing_client_id(self, client, monkeypatch):
        import config.settings as _settings

        monkeypatch.setattr(_settings, "GOOGLE_CLIENT_ID", "")

        r = client.get("/api/auth/google/login")

        assert r.status_code == 503
        assert "GOOGLE_CLIENT_ID" in r.get_data(as_text=True)

    def test_google_login_status_reflects_config(self, client, monkeypatch):
        import config.settings as _settings

        monkeypatch.setattr(_settings, "GOOGLE_CLIENT_ID", "")
        r = client.get("/api/auth/google/status")
        assert r.status_code == 200
        assert r.get_json()["enabled"] is False

        monkeypatch.setattr(_settings, "GOOGLE_CLIENT_ID", "test-client-id")
        r2 = client.get("/api/auth/google/status")
        assert r2.status_code == 200
        assert r2.get_json()["enabled"] is True

    def test_login_sets_secure_state_cookie(self, client, monkeypatch):
        import config.settings as _settings
        monkeypatch.setattr(_settings, "GOOGLE_CLIENT_ID", "test-client-id")
        monkeypatch.setattr(_settings, "AUTH_COOKIE_SECURE", True)

        r = client.get("/api/auth/google/login")

        assert r.status_code == 302
        cookie = r.headers["Set-Cookie"]
        assert "oauth_state=" in cookie
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        assert "SameSite=Lax" in cookie

    def test_invalid_state_is_rejected_before_token_exchange(self, client, monkeypatch):
        import app as app_module
        exchange = MagicMock()
        monkeypatch.setattr(app_module._auth, "google_exchange_code", exchange)
        client.set_cookie("oauth_state", "expected-state", domain="localhost")

        r = client.get(
            "/api/auth/google/callback?code=authorization-code&state=wrong-state"
        )

        assert r.status_code == 302
        assert r.headers["Location"] == "/app?auth_error=invalid_state"
        exchange.assert_not_called()
        assert "oauth_state=;" in r.headers["Set-Cookie"]

    def test_valid_state_creates_secure_session_cookie(self, client, monkeypatch):
        import app as app_module
        import config.settings as _settings
        monkeypatch.setattr(_settings, "AUTH_COOKIE_SECURE", True)
        monkeypatch.setattr(app_module._auth, "google_exchange_code", lambda _code: {
            "sub": "google-user-1", "email": "user@example.com",
            "name": "User", "picture": "",
        })
        client.set_cookie("oauth_state", "expected-state", domain="localhost")

        r = client.get(
            "/api/auth/google/callback?code=authorization-code&state=expected-state"
        )

        assert r.status_code == 302
        cookies = r.headers.getlist("Set-Cookie")
        session_cookie = next(cookie for cookie in cookies if cookie.startswith("session="))
        assert "HttpOnly" in session_cookie
        assert "Secure" in session_cookie
        assert "SameSite=Lax" in session_cookie


class TestTikTokDownloadHelpers:
    def test_download_limit_is_five_minutes(self):
        import app as app_module

        assert app_module._MAX_DOWNLOAD_DURATION_SECONDS == 300

    def test_tiktok_extractor_args_include_device_info(self, monkeypatch):
        import config.settings as _settings
        import app as app_module

        monkeypatch.setattr(_settings, "TIKTOK_DEVICE_ID", "1234567890123456789")
        monkeypatch.setattr(_settings, "TIKTOK_APP_INFO", "9876543210987654321")
        monkeypatch.delattr(app_module, "_TIKTOK_DEVICE_ID_CACHE", raising=False)
        monkeypatch.delattr(app_module, "_TIKTOK_APP_INFO_CACHE", raising=False)

        args = app_module._tiktok_extractor_args()
        assert args == [
            "--extractor-args",
            "tiktok:app_info=9876543210987654321;device_id=1234567890123456789",
        ]

        args2 = app_module._tiktok_extractor_args()
        assert args2 == args

    def test_tiktok_dns_error_is_classified(self):
        import app as app_module

        msg = app_module._classify_download_error(
            "[vm.tiktok] XYZ: Unable to download webpage: Failed to resolve 'vt.tiktok.com'"
        )
        assert "TikTok 链接解析失败" in msg

    def test_tiktok_universal_data_error_is_classified(self):
        import app as app_module

        msg = app_module._classify_download_error(
            "[TikTok] Unable to extract universal data for rehydration; please report this issue"
        )
        assert "TikTok 页面结构变更或反爬拦截" in msg

    def test_tiktok_shortlink_resolution_uses_final_url(self, monkeypatch):
        import app as app_module

        class _Resp:
            def __init__(self, final_url):
                self._final_url = final_url

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def geturl(self):
                return self._final_url

        monkeypatch.setattr(
            app_module.urllib.request,
            "urlopen",
            lambda req, timeout=15: _Resp("https://www.tiktok.com/@demo/video/123"),
        )
        final = app_module._resolve_tiktok_url("https://vt.tiktok.com/abcd/")
        assert final == "https://www.tiktok.com/@demo/video/123"

    def test_unique_video_output_path_appends_suffix(self, tmp_path):
        import app as app_module

        base = tmp_path / "same-title.mp4"
        base.write_bytes(b"old")

        second = app_module._unique_video_output_path(str(base))
        assert second.endswith("same-title (2).mp4")

    def test_tiktok_format_probe_prefers_h264_progressive(self):
        import app as app_module

        sample = {
            "formats": [
                {"format_id": "download", "ext": "mp4", "vcodec": "h264", "acodec": "aac"},
                {"format_id": "bytevc1_1080p_1320963-1", "ext": "mp4", "vcodec": "h265", "acodec": "aac", "filesize": 39645463},
                {"format_id": "h264_540p_748415-0", "ext": "mp4", "vcodec": "h264", "acodec": "aac", "filesize": 22146927},
                {"format_id": "h264_540p_1478862-0", "ext": "mp4", "vcodec": "h264", "acodec": "aac", "filesize": 43762137},
            ]
        }


class TestRecognitionModes:
    def test_visible_modes_are_exposed(self):
        import ai.recognition_mode as recognition_mode

        modes = recognition_mode.list_visible_modes()
        keys = [m["key"] for m in modes]
        assert keys == ["speed", "balanced", "accuracy"]
        assert modes[1]["preferred_provider"] == "groq"

    def test_mode_resolution_prefers_new_mode_then_legacy_provider(self):
        import ai.recognition_mode as recognition_mode

        assert recognition_mode.resolve_recognition_mode().key == "balanced"
        assert recognition_mode.resolve_recognition_mode("speed").key == "speed"
        assert recognition_mode.resolve_recognition_mode(provider="groq").key == "balanced"
        assert recognition_mode.resolve_recognition_mode(provider="qwen").key == "accuracy"

    def test_accuracy_provider_order_is_language_specific(self):
        import ai.recognition_mode as recognition_mode

        assert recognition_mode.get_accuracy_provider_candidates("th") == ("groq", "openai", "gemini", "qwen")
        assert recognition_mode.get_accuracy_provider_candidates("en") == ("gemini", "openai", "groq", "qwen")
        assert recognition_mode.get_accuracy_provider_candidates("zh") == ("qwen", "groq", "openai", "gemini")
        assert recognition_mode.get_accuracy_provider_candidates("ja") == ("openai", "qwen", "groq", "gemini")

    def test_recognition_modes_api(self, client):
        r = client.get("/api/recognition-modes")
        assert r.status_code == 200
        data = r.get_json()
        assert data["default"] == "balanced"
        assert [m["key"] for m in data["modes"]] == ["speed", "balanced", "accuracy"]


class TestUsagePageRoute:
    def test_usage_page_exists(self, client):
        r = client.get("/usage")
        assert r.status_code == 200
        body = r.get_data(as_text=True)
        assert "Usage History" in body or "使用记录" in body

    def test_ytdlp_auto_update_runs_in_deploy_env(self, monkeypatch, tmp_path):
        import app as app_module
        import config.settings as _settings

        calls = []

        def _check_output(cmd, text=True, timeout=10):
            calls.append(("check_output", tuple(cmd)))
            return "2026.03.17"

        def _run(cmd, capture_output=True, text=True, timeout=300):
            calls.append(("run", tuple(cmd)))
            class _Result:
                returncode = 0
                stdout = ""
                stderr = ""
            return _Result()

        monkeypatch.setattr(_settings, "YTDLP_AUTO_UPDATE", True)
        monkeypatch.setattr(_settings, "YTDLP_AUTO_UPDATE_INTERVAL_HOURS", 24)
        monkeypatch.setattr(_settings, "YTDLP_UPDATE_STAMP", str(tmp_path / "yt-dlp.stamp"))
        monkeypatch.setattr(app_module.subprocess, "check_output", _check_output)
        monkeypatch.setattr(app_module.subprocess, "run", _run)
        monkeypatch.setattr(app_module.sys, "executable", "/usr/bin/python3")

        app_module._maybe_auto_update_ytdlp()

        assert any(call[0] == "run" and "pip" in call[1] for call in calls)
        assert (tmp_path / "yt-dlp.stamp").exists()


class TestTranscribeErrorHandling:
    def test_thai_alignment_uses_word_tokens(self):
        import ai.speech as speech

        segments = [{"text": "สวัสดีครับ", "start": 0.0, "end": 1.2}]
        groq_words = [
            {"word": "สวัสดี", "start": 0.0, "end": 0.6},
            {"word": "ครับ", "start": 0.6, "end": 1.2},
        ]

        speech.align_word_timestamps(segments, groq_words, language="th")

        assert segments[0]["wordTimings"] == [
            {"start": 0.0, "end": 0.6},
            {"start": 0.6, "end": 1.2},
        ]

    def test_transcribe_error_413_is_classified(self):
        import app as app_module

        msg = app_module._classify_transcribe_error(
            "Error code:413-['error':{'message':'Request Entity Too Large','type':'invalid_request_error','code':'request_too_large'}]"
        )
        assert "识别请求过大" in msg

    def test_openai_transcribe_rejects_oversized_wav_before_api_call(self, monkeypatch, tmp_path):
        import ai.speech as speech

        wav_path = tmp_path / "oversize.wav"
        wav_path.write_bytes(b"0")

        def _safe_wav_path(_video_path, _suffix):
            return str(wav_path)

        class _Result:
            returncode = 0
            stderr = ""

        called = {"api": False}

        def _transcribe_file(*args, **kwargs):
            called["api"] = True
            raise AssertionError("OpenAI API should not be called when file is oversized")

        monkeypatch.setattr(speech, "_safe_wav_path", _safe_wav_path)
        monkeypatch.setattr(speech.subprocess, "run", lambda *a, **k: _Result())
        monkeypatch.setattr(speech.os.path, "getsize", lambda p: 25 * 1024 * 1024 + 1)
        monkeypatch.setattr(speech.openai_provider, "transcribe_file", _transcribe_file)

        with pytest.raises(RuntimeError) as exc:
            speech.transcribe_openai("/tmp/video.mp4")

        assert "超过 OpenAI 单次上传限制" in str(exc.value)
        assert called["api"] is False

    def test_openai_gpt4o_merges_text_with_groq_timestamps(self, monkeypatch):
        import ai.speech as speech

        monkeypatch.setattr(speech.providers.OpenAI, "TRANSCRIBE_MODEL", "gpt-4o-transcribe")
        monkeypatch.setattr(speech.providers.Groq, "API_KEY", "dummy")
        monkeypatch.setattr(speech.os.path, "getsize", lambda _path: 1024)
        monkeypatch.setattr(
            speech.openai_provider,
            "transcribe_text",
            lambda _path, language=None: "hello there world",
        )
        monkeypatch.setattr(
            speech,
            "_transcribe_groq_wav",
            lambda _path: {
                "segments": [
                    {"index": 0, "text": "hello", "start": 0.0, "end": 1.0},
                    {"index": 1, "text": "world", "start": 1.0, "end": 2.0},
                ],
                "language": "en",
                "words": [
                    {"word": "hello", "start": 0.0, "end": 1.0},
                    {"word": "world", "start": 1.0, "end": 2.0},
                ],
            },
        )

        result = speech._transcribe_openai_wav("/tmp/sample.wav")

        assert result["segments"][0]["text"] == "hello there"
        assert result["segments"][1]["text"] == "world"
        assert result["words"][0]["word"] == "hello"

    def test_transcribe_video_skips_retry_for_gpt4o(self, monkeypatch):
        import ai.speech as speech

        monkeypatch.setattr(speech.providers.OpenAI, "TRANSCRIBE_MODEL", "gpt-4o-transcribe")
        monkeypatch.setattr(speech, "get_video_duration", lambda _path: 10)
        monkeypatch.setattr(
            speech,
            "transcribe_openai",
            lambda _path: {
                "segments": [{"text": "ok", "start": 0.0, "end": 1.0, "_logprob": -1.2}],
                "language": "en",
            },
        )
        monkeypatch.setattr(speech, "fix_timestamps", lambda segs: segs)
        monkeypatch.setattr(speech, "normalize_segments", lambda segs, target: segs)
        monkeypatch.setattr(
            speech,
            "_retry_low_confidence_with_groq",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not retry")),
        )

        result = speech.transcribe_video("/tmp/video.mp4", provider="openai")

        assert result["segments"][0]["text"] == "ok"

    def test_transcribe_video_retries_low_confidence_for_groq_short_video(self, monkeypatch):
        import ai.speech as speech

        called = {"retry": 0}

        monkeypatch.setattr(speech, "get_video_duration", lambda _path: 10)
        monkeypatch.setattr(
            speech,
            "transcribe_groq",
            lambda _path: {
                "segments": [{"text": "ok", "start": 0.0, "end": 1.0, "_logprob": -1.2}],
                "language": "th",
            },
        )
        monkeypatch.setattr(speech, "fix_timestamps", lambda segs: segs)
        monkeypatch.setattr(speech, "normalize_segments", lambda segs, target: segs)
        monkeypatch.setattr(
            speech,
            "_retry_low_confidence_with_groq",
            lambda *args, **kwargs: called.__setitem__("retry", called["retry"] + 1),
        )

        result = speech.transcribe_video("/tmp/video.mp4", provider="groq")

        assert result["segments"][0]["text"] == "ok"
        assert called["retry"] == 1

    def test_transcribe_video_can_disable_groq_retry(self, monkeypatch):
        import ai.speech as speech

        called = {"retry": 0}

        monkeypatch.setattr(speech, "get_video_duration", lambda _path: 10)
        monkeypatch.setattr(
            speech,
            "transcribe_groq",
            lambda _path: {
                "segments": [{"text": "ok", "start": 0.0, "end": 1.0, "_logprob": -1.2}],
                "language": "th",
            },
        )
        monkeypatch.setattr(speech, "fix_timestamps", lambda segs: segs)
        monkeypatch.setattr(speech, "normalize_segments", lambda segs, target: segs)
        monkeypatch.setattr(
            speech,
            "_retry_low_confidence_with_groq",
            lambda *args, **kwargs: called.__setitem__("retry", called["retry"] + 1),
        )

        result = speech.transcribe_video("/tmp/video.mp4", provider="groq", enable_groq_retry=False)

        assert result["segments"][0]["text"] == "ok"
        assert called["retry"] == 0

    def test_retry_low_confidence_with_groq_limits_segments(self, monkeypatch):
        import ai.speech as speech

        calls = []

        segments = [
            {"text": f"seg{i}", "start": float(i * 2), "end": float(i * 2 + 1), "_logprob": -1.2}
            for i in range(6)
        ]
        monkeypatch.setattr(speech.providers.Groq, "API_KEY", "dummy")
        monkeypatch.setattr(
            speech.groq_provider,
            "transcribe_text",
            lambda path, language=None: calls.append((path, language)) or "ok",
        )
        monkeypatch.setattr(
            speech.subprocess,
            "run",
            lambda *args, **kwargs: type("R", (), {"returncode": 0, "stderr": ""})(),
        )
        monkeypatch.setattr(speech.os.path, "exists", lambda _path: False)

        speech._retry_low_confidence_with_groq("/tmp/video.mp4", segments, language="th")

        assert len(calls) == 4

    def test_transcribe_video_falls_back_to_groq_when_openai_is_too_large(self, monkeypatch):
        import ai.speech as speech

        calls = []

        monkeypatch.setattr(speech, "get_video_duration", lambda _path: 10)
        monkeypatch.setattr(speech, "transcribe_openai", lambda _path: (_ for _ in ()).throw(RuntimeError("识别请求过大（约 30.0MB，超过 OpenAI 单次上传限制）")))
        monkeypatch.setattr(speech, "transcribe_chunked", lambda video_path, provider, duration, progress_callback=None: calls.append((video_path, provider, duration)) or {"segments": [{"text": "ok", "start": 0, "end": 1}], "language": "en"})
        monkeypatch.setattr(speech, "fix_timestamps", lambda segs: segs)
        monkeypatch.setattr(speech, "normalize_segments", lambda segs, target: segs)

        result = speech.transcribe_video("/tmp/video.mp4", provider="openai")

        assert result["segments"][0]["text"] == "ok"
        assert calls and calls[0][1] == "groq"

    def test_transcribe_slice_falls_back_to_groq_when_openai_is_too_large(self, monkeypatch):
        import ai.speech as speech

        monkeypatch.setattr(speech, "transcribe_openai", lambda _path, language=None: (_ for _ in ()).throw(RuntimeError("request_too_large")))
        monkeypatch.setattr(speech, "_transcribe_groq_wav", lambda _path: {"segments": [{"text": "ok", "start": 0, "end": 1}], "language": "en"})

        result = speech.transcribe_slice("/tmp/slice.wav", provider="openai")

        assert result["text"] == "ok"

    def test_retranscribe_skips_language_mismatch_candidate(self, monkeypatch):
        import app as app_module
        from ai.recognition_mode import resolve_recognition_mode

        calls = []

        def fake_transcribe_slice(_path, provider="groq", language=None):
            calls.append((provider, language))
            return {"text": "สวัสดี", "language": "th"}

        class DummyCtx:
            def get_handle(self, preferred_provider=None):
                return SimpleNamespace(provider_id=preferred_provider, model_id=f"{preferred_provider}-model")

        monkeypatch.setattr(app_module, "transcribe_slice", fake_transcribe_slice)

        result, handle, fallback_used, fallback_from = app_module._attempt_transcription_with_mode(
            DummyCtx(),
            resolve_recognition_mode("accuracy"),
            audio_path="/tmp/slice.wav",
            language="th",
        )

        assert result["text"] == "สวัสดี"
        assert handle.provider_id == "groq"
        assert fallback_used is False
        assert fallback_from == "groq"
        assert calls == [("groq", "th")]

    def test_retranscribe_attempt_starts_from_next_provider(self, monkeypatch):
        import app as app_module
        from ai.recognition_mode import resolve_recognition_mode

        calls = []

        def fake_transcribe_slice(_path, provider="groq", language=None):
            calls.append(provider)
            return {"text": "different result", "language": "th"}

        class DummyCtx:
            def get_handle(self, preferred_provider=None):
                return SimpleNamespace(provider_id=preferred_provider, model_id=f"{preferred_provider}-model")

        monkeypatch.setattr(app_module, "transcribe_slice", fake_transcribe_slice)
        result, handle, _, _ = app_module._attempt_transcription_with_mode(
            DummyCtx(),
            resolve_recognition_mode("accuracy"),
            audio_path="/tmp/slice.wav",
            language="th",
            candidate_offset=1,
        )

        assert result["text"] == "different result"
        assert handle.provider_id == "openai"
        assert calls == ["openai"]

    def test_retranscribe_skips_repeated_text(self, monkeypatch):
        import app as app_module
        from ai.recognition_mode import resolve_recognition_mode

        calls = []

        def fake_transcribe_slice(_path, provider="groq", language=None):
            calls.append(provider)
            text = "same result" if provider == "openai" else "new result"
            return {"text": text, "language": "th"}

        class DummyCtx:
            def get_handle(self, preferred_provider=None):
                return SimpleNamespace(provider_id=preferred_provider, model_id=f"{preferred_provider}-model")

        monkeypatch.setattr(app_module, "transcribe_slice", fake_transcribe_slice)
        result, handle, _, _ = app_module._attempt_transcription_with_mode(
            DummyCtx(),
            resolve_recognition_mode("accuracy"),
            audio_path="/tmp/slice.wav",
            language="th",
            candidate_offset=1,
            rejected_texts=["same result"],
        )

        assert result["text"] == "new result"
        assert handle.provider_id == "gemini"
        assert calls == ["openai", "gemini"]

    def test_transcribe_video_falls_back_to_chunked_when_groq_is_too_large(self, monkeypatch):
        import ai.speech as speech

        calls = []

        monkeypatch.setattr(speech, "get_video_duration", lambda _path: 10)
        monkeypatch.setattr(speech.os.path, "getsize", lambda _path: speech._GROQ_MAX_DIRECT_BYTES + 1)
        monkeypatch.setattr(speech, "transcribe_groq", lambda _path: (_ for _ in ()).throw(RuntimeError("request_too_large")))
        monkeypatch.setattr(speech, "transcribe_chunked", lambda video_path, provider, duration, progress_callback=None: calls.append((video_path, provider, duration)) or {"segments": [{"text": "ok", "start": 0, "end": 1}], "language": "en"})
        monkeypatch.setattr(speech, "fix_timestamps", lambda segs: segs)
        monkeypatch.setattr(speech, "normalize_segments", lambda segs, target: segs)

        result = speech.transcribe_video("/tmp/video.mp4", provider="groq")

        assert result["segments"][0]["text"] == "ok"
        assert calls and calls[0][1] == "groq"

    def test_transcribe_chunked_uses_two_minute_chunks_for_groq(self, monkeypatch):
        import ai.speech as speech
        from types import SimpleNamespace

        chunk_calls = []

        def fake_extract(video_path, start, duration):
            chunk_calls.append((round(start, 2), round(duration, 2)))
            return f"/tmp/chunk_{len(chunk_calls)}.wav"

        def fake_transcribe(path, timestamp_granularities=None, language=None):
            if len(chunk_calls) == 1:
                return SimpleNamespace(
                    segments=[SimpleNamespace(text="สวัสดี", start=0.0, end=1.0)],
                    words=[SimpleNamespace(word="สวัสดี", start=0.0, end=1.0)],
                    language="th",
                )
            return SimpleNamespace(
                segments=[SimpleNamespace(text="ค่ะ", start=0.0, end=1.0)],
                words=[SimpleNamespace(word="ค่ะ", start=0.0, end=1.0)],
                language="th",
            )

        monkeypatch.setattr(speech, "_extract_chunk_wav", fake_extract)
        monkeypatch.setattr(speech.groq_provider, "transcribe_file", fake_transcribe)
        monkeypatch.setattr(speech.os.path, "exists", lambda _path: False)

        result = speech.transcribe_chunked("/tmp/video.mp4", "groq", 350, progress_callback=None)

        assert chunk_calls[:3] == [(0.0, 120), (120.0, 120), (240.0, 110)]
        assert result["language"] == "th"
        assert len(result["segments"]) == 3

    def test_qwen_filetrans_uses_public_file_url_and_async_task(self, monkeypatch, tmp_path):
        import ai.provider.qwen_asr as qwen_asr

        recorded = {}
        sample = tmp_path / "sample.wav"
        sample.write_bytes(b"RIFF0000WAVEfmt ")

        class _Resp:
            def __init__(self, data, ok=True, status=200):
                self._data = data
                self.ok = ok
                self.status_code = status
                self.text = json.dumps(data, ensure_ascii=False)

            def json(self):
                return self._data

            def raise_for_status(self):
                if not self.ok:
                    raise RuntimeError(self.text)

        def fake_get(url, headers=None, params=None, timeout=None):
            if url.endswith("/uploads"):
                recorded["policy_url"] = url
                recorded["policy_params"] = params or {}
                return _Resp({
                    "data": {
                        "upload_dir": "dashscope-instant/test/2026-07-19/abc",
                        "upload_host": "https://oss.example/upload",
                        "oss_access_key_id": "AK",
                        "signature": "SIG",
                        "policy": "POLICY",
                        "x_oss_object_acl": "private",
                        "x_oss_forbid_overwrite": "true",
                    }
                })
            if url == "https://example.test/result.json":
                return _Resp({
                    "transcripts": [{
                        "language": "th",
                        "sentences": [{
                            "begin_time": 100,
                            "end_time": 900,
                            "text": "สวัสดี",
                            "words": [
                                {"begin_time": 100, "end_time": 900, "text": "สวัสดี"},
                            ],
                        }],
                    }],
                })
            if url.endswith("/tasks/task-123"):
                return _Resp({
                    "output": {
                        "task_status": "SUCCEEDED",
                        "result": {"transcription_url": "https://example.test/result.json"},
                    }
                })
            raise AssertionError(f"unexpected GET {url}")

        def fake_post(url, headers=None, json=None, files=None, timeout=None):
            if url == "https://oss.example/upload":
                recorded["oss_upload_url"] = url
                recorded["oss_upload_fields"] = files or {}
                return _Resp({}, status=200)
            recorded["submit_url"] = url
            recorded["headers"] = headers or {}
            recorded["payload"] = json or {}
            return _Resp({"output": {"task_id": "task-123"}})

        monkeypatch.setattr(qwen_asr.providers.Qwen, "ASR_API_KEY", "dummy")
        monkeypatch.setattr(qwen_asr.requests, "post", fake_post)
        monkeypatch.setattr(qwen_asr.requests, "get", fake_get)
        monkeypatch.setattr(qwen_asr, "_POLL_INTERVAL", 0)
        monkeypatch.setattr(qwen_asr, "_POLL_MAX_WAIT", 1)
        monkeypatch.setattr(qwen_asr.time, "sleep", lambda *_args, **_kwargs: None)

        result = qwen_asr.transcribe_file(str(sample))

        assert recorded["policy_params"]["action"] == "getPolicy"
        assert recorded["policy_params"]["model"] == qwen_asr.providers.Qwen.ASR_MODEL
        assert recorded["oss_upload_fields"]["key"][1].startswith("dashscope-instant/test/2026-07-19/")
        assert recorded["headers"]["X-DashScope-Async"] == "enable"
        assert recorded["headers"]["X-DashScope-OssResourceResolve"] == "enable"
        assert recorded["payload"]["input"]["file_url"].startswith("oss://dashscope-instant/")
        assert result["language"] == "th"
        assert result["segments"][0]["text"] == "สวัสดี"
        assert result["words"][0]["word"] == "สวัสดี"


class TestAdminUsers:
    def test_returns_users_list(self, client):
        r = client.get("/api/admin/commerce/users", headers=_auth())
        assert r.status_code == 200
        body = r.get_json()
        assert "users" in body
        assert "count" in body
        assert body["count"] >= 1   # anonymous user exists

    def test_anonymous_user_included(self, client):
        r = client.get("/api/admin/commerce/users", headers=_auth())
        body = r.get_json()
        ids = [u["user_id"] for u in body["users"]]
        assert ANONYMOUS_USER_ID in ids

    def test_user_has_balance_fields(self, client, db):
        add_credits(db, ANONYMOUS_USER_ID, 200, "subscription", "test")
        r = client.get("/api/admin/commerce/users", headers=_auth())
        body = r.get_json()
        anon = next(u for u in body["users"] if u["user_id"] == ANONYMOUS_USER_ID)
        assert "balance" in anon
        assert anon["balance"]["total"] >= 200
        assert "subscription" in anon["balance"]

    def test_user_has_plan_field(self, client):
        r = client.get("/api/admin/commerce/users", headers=_auth())
        body = r.get_json()
        anon = next(u for u in body["users"] if u["user_id"] == ANONYMOUS_USER_ID)
        assert "plan" in anon
        assert anon["plan"] == "free"


class TestAdminUsage:
    def test_empty_returns_zeros(self, client):
        r = client.get("/api/admin/commerce/usage", headers=_auth())
        assert r.status_code == 200
        body = r.get_json()
        assert body["total_credits"] == 0
        assert "by_capability" in body
        assert "by_provider" in body

    def test_days_param(self, client):
        r = client.get("/api/admin/commerce/usage?days=30", headers=_auth())
        assert r.status_code == 200
        assert r.get_json()["days"] == 30

    def test_usage_aggregates_after_log(self, client, db):
        # Write two usage logs
        for _ in range(2):
            _log.record(
                db,
                user_id=ANONYMOUS_USER_ID,
                capability="transcription",
                quality_tier="standard",
                provider_id="groq",
                model_id="whisper-large-v3",
                plan_id="free",
                input_units=60.0,
                input_unit_type="seconds",
                provider_cost_usd=0.003,
                credits_reserved=10,
                credits_charged=10,
                latency_ms=2000,
                status="success",
            )

        r = client.get("/api/admin/commerce/usage?days=7", headers=_auth())
        body = r.get_json()
        assert body["total_credits"] >= 20
        assert "transcription" in body["by_capability"]
        assert "groq" in body["by_provider"]

    def test_failed_calls_counted(self, client, db):
        _log.record(
            db,
            user_id=ANONYMOUS_USER_ID,
            capability="transcription",
            quality_tier="standard",
            provider_id="groq",
            model_id="whisper-large-v3",
            plan_id="free",
            credits_reserved=0,
            credits_charged=0,
            latency_ms=None,
            status="failed",
            error_code="TimeoutError",
        )
        r = client.get("/api/admin/commerce/usage?days=7", headers=_auth())
        body = r.get_json()
        assert body["by_capability"].get("transcription", {}).get("failed", 0) >= 1


class TestAdminCosts:
    def test_empty_returns_zeros(self, client):
        r = client.get("/api/admin/commerce/costs", headers=_auth())
        assert r.status_code == 200
        body = r.get_json()
        assert body["total_cost_usd"] == 0.0
        assert body["total_credits"] == 0
        assert isinstance(body["entries"], list)

    def test_costs_excludes_failed(self, client, db):
        _log.record(
            db,
            user_id=ANONYMOUS_USER_ID,
            capability="transcription",
            quality_tier="standard",
            provider_id="groq",
            model_id="whisper-large-v3",
            plan_id="free",
            credits_reserved=0,
            credits_charged=0,
            provider_cost_usd=1.0,
            latency_ms=None,
            status="failed",
        )
        r = client.get("/api/admin/commerce/costs?days=7", headers=_auth())
        body = r.get_json()
        # failed entries should not appear in costs
        assert body["total_cost_usd"] == 0.0

    def test_costs_includes_success(self, client, db):
        _log.record(
            db,
            user_id=ANONYMOUS_USER_ID,
            capability="translation",
            quality_tier="standard",
            provider_id="deepseek",
            model_id="deepseek-chat",
            plan_id="free",
            input_units=500.0,
            input_unit_type="chars",
            provider_cost_usd=0.0005,
            credits_reserved=5,
            credits_charged=5,
            latency_ms=800,
            status="success",
        )
        r = client.get("/api/admin/commerce/costs?days=7", headers=_auth())
        body = r.get_json()
        assert body["total_cost_usd"] > 0
        assert len(body["entries"]) >= 1

    def test_costs_days_param(self, client):
        r = client.get("/api/admin/commerce/costs?days=14", headers=_auth())
        assert r.get_json()["days"] == 14


class TestAdminGrant:
    def test_grant_credits_increases_balance(self, client, db):
        initial = get_balance(db, ANONYMOUS_USER_ID)["total"]
        r = client.post(
            "/api/admin/commerce/credits/grant",
            headers={**_auth(), "Content-Type": "application/json"},
            data=json.dumps({
                "user_id": ANONYMOUS_USER_ID,
                "amount": 500,
                "type": "gift",
                "reason": "test grant",
            }),
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body["ok"] is True
        assert body["granted"] == 500
        assert body["balance"]["total"] == initial + 500

    def test_grant_subscription_credits(self, client, db):
        r = client.post(
            "/api/admin/commerce/credits/grant",
            headers={**_auth(), "Content-Type": "application/json"},
            data=json.dumps({
                "user_id": ANONYMOUS_USER_ID,
                "amount": 1000,
                "type": "subscription",
            }),
        )
        assert r.status_code == 200
        assert r.get_json()["ok"] is True

    def test_grant_missing_user_id_returns_400(self, client):
        r = client.post(
            "/api/admin/commerce/credits/grant",
            headers={**_auth(), "Content-Type": "application/json"},
            data=json.dumps({"amount": 100}),
        )
        assert r.status_code == 400

    def test_grant_zero_amount_returns_400(self, client):
        r = client.post(
            "/api/admin/commerce/credits/grant",
            headers={**_auth(), "Content-Type": "application/json"},
            data=json.dumps({"user_id": ANONYMOUS_USER_ID, "amount": 0}),
        )
        assert r.status_code == 400

    def test_grant_invalid_type_returns_400(self, client):
        r = client.post(
            "/api/admin/commerce/credits/grant",
            headers={**_auth(), "Content-Type": "application/json"},
            data=json.dumps({
                "user_id": ANONYMOUS_USER_ID,
                "amount": 100,
                "type": "invalid",
            }),
        )
        assert r.status_code == 400

    def test_grant_requires_auth(self, client):
        r = client.post(
            "/api/admin/commerce/credits/grant",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"user_id": ANONYMOUS_USER_ID, "amount": 100}),
        )
        assert r.status_code == 403


class TestAdminRefund:
    def _create_log(self, db) -> str:
        return _log.record(
            db,
            user_id=ANONYMOUS_USER_ID,
            capability="transcription",
            quality_tier="standard",
            provider_id="groq",
            model_id="whisper-large-v3",
            plan_id="free",
            input_units=60.0,
            input_unit_type="seconds",
            provider_cost_usd=0.003,
            credits_reserved=10,
            credits_charged=10,
            latency_ms=2000,
            status="success",
        )

    def test_refund_adds_gift_credits(self, client, db):
        add_credits(db, ANONYMOUS_USER_ID, 50, "subscription", "init")
        log_id = self._create_log(db)
        initial = get_balance(db, ANONYMOUS_USER_ID)["gift"]

        r = client.post(
            "/api/admin/commerce/credits/refund",
            headers={**_auth(), "Content-Type": "application/json"},
            data=json.dumps({
                "usage_log_id": log_id,
                "amount": 10,
                "reason": "quality issue",
            }),
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body["ok"] is True
        assert body["refunded"] == 10
        assert get_balance(db, ANONYMOUS_USER_ID)["gift"] == initial + 10

    def test_refund_missing_log_id_returns_400(self, client):
        r = client.post(
            "/api/admin/commerce/credits/refund",
            headers={**_auth(), "Content-Type": "application/json"},
            data=json.dumps({"amount": 10}),
        )
        assert r.status_code == 400

    def test_refund_invalid_log_returns_error(self, client):
        r = client.post(
            "/api/admin/commerce/credits/refund",
            headers={**_auth(), "Content-Type": "application/json"},
            data=json.dumps({"usage_log_id": "nonexistent-log", "amount": 10}),
        )
        # wallet.refund raises ValueError for bad log_id → 404
        assert r.status_code in (404, 500)

    def test_refund_requires_auth(self, client):
        r = client.post(
            "/api/admin/commerce/credits/refund",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"usage_log_id": "x", "amount": 10}),
        )
        assert r.status_code == 403


class TestAdminLog:
    def test_get_existing_log(self, client, db):
        log_id = _log.record(
            db,
            user_id=ANONYMOUS_USER_ID,
            capability="translation",
            quality_tier="standard",
            provider_id="deepseek",
            model_id="deepseek-chat",
            plan_id="free",
            credits_reserved=5,
            credits_charged=5,
            latency_ms=800,
            status="success",
        )
        r = client.get(f"/api/admin/commerce/log/{log_id}", headers=_auth())
        assert r.status_code == 200
        body = r.get_json()
        assert body["log_id"] == log_id
        assert body["capability"] == "translation"
        assert body["provider_id"] == "deepseek"

    def test_get_nonexistent_log_returns_404(self, client):
        r = client.get("/api/admin/commerce/log/does-not-exist", headers=_auth())
        assert r.status_code == 404

    def test_get_log_requires_auth(self, client):
        r = client.get("/api/admin/commerce/log/any-id")
        assert r.status_code == 403


# ── Task 4.2：用户余额 API ────────────────────────────────────────────────────

class TestUserWallet:
    def test_returns_200(self, client):
        r = client.get("/api/user/wallet")
        assert r.status_code == 200

    def test_response_has_required_fields(self, client):
        r = client.get("/api/user/wallet")
        body = r.get_json()
        assert "user_id" in body
        assert "plan" in body
        assert "balance" in body
        assert "subscription_expires_at" in body
        assert "monthly_quota" in body

    def test_user_id_is_anonymous(self, client):
        r = client.get("/api/user/wallet")
        assert r.get_json()["user_id"] == ANONYMOUS_USER_ID

    def test_balance_reflects_added_credits(self, client, db):
        add_credits(db, ANONYMOUS_USER_ID, 300, "subscription", "test")
        r = client.get("/api/user/wallet")
        body = r.get_json()
        assert body["balance"]["total"] >= 300
        assert body["balance"]["subscription"] >= 300

    def test_plan_is_free_for_anonymous(self, client):
        r = client.get("/api/user/wallet")
        assert r.get_json()["plan"] == "free"

    def test_no_auth_required(self, client):
        # wallet is public in transition period
        r = client.get("/api/user/wallet")
        assert r.status_code == 200


class TestUserUsage:
    def test_returns_200(self, client):
        r = client.get("/api/user/usage")
        assert r.status_code == 200

    def test_response_structure(self, client):
        r = client.get("/api/user/usage")
        body = r.get_json()
        assert "user_id" in body
        assert "summary" in body
        assert "history" in body

    def test_empty_history(self, client):
        r = client.get("/api/user/usage")
        body = r.get_json()
        assert isinstance(body["history"], list)
        assert len(body["history"]) == 0

    def test_history_after_logs(self, client, db):
        for _ in range(3):
            _log.record(
                db,
                user_id=ANONYMOUS_USER_ID,
                capability="transcription",
                quality_tier="standard",
                provider_id="groq",
                model_id="whisper-large-v3",
                plan_id="free",
                credits_reserved=10,
                credits_charged=10,
                latency_ms=2000,
                status="success",
            )

        r = client.get("/api/user/usage")
        body = r.get_json()
        assert len(body["history"]) == 3

    def test_summary_aggregates_correctly(self, client, db):
        _log.record(
            db,
            user_id=ANONYMOUS_USER_ID,
            capability="translation",
            quality_tier="standard",
            provider_id="deepseek",
            model_id="deepseek-chat",
            plan_id="free",
            credits_reserved=5,
            credits_charged=5,
            latency_ms=800,
            status="success",
        )
        r = client.get("/api/user/usage")
        summary = r.get_json()["summary"]
        assert "by_capability" in summary
        assert "by_provider" in summary
        assert summary["by_capability"].get("translation", 0) > 0

    def test_limit_param(self, client, db):
        for _ in range(10):
            _log.record(
                db,
                user_id=ANONYMOUS_USER_ID,
                capability="transcription",
                quality_tier="standard",
                provider_id="groq",
                model_id="whisper-large-v3",
                plan_id="free",
                credits_reserved=5,
                credits_charged=5,
                latency_ms=1000,
                status="success",
            )
        r = client.get("/api/user/usage?limit=3")
        body = r.get_json()
        assert len(body["history"]) <= 3

    def test_no_auth_required(self, client):
        r = client.get("/api/user/usage")
        assert r.status_code == 200


class TestUserUsageDetail:
    def test_summary_includes_counts(self, client, db):
        for _ in range(2):
            _log.record(
                db,
                user_id=ANONYMOUS_USER_ID,
                capability="translation",
                quality_tier="standard",
                provider_id="gemini",
                model_id="gemini-3.1-flash-lite",
                plan_id="free",
                credits_reserved=2,
                credits_charged=2,
                latency_ms=120,
                status="success",
            )
        _log.record(
            db,
            user_id=ANONYMOUS_USER_ID,
            capability="translation",
            quality_tier="standard",
            provider_id="gemini",
            model_id="gemini-3.1-flash-lite",
            plan_id="free",
            credits_reserved=2,
            credits_charged=0,
            latency_ms=100,
            status="failed",
        )

        r = client.get("/api/user/usage?days=30")
        summary = r.get_json()["summary"]
        assert summary["total_count"] >= 3
        assert summary["success_count"] >= 2
        assert summary["failed_count"] >= 1

    def test_detail_endpoint_returns_log(self, client, db, monkeypatch):
        log_id = _log.record(
            db,
            user_id=ANONYMOUS_USER_ID,
            capability="transcription",
            quality_tier="standard",
            provider_id="groq",
            model_id="whisper-large-v3",
            plan_id="free",
            credits_reserved=5,
            credits_charged=5,
            latency_ms=900,
            status="success",
            extra={"video": "demo.mp4"},
        )

        import app as app_module
        monkeypatch.setattr(app_module._auth, "get_current_user", lambda _db, _req: {
            "user_id": ANONYMOUS_USER_ID,
            "email": "",
            "name": "",
            "picture_url": "",
        })

        r = client.get(f"/api/user/usage/{log_id}")
        assert r.status_code == 200
        body = r.get_json()
        assert body["log_id"] == log_id
        assert body["extra"]["video"] == "demo.mp4"

    def test_detail_endpoint_missing_returns_404(self, client, monkeypatch):
        import app as app_module
        monkeypatch.setattr(app_module._auth, "get_current_user", lambda _db, _req: {
            "user_id": ANONYMOUS_USER_ID,
            "email": "",
            "name": "",
            "picture_url": "",
        })

        r = client.get("/api/user/usage/not-found")
        assert r.status_code == 404
