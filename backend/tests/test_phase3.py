"""
Phase 3 测试：CommerceContext 中间件 + 集成链路
pytest backend/tests/test_phase3.py
"""
import pytest

from commerce.db import init_db
from commerce.seed import run_seed
from commerce.identity import create_user, ANONYMOUS_USER_ID, get_or_create_anonymous
from commerce.wallet import add_credits, get_balance, InsufficientFundsError
from commerce.middleware import CommerceContext
from commerce.usage_log import get_log, get_summary


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    conn = init_db(":memory:")
    run_seed(conn)
    get_or_create_anonymous(conn)
    yield conn
    conn.close()


def _funded_ctx(db, capability, credits=500, **kwargs) -> CommerceContext:
    add_credits(db, ANONYMOUS_USER_ID, credits, "subscription", "test")
    return CommerceContext(db, ANONYMOUS_USER_ID, capability,
                          quality_tier="standard", plan_id="free", **kwargs)


# ── Task 3.0：CommerceContext ─────────────────────────────────────────────────

class TestCommerceContextPermission:
    def test_check_permission_transcribe_free(self, db):
        ctx = CommerceContext(db, ANONYMOUS_USER_ID, "transcription")
        assert ctx.check_permission("CanTranscribe") is True

    def test_check_permission_tts_free_allowed(self, db):
        # free plan 现在包含 CanTTS（通过限流而非权限管控用量）
        ctx = CommerceContext(db, ANONYMOUS_USER_ID, "tts_synthesis")
        assert ctx.check_permission("CanTTS") is True

    def test_check_permission_export_free_allowed(self, db):
        # free plan 现在包含 CanExport
        ctx = CommerceContext(db, ANONYMOUS_USER_ID, "export")
        assert ctx.check_permission("CanExport") is True

    def test_check_permission_image_gen_free_denied(self, db):
        # CanImageGen 不在 free plan
        ctx = CommerceContext(db, ANONYMOUS_USER_ID, "tts_synthesis")
        assert ctx.check_permission("CanImageGen") is False


class TestCommerceContextReserve:
    def test_reserve_deducts_balance(self, db):
        add_credits(db, ANONYMOUS_USER_ID, 100, "subscription", "test")
        ctx = CommerceContext(db, ANONYMOUS_USER_ID, "transcription",
                              quality_tier="standard", plan_id="free")
        initial = get_balance(db, ANONYMOUS_USER_ID)["total"]
        ctx.reserve({"duration_seconds": 60})
        assert get_balance(db, ANONYMOUS_USER_ID)["total"] < initial

    def test_reserve_free_capability_no_deduction(self, db):
        """romanize_zh（local provider）reserve 0 credits，余额不变"""
        add_credits(db, ANONYMOUS_USER_ID, 100, "subscription", "test")
        ctx = CommerceContext(db, ANONYMOUS_USER_ID, "romanize",
                              quality_tier="standard", plan_id="free")
        initial = get_balance(db, ANONYMOUS_USER_ID)["total"]
        ctx.reserve({})   # zh romanize → fixed_amount=0, min_credits=0
        assert get_balance(db, ANONYMOUS_USER_ID)["total"] == initial
        assert ctx._reservation_id is None

    def test_reserve_insufficient_raises(self, db):
        # anonymous 默认 0 credits
        ctx = CommerceContext(db, ANONYMOUS_USER_ID, "transcription",
                              quality_tier="standard", plan_id="free")
        with pytest.raises(InsufficientFundsError):
            ctx.reserve({"duration_seconds": 300})


class TestCommerceContextSettle:
    def test_settle_writes_usage_log(self, db):
        ctx = _funded_ctx(db, "transcription")
        ctx.reserve({"duration_seconds": 60})
        ctx.settle({"duration_seconds": 60}, "groq", "whisper-large-v3", 3000)
        assert ctx.log_id is not None
        log = get_log(db, ctx.log_id)
        assert log["capability"] == "transcription"
        assert log["provider_id"] == "groq"
        assert log["status"] == "success"
        assert log["latency_ms"] == 3000

    def test_settle_confirms_reservation(self, db):
        ctx = _funded_ctx(db, "transcription")
        ctx.reserve({"duration_seconds": 60})
        rid = ctx._reservation_id
        ctx.settle({"duration_seconds": 60}, "groq", "whisper-large-v3", 3000)
        # reservation 应被 confirm，不能再 release
        from commerce.wallet import release, ReservationNotFoundError
        with pytest.raises(ReservationNotFoundError):
            release(db, rid)

    def test_settle_logs_cost_usd(self, db):
        ctx = _funded_ctx(db, "transcription")
        ctx.reserve({"duration_seconds": 120})
        ctx.settle({"duration_seconds": 120}, "groq", "whisper-large-v3", 5000)
        log = get_log(db, ctx.log_id)
        assert log["provider_cost_usd"] > 0

    def test_settle_free_capability_no_wallet_change(self, db):
        """export（0 credits）settle 后余额不变"""
        add_credits(db, ANONYMOUS_USER_ID, 100, "subscription", "test")
        ctx = CommerceContext(db, ANONYMOUS_USER_ID, "export",
                              quality_tier="standard", plan_id="free")
        ctx.reserve({})
        initial = get_balance(db, ANONYMOUS_USER_ID)["total"]
        ctx.settle({}, "local", "ffmpeg", 500)
        assert get_balance(db, ANONYMOUS_USER_ID)["total"] == initial


