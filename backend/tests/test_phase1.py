"""
Phase 1 测试：Wallet + Pricing Engine + Usage Log
pytest backend/tests/test_phase1.py
"""
import threading
import pytest

from commerce.db import init_db
from commerce.seed import run_seed
from commerce.identity import create_user, get_or_create_anonymous
from commerce.wallet import (
    get_or_create_wallet, get_balance,
    reserve, confirm, release,
    add_credits, refund, get_history,
    InsufficientFundsError, WalletNotFoundError, ReservationNotFoundError,
)
from commerce.pricing import estimate_credits, calculate_credits
from commerce.usage_log import record, get_log, get_user_history, get_summary


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    conn = init_db(":memory:")
    run_seed(conn)
    yield conn
    conn.close()


def _user_with_credits(db, sub=0, gift=0, paid=0) -> str:
    """创建用户并充值指定 credits，返回 user_id。"""
    uid = create_user(db)
    if sub:
        add_credits(db, uid, sub, "subscription", "test-setup")
    if gift:
        add_credits(db, uid, gift, "gift", "test-setup")
    if paid:
        add_credits(db, uid, paid, "paid", "test-setup")
    return uid


# ── Task 1.1：Wallet ─────────────────────────────────────────────────────────

class TestWalletBalance:
    def test_initial_balance_all_zero(self, db):
        uid = create_user(db)
        bal = get_balance(db, uid)
        assert bal == {"subscription": 0, "gift": 0, "paid": 0, "total": 0}

    def test_add_subscription_credits(self, db):
        uid = create_user(db)
        add_credits(db, uid, 100, "subscription", "monthly-reset")
        bal = get_balance(db, uid)
        assert bal["subscription"] == 100
        assert bal["total"] == 100

    def test_add_gift_credits(self, db):
        uid = create_user(db)
        add_credits(db, uid, 50, "gift", "promo")
        assert get_balance(db, uid)["gift"] == 50

    def test_add_paid_credits(self, db):
        uid = create_user(db)
        add_credits(db, uid, 200, "paid", "stripe-order-123")
        assert get_balance(db, uid)["paid"] == 200

    def test_wallet_not_found_raises(self, db):
        with pytest.raises(WalletNotFoundError):
            get_balance(db, "nonexistent-user")


class TestWalletReserve:
    def test_reserve_deducts_subscription_first(self, db):
        uid = _user_with_credits(db, sub=100, gift=50, paid=200)
        reserve(db, uid, 80)
        bal = get_balance(db, uid)
        assert bal["subscription"] == 20
        assert bal["gift"] == 50
        assert bal["paid"] == 200

    def test_reserve_crosses_to_gift_when_sub_insufficient(self, db):
        uid = _user_with_credits(db, sub=10, gift=50, paid=0)
        reserve(db, uid, 30)
        bal = get_balance(db, uid)
        assert bal["subscription"] == 0
        assert bal["gift"] == 30   # 50 - 20（补足 sub 用完后的差额）

    def test_reserve_crosses_all_credit_types(self, db):
        uid = _user_with_credits(db, sub=5, gift=5, paid=100)
        reserve(db, uid, 20)
        bal = get_balance(db, uid)
        assert bal["subscription"] == 0
        assert bal["gift"] == 0
        assert bal["paid"] == 90   # 100 - 10

    def test_reserve_insufficient_raises(self, db):
        uid = _user_with_credits(db, sub=5)
        with pytest.raises(InsufficientFundsError):
            reserve(db, uid, 10)

    def test_reserve_exact_amount(self, db):
        uid = _user_with_credits(db, sub=10)
        reserve(db, uid, 10)
        assert get_balance(db, uid)["total"] == 0

    def test_reserve_returns_reservation_id(self, db):
        uid = _user_with_credits(db, sub=100)
        rid = reserve(db, uid, 10)
        assert len(rid) == 36   # UUID


class TestWalletConfirm:
    def test_confirm_marks_reservation_consumed(self, db):
        uid = _user_with_credits(db, sub=100)
        rid = reserve(db, uid, 20)
        confirm(db, rid)
        # balance 已在 reserve 时扣，confirm 后不变
        assert get_balance(db, uid)["subscription"] == 80

    def test_confirm_changes_tx_type(self, db):
        uid = _user_with_credits(db, sub=100)
        rid = reserve(db, uid, 20)
        confirm(db, rid)
        row = db.execute(
            "SELECT tx_type FROM wallet_transactions WHERE tx_id = ?", (rid,)
        ).fetchone()
        assert row["tx_type"] == "confirm"

    def test_confirm_nonexistent_raises(self, db):
        with pytest.raises(ReservationNotFoundError):
            confirm(db, "00000000-0000-0000-0000-000000000000")

    def test_confirm_already_confirmed_raises(self, db):
        uid = _user_with_credits(db, sub=100)
        rid = reserve(db, uid, 10)
        confirm(db, rid)
        with pytest.raises(ReservationNotFoundError):
            confirm(db, rid)   # 重复确认应报错


