"""
Phase 2 测试：Permission Engine + AI Router
pytest backend/tests/test_phase2.py
"""
import pytest

from commerce.db import init_db
from commerce.seed import run_seed
from commerce.identity import create_user, set_user_subscription
from commerce.plan import get_default_quality
from commerce.permission import (
    check, check_all, get_user_permissions,
    grant, revoke, ALL_PERMISSIONS,
)
from commerce.router import route, with_fallback, ProviderHandle


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    conn = init_db(":memory:")
    run_seed(conn)
    yield conn
    conn.close()


def _user_with_plan(db, plan_id: str, credits: int = 0) -> str:
    uid = create_user(db)
    if plan_id != "free":
        set_user_subscription(db, uid, plan_id, "2099-12-31 00:00:00", credits)
    return uid


# ── Task 2.1：Permission Engine ───────────────────────────────────────────────

class TestPermissionPlanBased:
    def test_free_user_can_transcribe(self, db):
        uid = _user_with_plan(db, "free")
        assert check(db, uid, "CanTranscribe") is True

    def test_free_user_can_ocr(self, db):
        uid = _user_with_plan(db, "free")
        assert check(db, uid, "CanOCR") is True

    def test_free_user_can_translate(self, db):
        uid = _user_with_plan(db, "free")
        assert check(db, uid, "CanTranslate") is True

    def test_free_user_can_tts(self, db):
        uid = _user_with_plan(db, "free")
        assert check(db, uid, "CanTTS") is True

    def test_free_user_can_pronunciation(self, db):
        uid = _user_with_plan(db, "free")
        assert check(db, uid, "CanPronunciationAssess") is True

    def test_free_user_cannot_image_gen(self, db):
        uid = _user_with_plan(db, "free")
        assert check(db, uid, "CanImageGen") is False

    def test_plus_user_can_tts(self, db):
        uid = _user_with_plan(db, "plus", 1000)
        assert check(db, uid, "CanTTS") is True

    def test_plus_user_can_romanize(self, db):
        uid = _user_with_plan(db, "plus", 1000)
        assert check(db, uid, "CanRomanize") is True

    def test_plus_user_cannot_image_gen(self, db):
        uid = _user_with_plan(db, "plus", 1000)
        assert check(db, uid, "CanImageGen") is False

    def test_pro_user_has_all_permissions(self, db):
        uid = _user_with_plan(db, "pro", 5000)
        for perm in ALL_PERMISSIONS:
            assert check(db, uid, perm) is True, f"pro user missing {perm}"

    def test_enterprise_user_has_all_permissions(self, db):
        uid = _user_with_plan(db, "enterprise", 50000)
        assert check(db, uid, "CanImageGen") is True
        assert check(db, uid, "CanProcessLongVideo") is True

    def test_default_quality_is_plan_bound(self):
        assert get_default_quality("free") == "economy"
        assert get_default_quality("plus") == "standard"
        assert get_default_quality("pro") == "premium"
        assert get_default_quality("enterprise") == "premium"


class TestPermissionManualGrant:
    def test_manual_grant_overrides_plan(self, db):
        uid = _user_with_plan(db, "free")
        assert check(db, uid, "CanImageGen") is False
        grant(db, uid, "CanImageGen")
        assert check(db, uid, "CanImageGen") is True

    def test_grant_with_expiry_respected(self, db):
        uid = _user_with_plan(db, "free")
        grant(db, uid, "CanImageGen", expires_at="2000-01-01 00:00:00")  # 已过期
        assert check(db, uid, "CanImageGen") is False

    def test_grant_never_expires_when_none(self, db):
        uid = _user_with_plan(db, "free")
        grant(db, uid, "CanOCR", expires_at=None)
        assert check(db, uid, "CanOCR") is True

    def test_revoke_removes_manual_grant(self, db):
        uid = _user_with_plan(db, "free")
        grant(db, uid, "CanImageGen")
        revoke(db, uid, "CanImageGen")
        assert check(db, uid, "CanImageGen") is False

    def test_revoke_plan_permission_has_no_effect(self, db):
        """revoke 只能撤手动授权；套餐权限不受影响"""
        uid = _user_with_plan(db, "plus", 1000)
        assert check(db, uid, "CanTTS") is True
        revoke(db, uid, "CanTTS")         # 没有手动授权可撤
        assert check(db, uid, "CanTTS") is True   # 套餐权限仍有效

    def test_grant_unknown_permission_raises(self, db):
        uid = _user_with_plan(db, "free")
        with pytest.raises(ValueError):
            grant(db, uid, "CanDoAnything")

    def test_grant_overwrite_existing(self, db):
        """重复 grant 同一权限（新 expires_at）不会报错"""
        uid = _user_with_plan(db, "free")
        grant(db, uid, "CanOCR", expires_at="2099-01-01 00:00:00")
        grant(db, uid, "CanOCR", expires_at="2099-06-01 00:00:00")  # 覆盖
        assert check(db, uid, "CanOCR") is True


class TestPermissionBatch:
    def test_check_all_mixed_results(self, db):
        uid = _user_with_plan(db, "plus", 1000)
        result = check_all(db, uid, ["CanTranscribe", "CanTTS", "CanImageGen"])
        assert result["CanTranscribe"] is True
        assert result["CanTTS"] is True
        assert result["CanImageGen"] is False

    def test_get_user_permissions_includes_plan_and_grants(self, db):
        uid = _user_with_plan(db, "free")
        grant(db, uid, "CanOCR")
        perms = get_user_permissions(db, uid)
        assert "CanTranscribe" in perms    # from plan
        assert "CanTranslate"  in perms    # from plan
        assert "CanOCR"        in perms    # manual grant
        assert "CanImageGen"   not in perms  # not in free plan, not granted

    def test_check_all_empty_list(self, db):
        uid = _user_with_plan(db, "free")
        assert check_all(db, uid, []) == {}


