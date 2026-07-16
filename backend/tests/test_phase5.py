"""
Phase 5 测试：对账 + Rate Limiter + 月末 Cron
pytest backend/tests/test_phase5.py
"""
import datetime
import sys
from unittest.mock import MagicMock

# Mock boto3/botocore for app import
for _mod in ("boto3", "botocore", "botocore.config"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

import pytest

from commerce.db import init_db, _local as _db_local
from commerce.seed import run_seed
from commerce.identity import (
    get_or_create_anonymous, create_user, set_user_subscription, ANONYMOUS_USER_ID,
)
from commerce.wallet import add_credits, get_balance
from commerce import usage_log as _log
from commerce.middleware import CommerceContext

from app import app as flask_app


TEST_ADMIN_KEY = "test-admin-key-5"


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    conn = init_db(":memory:")
    run_seed(conn)
    get_or_create_anonymous(conn)
    yield conn
    conn.close()


@pytest.fixture
def client(db, monkeypatch):
    import config.settings as _settings
    monkeypatch.setattr(_settings, "ADMIN_KEY", TEST_ADMIN_KEY)
    _db_local.conn = db
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c
    _db_local.conn = None


def _auth():
    return {"X-Admin-Key": TEST_ADMIN_KEY}


def _make_success_log(db, capability="transcription", credits=10,
                      provider="groq", model="whisper-large-v3"):
    return _log.record(
        db,
        user_id=ANONYMOUS_USER_ID,
        capability=capability,
        quality_tier="standard",
        provider_id=provider,
        model_id=model,
        plan_id="free",
        input_units=60.0,
        input_unit_type="seconds",
        provider_cost_usd=0.003,
        credits_reserved=credits,
        credits_charged=credits,
        latency_ms=2000,
        status="success",
    )


# ══════════ Task 5.1：对账机制 ═══════════════════════════════════════════════

class TestReconcileLogic:
    def test_empty_db_is_ok(self, db):
        from commerce.reconcile import run_reconciliation
        result = run_reconciliation(db, since_days=1)
        assert result["ok"] is True
        assert result["usage_total"] == 0
        assert result["wallet_total"] == 0
        assert result["discrepancy"] == 0

    def test_balanced_settle_is_ok(self, db):
        """reserve → confirm 后，usage_log 与 wallet_transactions 应对齐"""
        from commerce.reconcile import run_reconciliation
        add_credits(db, ANONYMOUS_USER_ID, 500, "subscription", "test")

        ctx = CommerceContext(db, ANONYMOUS_USER_ID, "transcription",
                              quality_tier="standard", plan_id="free")
        ctx.reserve({"duration_seconds": 60})
        ctx.settle({"duration_seconds": 60}, "groq", "whisper-large-v3", 2000)

        result = run_reconciliation(db, since_days=1)
        assert result["ok"] is True
        assert result["usage_total"] > 0
        assert result["wallet_total"] == result["usage_total"]
        assert result["discrepancy"] == 0

    def test_discrepancy_detected(self, db):
        """手动写入不匹配的日志，应触发 NOT OK"""
        from commerce.reconcile import run_reconciliation

        # usage_log 有 50 credits，但没有对应的 wallet confirm tx
        _log.record(
            db,
            user_id=ANONYMOUS_USER_ID,
            capability="transcription",
            quality_tier="standard",
            provider_id="groq",
            model_id="whisper-large-v3",
            plan_id="free",
            credits_reserved=50,
            credits_charged=50,
            latency_ms=1000,
            status="success",
        )

        result = run_reconciliation(db, since_days=1)
        assert result["ok"] is False
        assert result["usage_total"] == 50
        assert result["wallet_total"] == 0
        assert result["discrepancy"] == 50
        assert result["discrepancy_ratio"] > 0

    def test_failed_logs_excluded(self, db):
        """failed 状态的 usage_log 不计入对账"""
        from commerce.reconcile import run_reconciliation

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
        )
        result = run_reconciliation(db, since_days=1)
        assert result["ok"] is True
        assert result["usage_total"] == 0

    def test_result_has_all_fields(self, db):
        from commerce.reconcile import run_reconciliation
        result = run_reconciliation(db, since_days=7)
        for key in ("since", "since_days", "usage_total", "wallet_total",
                    "discrepancy", "discrepancy_ratio", "ok", "message"):
            assert key in result

    def test_since_days_parameter(self, db):
        from commerce.reconcile import run_reconciliation
        r = run_reconciliation(db, since_days=30)
        assert r["since_days"] == 30

    def test_threshold_exactly_zero_percent_ok(self, db):
        """0% 差异总是 ok"""
        from commerce.reconcile import run_reconciliation
        result = run_reconciliation(db, since_days=1)
        assert result["ok"] is True
        assert result["discrepancy_ratio"] == 0.0

    def test_multiple_settles_balanced(self, db):
        from commerce.reconcile import run_reconciliation
        add_credits(db, ANONYMOUS_USER_ID, 500, "subscription", "test")
        for _ in range(3):
            ctx = CommerceContext(db, ANONYMOUS_USER_ID, "transcription",
                                  quality_tier="standard", plan_id="free")
            ctx.reserve({"duration_seconds": 30})
            ctx.settle({"duration_seconds": 30}, "groq", "whisper-large-v3", 1000)
        result = run_reconciliation(db, since_days=1)
        assert result["ok"] is True
        assert result["discrepancy"] == 0


