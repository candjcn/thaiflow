"""
Phase 0 测试：DB Schema + Identity + Seed
pytest backend/tests/test_phase0.py
"""
import pytest
from commerce.db import init_db
from commerce.identity import (
    create_user, get_user, get_user_plan,
    get_or_create_anonymous, set_user_subscription,
    ANONYMOUS_USER_ID,
)
from commerce.seed import run_seed


# ── 共用 fixture ──────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    conn = init_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def seeded_db(db):
    run_seed(db)
    return db


# ── Task 0.1：Schema ──────────────────────────────────────────────────────────

class TestSchema:
    def test_all_tables_created(self, db):
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        required = {
            "users", "plan_definitions", "user_subscriptions",
            "wallets", "wallet_transactions",
            "provider_costs", "pricing_policies",
            "usage_logs", "permission_grants",
        }
        assert required.issubset(tables)

    def test_unique_wallet_per_user(self, db):
        uid = create_user(db)
        # wallet 已由 create_user 创建，再次插入同一 user_id 应违反 UNIQUE
        with pytest.raises(Exception):
            db.execute(
                "INSERT INTO wallets (wallet_id, user_id) VALUES ('w2', ?)", (uid,)
            )
            db.commit()

    def test_foreign_key_enforced(self, db):
        with pytest.raises(Exception):
            db.execute(
                "INSERT INTO wallets (wallet_id, user_id) VALUES ('w-bad', 'nonexistent')"
            )
            db.commit()

    def test_indexes_exist(self, db):
        indexes = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_usage_logs_user" in indexes
        assert "idx_wallet_tx_wallet" in indexes


# ── Task 0.2：Identity ────────────────────────────────────────────────────────

class TestIdentity:
    def test_create_user_returns_uuid(self, db):
        uid = create_user(db)
        assert len(uid) == 36
        assert uid.count("-") == 4

    def test_create_user_also_creates_wallet(self, db):
        uid = create_user(db)
        row = db.execute(
            "SELECT wallet_id FROM wallets WHERE user_id = ?", (uid,)
        ).fetchone()
        assert row is not None

    def test_create_user_with_email(self, db):
        uid = create_user(db, email="test@example.com")
        user = get_user(db, uid)
        assert user["email"] == "test@example.com"

    def test_get_user_returns_none_for_unknown(self, db):
        assert get_user(db, "not-exist") is None

    def test_get_user_plan_default_free(self, db):
        uid = create_user(db)
        assert get_user_plan(db, uid) == "free"

    def test_get_user_plan_after_subscription(self, db, seeded_db):
        uid = create_user(db)
        set_user_subscription(db, uid, "plus", "2099-12-31 00:00:00", 1000)
        assert get_user_plan(db, uid) == "plus"

    def test_set_subscription_updates_wallet_credits(self, db, seeded_db):
        uid = create_user(db)
        set_user_subscription(db, uid, "plus", "2099-12-31 00:00:00", 1000)
        row = db.execute(
            "SELECT subscription_credits FROM wallets WHERE user_id = ?", (uid,)
        ).fetchone()
        assert row["subscription_credits"] == 1000

    def test_get_or_create_anonymous_idempotent(self, db):
        id1 = get_or_create_anonymous(db)
        id2 = get_or_create_anonymous(db)
        assert id1 == id2 == ANONYMOUS_USER_ID

    def test_anonymous_has_wallet(self, db):
        get_or_create_anonymous(db)
        row = db.execute(
            "SELECT wallet_id FROM wallets WHERE user_id = ?", (ANONYMOUS_USER_ID,)
        ).fetchone()
        assert row is not None


# ── Task 0.3：Seed ────────────────────────────────────────────────────────────

class TestSeed:
    def test_seed_creates_4_plans(self, seeded_db):
        count = seeded_db.execute(
            "SELECT count(*) FROM plan_definitions"
        ).fetchone()[0]
        assert count == 4

    def test_seed_plan_ids_correct(self, seeded_db):
        plans = {
            row[0]
            for row in seeded_db.execute("SELECT plan_id FROM plan_definitions").fetchall()
        }
        assert plans == {"free", "plus", "pro", "enterprise"}

    def test_free_plan_credits(self, seeded_db):
        row = seeded_db.execute(
            "SELECT monthly_credits FROM plan_definitions WHERE plan_id = 'free'"
        ).fetchone()
        assert row["monthly_credits"] == 100

    def test_seed_creates_provider_costs(self, seeded_db):
        count = seeded_db.execute(
            "SELECT count(*) FROM provider_costs"
        ).fetchone()[0]
        assert count > 10

    def test_seed_local_pypinyin_is_free(self, seeded_db):
        row = seeded_db.execute(
            "SELECT unit_price FROM provider_costs WHERE provider_id='local' AND model_id='pypinyin'"
        ).fetchone()
        assert row is not None
        assert row["unit_price"] == 0.0

    def test_seed_creates_pricing_policies(self, seeded_db):
        count = seeded_db.execute(
            "SELECT count(*) FROM pricing_policies"
        ).fetchone()[0]
        assert count > 10

    def test_seed_export_is_free(self, seeded_db):
        row = seeded_db.execute(
            "SELECT fixed_amount, min_credits FROM pricing_policies WHERE capability='export'"
        ).fetchone()
        assert row is not None
        assert row["fixed_amount"] == 0
        assert row["min_credits"] == 0

    def test_seed_idempotent(self, db):
        run_seed(db)
        run_seed(db)   # 再次执行不报错，不重复插入
        count = db.execute("SELECT count(*) FROM plan_definitions").fetchone()[0]
        assert count == 4

    def test_plan_features_json_parseable(self, seeded_db):
        import json
        rows = seeded_db.execute(
            "SELECT plan_id, features_json FROM plan_definitions"
        ).fetchall()
        for row in rows:
            features = json.loads(row["features_json"])
            assert "permissions" in features, f"{row['plan_id']} missing permissions"