class TestCommerceContextReleaseOnError:
    def test_release_restores_balance(self, db):
        add_credits(db, ANONYMOUS_USER_ID, 100, "subscription", "test")
        ctx = CommerceContext(db, ANONYMOUS_USER_ID, "transcription",
                              quality_tier="standard", plan_id="free")
        initial = get_balance(db, ANONYMOUS_USER_ID)["total"]
        ctx.reserve({"duration_seconds": 60})
        ctx.release_on_error(Exception("provider timeout"))
        assert get_balance(db, ANONYMOUS_USER_ID)["total"] == initial

    def test_release_writes_failed_log(self, db):
        add_credits(db, ANONYMOUS_USER_ID, 100, "subscription", "test")
        ctx = CommerceContext(db, ANONYMOUS_USER_ID, "transcription",
                              quality_tier="standard", plan_id="free")
        ctx.reserve({"duration_seconds": 60})
        ctx.release_on_error(ValueError("api error"))
        log = get_log(db, ctx.log_id)
        assert log["status"] == "failed"
        assert log["error_code"] == "ValueError"
        assert log["credits_charged"] == 0

    def test_release_free_capability_no_error(self, db):
        """免费操作（reservation_id=None）release 不报错"""
        ctx = CommerceContext(db, ANONYMOUS_USER_ID, "romanize",
                              quality_tier="standard", plan_id="free")
        ctx.reserve({})   # min_credits=0
        ctx.release_on_error(Exception("test"))  # 不应抛出异常


class TestCommerceContextGetHandle:
    def test_get_handle_returns_provider_handle(self, db):
        ctx = CommerceContext(db, ANONYMOUS_USER_ID, "transcription")
        handle = ctx.get_handle()
        assert handle.provider_id == "groq"
        assert handle.capability == "transcription"

    def test_get_handle_preferred_provider(self, db):
        ctx = CommerceContext(db, ANONYMOUS_USER_ID, "transcription")
        handle = ctx.get_handle(preferred_provider="azure")
        assert handle.provider_id == "azure"


class TestCommerceContextFullFlow:
    def test_full_flow_transcription(self, db):
        """完整调用链：reserve → settle → 检查 log + wallet"""
        add_credits(db, ANONYMOUS_USER_ID, 500, "subscription", "test")
        initial = get_balance(db, ANONYMOUS_USER_ID)["total"]

        ctx = CommerceContext(db, ANONYMOUS_USER_ID, "transcription",
                              quality_tier="standard", plan_id="free",
                              extra={"video": "test.mp4"})
        assert ctx.check_permission("CanTranscribe")
        ctx.reserve({"duration_seconds": 90})
        assert get_balance(db, ANONYMOUS_USER_ID)["total"] < initial

        ctx.settle({"duration_seconds": 90}, "groq", "whisper-large-v3", 4500)
        assert get_balance(db, ANONYMOUS_USER_ID)["total"] < initial  # credits 已扣

        log = get_log(db, ctx.log_id)
        assert log["status"] == "success"
        assert log["credits_reserved"] > 0
        assert log["extra_json"] is not None

    def test_full_flow_error_recovers_balance(self, db):
        """错误路径：reserve → release → wallet 完全恢复"""
        add_credits(db, ANONYMOUS_USER_ID, 500, "subscription", "test")
        initial = get_balance(db, ANONYMOUS_USER_ID)["total"]

        ctx = CommerceContext(db, ANONYMOUS_USER_ID, "translation",
                              quality_tier="standard", plan_id="free")
        ctx.check_permission("CanTranslate")
        ctx.reserve({"char_count": 1000})
        ctx.release_on_error(RuntimeError("deepseek unavailable"))

        assert get_balance(db, ANONYMOUS_USER_ID)["total"] == initial
        assert get_log(db, ctx.log_id)["status"] == "failed"

    def test_summary_after_multiple_calls(self, db):
        """多次调用后 get_summary 正确汇总"""
        add_credits(db, ANONYMOUS_USER_ID, 500, "subscription", "test")

        for _ in range(3):
            ctx = CommerceContext(db, ANONYMOUS_USER_ID, "transcription",
                                  quality_tier="standard", plan_id="free")
            ctx.reserve({"duration_seconds": 60})
            ctx.settle({"duration_seconds": 60}, "groq", "whisper-large-v3", 3000)

        summary = get_summary(db, ANONYMOUS_USER_ID)
        assert summary["by_capability"].get("transcription", 0) > 0
        assert summary["by_provider"].get("groq", 0) > 0