class TestReconcileAdminAPI:
    def test_reconcile_route_ok(self, client):
        r = client.get(f"/api/admin/commerce/reconcile", headers=_auth())
        assert r.status_code == 200
        body = r.get_json()
        assert body["ok"] is True

    def test_reconcile_route_requires_auth(self, client):
        r = client.get("/api/admin/commerce/reconcile")
        assert r.status_code == 403

    def test_reconcile_days_param(self, client):
        r = client.get("/api/admin/commerce/reconcile?days=7", headers=_auth())
        assert r.get_json()["since_days"] == 7

    def test_reconcile_discrepancy_returns_409(self, client, db):
        # inject an imbalanced log
        _log.record(
            db,
            user_id=ANONYMOUS_USER_ID,
            capability="transcription",
            quality_tier="standard",
            provider_id="groq",
            model_id="whisper-large-v3",
            plan_id="free",
            credits_reserved=100,
            credits_charged=100,
            latency_ms=1000,
            status="success",
        )
        r = client.get("/api/admin/commerce/reconcile?days=1", headers=_auth())
        assert r.status_code == 409
        assert r.get_json()["ok"] is False


# ══════════ Task 5.2：Rate Limiter ═══════════════════════════════════════════

@pytest.fixture(autouse=False)
def clean_rate_limits():
    """每个 rate_limit 测试前后清空计数器"""
    from commerce.rate_limit import reset_all
    reset_all()
    yield
    reset_all()