# ── Task 2.2：AI Router ───────────────────────────────────────────────────────

class TestRouterBasic:
    def test_route_transcription_default_groq(self):
        handle = route("transcription", "standard", "plus")
        assert handle.provider_id == "groq"
        assert handle.capability == "transcription"
        assert not handle.is_composite

    def test_route_translation_default_deepseek(self):
        handle = route("translation", "standard", "plus")
        assert handle.provider_id == "deepseek"

    def test_route_tts_standard_gemini(self):
        handle = route("tts_synthesis", "standard", "plus")
        assert handle.provider_id == "gemini"

    def test_route_pronunciation_azure_only(self):
        handle = route("pronunciation", "standard", "plus")
        assert handle.provider_id == "azure"

    def test_route_export_local(self):
        handle = route("export", "standard", "free")
        assert handle.provider_id == "local"

    def test_route_premium_transcription_azure_first(self):
        handle = route("transcription", "premium", "pro")
        assert handle.provider_id == "azure"

    def test_route_handle_has_timeout(self):
        handle = route("transcription", "standard", "plus")
        assert handle.timeout > 0

    def test_route_handle_has_model_id(self):
        handle = route("transcription", "standard", "plus")
        assert handle.model_id == "whisper-large-v3"

    def test_route_tts_synthesis_gemini_uses_tts_model(self):
        handle = route("tts_synthesis", "standard", "plus")
        assert handle.provider_id == "gemini"
        assert handle.model_id == "gemini-3.1-flash-tts"

    def test_route_tts_synthesis_azure_uses_tts_model(self):
        handle = route("tts_synthesis", "economy", "plus")
        assert handle.provider_id == "azure"
        assert handle.model_id == "azure-tts-neural"


class TestRouterPreferred:
    def test_preferred_provider_overrides_default(self):
        handle = route("transcription", "standard", "plus", preferred_provider="azure")
        assert handle.provider_id == "azure"

    def test_preferred_provider_in_candidates_reorders(self):
        # azure 本来是 fallback，preferred 后应成为首选
        handle = route("transcription", "standard", "plus", preferred_provider="azure")
        assert handle.provider_id == "azure"
        # groq 应该变成 fallback
        fallback = with_fallback(handle, Exception("test"))
        assert fallback is not None
        assert fallback.provider_id == "groq"

    def test_preferred_provider_not_in_table_still_works(self):
        handle = route("transcription", "standard", "plus", preferred_provider="openai")
        assert handle.provider_id == "openai"

    def test_combined_returns_composite(self):
        handle = route("transcription", "standard", "plus", preferred_provider="combined")
        assert handle.is_composite is True
        assert len(handle.sub_handles) == 2
        assert handle.sub_handles[0].provider_id == "groq"
        assert handle.sub_handles[1].provider_id == "azure"

    def test_composite_has_no_credits_field(self):
        """ProviderHandle 不持有定价信息"""
        handle = route("translation", "standard", "plus")
        assert not hasattr(handle, "credits")
        assert not hasattr(handle, "estimated_cost")


class TestRouterFallback:
    def test_with_fallback_returns_next(self):
        handle = route("translation", "standard", "plus")   # deepseek
        assert handle.provider_id == "deepseek"
        fallback = with_fallback(handle, Exception("timeout"))
        assert fallback is not None
        assert fallback.provider_id == "gemini"

    def test_with_fallback_no_more_returns_none(self):
        handle = route("pronunciation", "standard", "plus")   # azure（唯一）
        fallback = with_fallback(handle, Exception("error"))
        assert fallback is None

    def test_with_fallback_chain_exhaustion(self):
        handle = route("translation", "standard", "plus")   # deepseek → gemini
        fb1 = with_fallback(handle, Exception("err1"))
        assert fb1.provider_id == "gemini"
        fb2 = with_fallback(fb1, Exception("err2"))
        assert fb2 is None

    def test_composite_has_no_fallback(self):
        handle = route("transcription", "standard", "plus", preferred_provider="combined")
        fallback = with_fallback(handle, Exception("error"))
        assert fallback is None

    def test_fallback_capability_preserved(self):
        handle = route("translation", "standard", "plus")
        fallback = with_fallback(handle, Exception("err"))
        assert fallback.capability == handle.capability


class TestRouterProviderTransparency:
    def test_router_does_not_hold_pricing(self):
        """Router 只管路由，Credits 由 Pricing Engine 按 capability 决定"""
        from commerce.pricing import estimate_credits

        h_groq = route("transcription", "standard", "plus")
        h_azure = route("transcription", "standard", "plus", preferred_provider="azure")

        # 两个 handle 指向不同 Provider，但 capability 相同
        assert h_groq.capability == h_azure.capability == "transcription"
        # Credits 估算与 provider 无关（provider_id 不参与 estimate）
        db = init_db(":memory:")
        run_seed(db)
        c1 = estimate_credits(db, "transcription", "standard", "plus",
                               {"duration_seconds": 120})
        c2 = estimate_credits(db, "transcription", "standard", "plus",
                               {"duration_seconds": 120})
        assert c1 == c2
        db.close()