class TestWalletRelease:
    def test_release_restores_balance(self, db):
        uid = _user_with_credits(db, sub=100)
        rid = reserve(db, uid, 30)
        assert get_balance(db, uid)["subscription"] == 70
        release(db, rid)
        assert get_balance(db, uid)["subscription"] == 100

    def test_release_nonexistent_raises(self, db):
        with pytest.raises(ReservationNotFoundError):
            release(db, "00000000-0000-0000-0000-000000000000")

    def test_release_after_confirm_raises(self, db):
        uid = _user_with_credits(db, sub=100)
        rid = reserve(db, uid, 10)
        confirm(db, rid)
        with pytest.raises(ReservationNotFoundError):
            release(db, rid)   # 已 confirm，不能再 release


class TestWalletRefund:
    def test_refund_adds_gift_credits(self, db):
        uid = _user_with_credits(db, sub=100)
        rid = reserve(db, uid, 20)
        confirm(db, rid)
        log_id = record(
            db, user_id=uid, capability="transcription",
            provider_id="groq", model_id="whisper-large-v3", plan_id="free",
            credits_reserved=20, credits_charged=20,
        )
        refund(db, log_id, 10, "test refund")
        assert get_balance(db, uid)["gift"] == 10

    def test_refund_nonexistent_log_raises(self, db):
        with pytest.raises(ValueError):
            refund(db, "bad-log-id", 10, "test")