class TestRateLimitLogic:
    def test_free_transcription_allowed_within_limit(self, clean_rate_limits):
        from commerce.rate_limit import check_rate_limit
        assert check_rate_limit("user1", "transcription", "free") is True

    def test_free_transcription_blocked_after_limit(self, clean_rate_limits):
        from commerce.rate_limit import check_rate_limit, increment
        for _ in range(3):
            increment("user1", "transcription")
        assert check_rate_limit("user1", "transcription", "free") is False

    def test_free_tts_limit_is_2(self, clean_rate_limits):
        from commerce.rate_limit import check_rate_limit, increment
        increment("user1", "tts_synthesis")
        assert check_rate_limit("user1", "tts_synthesis", "free") is True
        increment("user1", "tts_synthesis")
        assert check_rate_limit("user1", "tts_synthesis", "free") is False

    def test_free_pronunciation_limit_is_5(self, clean_rate_limits):
        from commerce.rate_limit import check_rate_limit, increment, get_limit
        assert get_limit("pronunciation", "free") == 5
        for _ in range(5):
            increment("user1", "pronunciation")
        assert check_rate_limit("user1", "pronunciation", "free") is False

    def test_plus_user_unlimited(self, clean_rate_limits):
        from commerce.rate_limit import check_rate_limit, increment, get_limit
        assert get_limit("transcription", "plus") is None
        for _ in range(100):
            increment("user1", "transcription")
        assert check_rate_limit("user1", "transcription", "plus") is True

    def test_pro_user_unlimited(self, clean_rate_limits):
        from commerce.rate_limit import check_rate_limit
        assert check_rate_limit("user1", "transcription", "pro") is True

    def test_different_users_independent(self, clean_rate_limits):
        from commerce.rate_limit import check_rate_limit, increment
        for _ in range(3):
            increment("user_a", "transcription")
        assert check_rate_limit("user_a", "transcription", "free") is False
        assert check_rate_limit("user_b", "transcription", "free") is True

    def test_different_capabilities_independent(self, clean_rate_limits):
        from commerce.rate_limit import check_rate_limit, increment
        for _ in range(3):
            increment("user1", "transcription")
        assert check_rate_limit("user1", "transcription", "free") is False
        assert check_rate_limit("user1", "pronunciation", "free") is True

    def test_non_limited_capability_always_allowed(self, clean_rate_limits):
        from commerce.rate_limit import check_rate_limit, get_limit
        # translation is not in the rate-limit table
        assert get_limit("translation", "free") is None
        assert check_rate_limit("user1", "translation", "free") is True

    def test_increment_returns_count(self, clean_rate_limits):
        from commerce.rate_limit import increment
        assert increment("user1", "transcription") == 1
        assert increment("user1", "transcription") == 2
        assert increment("user1", "transcription") == 3

    def test_get_usage_returns_count(self, clean_rate_limits):
        from commerce.rate_limit import increment, get_usage
        assert get_usage("user1", "pronunciation") == 0
        increment("user1", "pronunciation")
        increment("user1", "pronunciation")
        assert get_usage("user1", "pronunciation") == 2

    def test_reset_all_clears_counters(self, clean_rate_limits):
        from commerce.rate_limit import increment, get_usage, reset_all
        increment("user1", "transcription")
        reset_all()
        assert get_usage("user1", "transcription") == 0


class TestRateLimitAPI:
    def test_rate_limits_route_returns_200(self, client, clean_rate_limits):
        r = client.get("/api/user/rate-limits")
        assert r.status_code == 200

    def test_rate_limits_structure(self, client, clean_rate_limits):
        r = client.get("/api/user/rate-limits")
        body = r.get_json()
        assert "plan" in body
        assert "rate_limits" in body

    def test_rate_limits_shows_free_caps(self, client, clean_rate_limits):
        r = client.get("/api/user/rate-limits")
        rl = r.get_json()["rate_limits"]
        assert "transcription" in rl
        assert "tts_synthesis" in rl
        assert "pronunciation" in rl

    def test_rate_limits_remaining_decreases(self, client, clean_rate_limits):
        from commerce.rate_limit import increment
        increment(ANONYMOUS_USER_ID, "transcription")
        increment(ANONYMOUS_USER_ID, "transcription")
        r = client.get("/api/user/rate-limits")
        rl = r.get_json()["rate_limits"]["transcription"]
        assert rl["used"] == 2
        assert rl["remaining"] == 1

    def test_rate_limits_no_auth_required(self, client, clean_rate_limits):
        r = client.get("/api/user/rate-limits")
        assert r.status_code == 200


# ══════════ Task 5.3：月末 Credits 重置 ══════════════════════════════════════

class TestCronResetLogic:
    def test_empty_db_no_error(self, db):
        from commerce.cron import reset_month_credits
        result = reset_month_credits(db)
        assert result["expired_subscription"] == 0
        assert result["renewed"] == 0
        assert result["expired_gift"] == 0

    def test_result_has_required_fields(self, db):
        from commerce.cron import reset_month_credits
        result = reset_month_credits(db)
        for key in ("expired_subscription", "renewed", "expired_gift", "ran_at"):
            assert key in result

    def test_expired_subscription_credits_cleared(self, db):
        from commerce.cron import reset_month_credits
        # Set subscription_credits with an already-expired expiry
        add_credits(db, ANONYMOUS_USER_ID, 200, "subscription", "test",
                    expires_at="2000-01-01 00:00:00")
        assert get_balance(db, ANONYMOUS_USER_ID)["subscription"] == 200

        result = reset_month_credits(db)
        assert result["expired_subscription"] >= 1
        assert get_balance(db, ANONYMOUS_USER_ID)["subscription"] == 0

    def test_active_subscription_not_cleared(self, db):
        from commerce.cron import reset_month_credits
        # Future expiry — should not be cleared
        future = (datetime.datetime.utcnow() + datetime.timedelta(days=30)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        add_credits(db, ANONYMOUS_USER_ID, 300, "subscription", "test",
                    expires_at=future)
        reset_month_credits(db)
        assert get_balance(db, ANONYMOUS_USER_ID)["subscription"] == 300

    def test_renew_active_subscription(self, db):
        from commerce.cron import reset_month_credits
        # Create user with active plus subscription (expiry in future)
        uid = create_user(db)
        future = (datetime.datetime.utcnow() + datetime.timedelta(days=30)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        set_user_subscription(db, uid, "plus", future, credits_quota=1000)

        # Simulate: credits_reset_at in previous month so cron will renew
        last_month = (datetime.datetime.utcnow() - datetime.timedelta(days=35)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        db.execute(
            "UPDATE user_subscriptions SET credits_reset_at = ? WHERE user_id = ?",
            (last_month, uid),
        )
        # Zero out their credits (simulate month-end depletion)
        db.execute(
            "UPDATE wallets SET subscription_credits = 0 WHERE user_id = ?", (uid,)
        )
        db.commit()

        result = reset_month_credits(db)
        assert result["renewed"] >= 1
        # After renewal, balance should be restored to quota
        assert get_balance(db, uid)["subscription"] == 1000

    def test_expired_gift_credits_cleared(self, db):
        from commerce.cron import reset_month_credits
        # Add gift credits with already-expired expiry
        expired_at = "2000-06-01 00:00:00"
        add_credits(db, ANONYMOUS_USER_ID, 50, "gift", "test", expires_at=expired_at)
        assert get_balance(db, ANONYMOUS_USER_ID)["gift"] == 50

        result = reset_month_credits(db)
        assert result["expired_gift"] >= 1
        assert get_balance(db, ANONYMOUS_USER_ID)["gift"] == 0

    def test_active_gift_credits_not_cleared(self, db):
        from commerce.cron import reset_month_credits
        # Add gift credits with future expiry
        future = (datetime.datetime.utcnow() + datetime.timedelta(days=15)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        add_credits(db, ANONYMOUS_USER_ID, 75, "gift", "test", expires_at=future)
        reset_month_credits(db)
        assert get_balance(db, ANONYMOUS_USER_ID)["gift"] == 75

    def test_gift_credits_default_30day_expiry(self, db):
        """add_credits(gift) without explicit expires_at defaults to +30 days"""
        add_credits(db, ANONYMOUS_USER_ID, 100, "gift", "test")
        row = db.execute(
            "SELECT gift_expires_at FROM wallets WHERE user_id = ?",
            (ANONYMOUS_USER_ID,),
        ).fetchone()
        assert row["gift_expires_at"] is not None
        exp = datetime.datetime.strptime(row["gift_expires_at"], "%Y-%m-%d %H:%M:%S")
        assert exp > datetime.datetime.utcnow()

    def test_seconds_until_next_month_positive(self):
        from commerce.cron import _seconds_until_next_month
        secs = _seconds_until_next_month()
        assert secs >= 60  # at least 60 seconds (clamped minimum)
        assert secs <= 31 * 24 * 3600  # at most one month


class TestCronThread:
    def test_start_cron_returns_thread(self, db):
        from commerce.cron import start_cron
        calls = []

        def fake_db_factory():
            calls.append(1)
            return db

        t = start_cron(fake_db_factory)
        assert t.daemon is True
        assert t.is_alive()
        t.join(timeout=0)   # non-blocking, just check it started