class TestWalletConcurrency:
    def test_concurrent_reserve_no_double_spend(self, tmp_path):
        """并发预扣不超发（乐观锁保证）。
        使用文件数据库 + 每线程独立连接，模拟真实多线程 Flask 场景。
        """
        db_path = str(tmp_path / "concurrency_test.db")

        # 初始化数据库并创建用户
        setup_db = init_db(db_path)
        run_seed(setup_db)
        uid = create_user(setup_db)
        add_credits(setup_db, uid, 100, "subscription", "test-setup")
        setup_db.close()

        results = []
        errors = []

        def try_reserve():
            # 每个线程用独立连接（模拟 Flask 线程本地连接）
            conn = init_db(db_path)
            try:
                rid = reserve(conn, uid, 60)
                results.append(rid)
            except InsufficientFundsError:
                errors.append("insufficient")
            except RuntimeError:
                errors.append("retry_exhausted")
            finally:
                conn.close()

        threads = [threading.Thread(target=try_reserve) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 100 credits / 60 per reserve → 至多 1 次成功，至少 2 次失败
        assert len(errors) >= 2

        verify_db = init_db(db_path)
        bal = get_balance(verify_db, uid)
        verify_db.close()
        assert bal["total"] >= 0           # 余额非负
        assert bal["subscription"] <= 100   # 不超发

    def test_history_records_transactions(self, db):
        uid = _user_with_credits(db, sub=100)
        reserve(db, uid, 10)
        history = get_history(db, uid)
        tx_types = [h["tx_type"] for h in history]
        assert "reserve" in tx_types
        assert "add" in tx_types


# ── Task 1.2：Pricing Engine ──────────────────────────────────────────────────

class TestPricing:
    def test_estimate_transcription_minimum_1(self, db):
        """短视频估算至少 1 credit"""
        credits = estimate_credits(
            db, "transcription", "standard", "plus",
            {"duration_seconds": 10},
        )
        assert credits >= 1

    def test_estimate_includes_buffer(self, db):
        """估算值 >= 精确值（含 10% 余量）"""
        exact, _ = calculate_credits(
            db, "transcription", "standard", "plus",
            "groq", "whisper-large-v3", {"duration_seconds": 300},
        )
        estimate = estimate_credits(
            db, "transcription", "standard", "plus",
            {"duration_seconds": 300},
        )
        assert estimate >= exact

    def test_calculate_word_definition_fixed(self, db):
        """word_definition 固定 1 credit"""
        credits, _ = calculate_credits(
            db, "word_definition", "standard", "plus",
            "deepseek", "deepseek-chat", {},
        )
        assert credits == 1

    def test_calculate_export_free(self, db):
        """export 固定 0 credits"""
        credits, cost = calculate_credits(
            db, "export", "standard", "plus",
            "local", "ffmpeg", {},
        )
        assert credits == 0
        assert cost == 0.0

    def test_calculate_romanize_local_free(self, db):
        """romanize 本地 pypinyin 免费"""
        credits, cost = calculate_credits(
            db, "romanize", "standard", "plus",
            "local", "pypinyin", {},
        )
        assert credits == 0
        assert cost == 0.0

    def test_calculate_ocr_fixed_2(self, db):
        """OCR 固定 2 credits"""
        credits, _ = calculate_credits(
            db, "ocr", "standard", "plus",
            "gemini", "gemini-3.1-flash-lite", {},
        )
        assert credits == 2

    def test_provider_transparent_to_user(self, db):
        """同 capability/tier/plan，不同 Provider 的 Credits 相同（Provider 对用户透明）"""
        c_groq, _ = calculate_credits(
            db, "transcription", "economy", "plus",
            "groq", "whisper-large-v3", {"duration_seconds": 60},
        )
        c_azure, _ = calculate_credits(
            db, "transcription", "economy", "plus",
            "azure", "azure-speech", {"duration_seconds": 60},
        )
        assert c_groq == c_azure

    def test_calculate_returns_cost_usd(self, db):
        """精确计算同时返回 cost_usd（供 Usage Log 记录）"""
        _, cost = calculate_credits(
            db, "transcription", "standard", "plus",
            "groq", "whisper-large-v3", {"duration_seconds": 120},
        )
        assert cost > 0.0

    def test_calculate_local_provider_cost_zero(self, db):
        """本地 Provider 成本为 0"""
        _, cost = calculate_credits(
            db, "romanize", "standard", "plus",
            "local", "pypinyin", {},
        )
        assert cost == 0.0

    def test_premium_tier_more_than_standard(self, db):
        """premium tier credits >= standard tier credits"""
        c_std, _  = calculate_credits(
            db, "transcription", "standard", "pro",
            "groq", "whisper-large-v3", {"duration_seconds": 300},
        )
        c_prem, _ = calculate_credits(
            db, "transcription", "premium", "pro",
            "groq", "whisper-large-v3", {"duration_seconds": 300},
        )
        assert c_prem >= c_std


# ── Task 1.3：Usage Log ───────────────────────────────────────────────────────

class TestUsageLog:
    def test_record_returns_log_id(self, db):
        uid = create_user(db)
        log_id = record(
            db, user_id=uid, capability="transcription",
            provider_id="groq", model_id="whisper-large-v3", plan_id="free",
            credits_charged=5,
        )
        assert len(log_id) == 36

    def test_record_can_be_retrieved(self, db):
        uid = create_user(db)
        log_id = record(
            db, user_id=uid, capability="translation",
            provider_id="deepseek", model_id="deepseek-chat", plan_id="plus",
            credits_charged=3,
        )
        log = get_log(db, log_id)
        assert log is not None
        assert log["capability"] == "translation"
        assert log["credits_charged"] == 3

    def test_get_log_nonexistent_returns_none(self, db):
        assert get_log(db, "nonexistent") is None

    def test_record_with_extra_metadata(self, db):
        uid = create_user(db)
        log_id = record(
            db, user_id=uid, capability="transcription",
            provider_id="groq", model_id="whisper-large-v3", plan_id="free",
            extra={"video": "lesson.mp4", "language": "th"},
        )
        log = get_log(db, log_id)
        assert log["extra"]["video"] == "lesson.mp4"

    def test_record_fallback_fields(self, db):
        uid = create_user(db)
        log_id = record(
            db, user_id=uid, capability="translation",
            provider_id="gemini", model_id="gemini-3.1-flash-lite", plan_id="free",
            credits_charged=2, fallback_used=True, fallback_from="deepseek",
        )
        log = get_log(db, log_id)
        assert log["fallback_used"] == 1
        assert log["fallback_from"] == "deepseek"

    def test_summary_aggregates_by_capability(self, db):
        uid = create_user(db)
        record(db, user_id=uid, capability="transcription",
               provider_id="groq", model_id="whisper-large-v3", plan_id="free",
               credits_charged=10)
        record(db, user_id=uid, capability="translation",
               provider_id="deepseek", model_id="deepseek-chat", plan_id="free",
               credits_charged=5)
        record(db, user_id=uid, capability="transcription",
               provider_id="groq", model_id="whisper-large-v3", plan_id="free",
               credits_charged=8)

        summary = get_summary(db, uid)
        assert summary["total_credits"] == 23
        assert summary["by_capability"]["transcription"] == 18
        assert summary["by_capability"]["translation"] == 5

    def test_summary_aggregates_by_provider(self, db):
        uid = create_user(db)
        record(db, user_id=uid, capability="transcription",
               provider_id="groq", model_id="whisper-large-v3", plan_id="free",
               credits_charged=10)
        record(db, user_id=uid, capability="translation",
               provider_id="deepseek", model_id="deepseek-chat", plan_id="free",
               credits_charged=5)

        summary = get_summary(db, uid)
        assert summary["by_provider"]["groq"] == 10
        assert summary["by_provider"]["deepseek"] == 5

    def test_user_history_ordered_by_time(self, db):
        uid = create_user(db)
        for cap in ["transcription", "translation", "ocr"]:
            record(db, user_id=uid, capability=cap,
                   provider_id="groq", model_id="whisper-large-v3", plan_id="free")
        history = get_user_history(db, uid)
        assert history[0]["capability"] == "ocr"   # 最新在前

    def test_summary_excludes_failed_logs(self, db):
        uid = create_user(db)
        record(db, user_id=uid, capability="transcription",
               provider_id="groq", model_id="whisper-large-v3", plan_id="free",
               credits_charged=10, status="success")
        record(db, user_id=uid, capability="transcription",
               provider_id="groq", model_id="whisper-large-v3", plan_id="free",
               credits_charged=5, status="failed")
        summary = get_summary(db, uid)
        assert summary["total_credits"] == 10   # failed 不计入
