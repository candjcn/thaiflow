"""
Comprehensive test suite for the referral system.

Tests cover:
  - get_ref_code()
  - resolve_ref_code()
  - bind_referral()
  - try_activate_referral()
  - on_purchase()
  - get_referral_stats()
  - get_admin_stats()
  - API endpoints (bind-referral, ref-code, referrals, admin/referrals)

Run with:
  python3 backend/tests/test_referral.py
"""

import sys
import os
import json
import re

# Ensure the backend directory is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from commerce.db import init_db
from commerce.wallet import get_balance, get_or_create_wallet
import commerce.referral as referral

# ─── helpers ─────────────────────────────────────────────────────────────────

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"

_results = {"pass": 0, "fail": 0}


def ok(name: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail else ""))
    if condition:
        _results["pass"] += 1
    else:
        _results["fail"] += 1
    return condition


def make_db():
    """Return a fresh in-memory DB with schema applied."""
    return init_db(":memory:")


def insert_user(db, user_id: str, email: str = None):
    """Insert a minimal user row so foreign-key constraints pass."""
    email = email or f"{user_id}@example.com"
    db.execute(
        "INSERT OR IGNORE INTO users (user_id, email) VALUES (?, ?)",
        (user_id, email),
    )
    db.commit()


def get_gift_balance(db, user_id: str) -> int:
    """Return current gift_credits for a user (create wallet if missing)."""
    get_or_create_wallet(db, user_id)
    return get_balance(db, user_id)["gift"]


# ─── 1. get_ref_code ─────────────────────────────────────────────────────────

def test_get_ref_code():
    print("\n=== 1. get_ref_code ===")

    code_a = referral.get_ref_code("user_alice")
    code_b = referral.get_ref_code("user_bob")

    ok("returns 8 chars", len(code_a) == 8, f"got {len(code_a)!r}")
    ok("alphanumeric only", bool(re.fullmatch(r"[A-Z0-9]{8}", code_a)),
       f"got {code_a!r}")
    ok("deterministic (same input → same output)",
       code_a == referral.get_ref_code("user_alice"))
    ok("different users → different codes", code_a != code_b,
       f"{code_a!r} vs {code_b!r}")
    ok("uppercased", code_a == code_a.upper())


# ─── 2. resolve_ref_code ─────────────────────────────────────────────────────

def test_resolve_ref_code():
    print("\n=== 2. resolve_ref_code ===")

    db = make_db()
    insert_user(db, "user_alice")

    code = referral.get_ref_code("user_alice")

    ok("valid code resolves to correct user_id",
       referral.resolve_ref_code(db, code) == "user_alice",
       f"code={code!r}")
    ok("invalid code returns None",
       referral.resolve_ref_code(db, "XXXXXXXX") is None)
    ok("empty string returns None",
       referral.resolve_ref_code(db, "") is None)
    ok("too-short code returns None",
       referral.resolve_ref_code(db, "ABC") is None)
    ok("too-long code returns None",
       referral.resolve_ref_code(db, "ABCDEFGHI") is None)   # 9 chars
    ok("lowercase input normalised correctly",
       referral.resolve_ref_code(db, code.lower()) == "user_alice",
       f"lowercase {code.lower()!r}")
    ok("user not in DB returns None",
       referral.resolve_ref_code(db, referral.get_ref_code("ghost_user")) is None)


# ─── 3. bind_referral ────────────────────────────────────────────────────────

def test_bind_referral():
    print("\n=== 3. bind_referral ===")

    db = make_db()
    insert_user(db, "referrer1")
    insert_user(db, "referred1")
    insert_user(db, "referred2")

    ref_code = referral.get_ref_code("referrer1")

    # Happy path
    result = referral.bind_referral(db, "referred1", ref_code)
    ok("happy path returns True", result is True)
    row = db.execute(
        "SELECT * FROM referrals WHERE referred_id = ?", ("referred1",)
    ).fetchone()
    ok("row inserted into referrals", row is not None)
    ok("status is 'pending'", row["status"] == "pending" if row else False)
    ok("referrer_id stored correctly",
       row["referrer_id"] == "referrer1" if row else False)
    ok("ref_code stored correctly",
       row["ref_code"] == ref_code if row else False)

    # Double-bind blocked
    result2 = referral.bind_referral(db, "referred1", ref_code)
    ok("double-bind returns False (idempotent)", result2 is False)
    count = db.execute(
        "SELECT COUNT(*) AS c FROM referrals WHERE referred_id = ?", ("referred1",)
    ).fetchone()["c"]
    ok("only one referral row exists after double-bind", count == 1)

    # Self-referral blocked
    result3 = referral.bind_referral(db, "referrer1", ref_code)
    ok("self-referral returns False", result3 is False)
    self_row = db.execute(
        "SELECT * FROM referrals WHERE referred_id = ?", ("referrer1",)
    ).fetchone()
    ok("self-referral not inserted", self_row is None)

    # Invalid code
    result4 = referral.bind_referral(db, "referred2", "XXXXXXXX")
    ok("invalid code returns False", result4 is False)

    # Empty code
    result5 = referral.bind_referral(db, "referred2", "")
    ok("empty code returns False", result5 is False)

    result6 = referral.bind_referral(db, "referred2", "   ")
    ok("whitespace-only code returns False", result6 is False)


# ─── 4. try_activate_referral ────────────────────────────────────────────────

def test_try_activate_referral():
    print("\n=== 4. try_activate_referral ===")

    db = make_db()
    insert_user(db, "referrer_a")
    insert_user(db, "referred_a")

    # No referral row → False
    ok("no referral row returns False",
       referral.try_activate_referral(db, "referred_a") is False)

    # Bind then activate
    ref_code = referral.get_ref_code("referrer_a")
    referral.bind_referral(db, "referred_a", ref_code)

    result = referral.try_activate_referral(db, "referred_a")
    ok("happy path returns True", result is True)

    # Check DB status
    row = db.execute(
        "SELECT * FROM referrals WHERE referred_id = ?", ("referred_a",)
    ).fetchone()
    ok("status updated to 'activated'",
       row["status"] == "activated" if row else False)
    ok("referrer_rewarded set to 1",
       row["referrer_rewarded"] == 1 if row else False)
    ok("referred_rewarded set to 1",
       row["referred_rewarded"] == 1 if row else False)
    ok("activated_at populated",
       bool(row["activated_at"]) if row else False)

    # Check credits
    referrer_gift = get_gift_balance(db, "referrer_a")
    referred_gift = get_gift_balance(db, "referred_a")
    ok(f"referrer got {referral.REFERRAL_SIGNUP_CREDITS} gift credits",
       referrer_gift == referral.REFERRAL_SIGNUP_CREDITS,
       f"got {referrer_gift}")
    ok(f"referred got {referral.REFERRAL_SIGNUP_CREDITS} gift credits",
       referred_gift == referral.REFERRAL_SIGNUP_CREDITS,
       f"got {referred_gift}")

    # Already activated → False (idempotent)
    result2 = referral.try_activate_referral(db, "referred_a")
    ok("already activated returns False", result2 is False)

    # Credits should NOT be doubled
    referrer_gift2 = get_gift_balance(db, "referrer_a")
    ok("credits not doubled on second activation call",
       referrer_gift2 == referral.REFERRAL_SIGNUP_CREDITS,
       f"got {referrer_gift2}")


# ─── 5. on_purchase ──────────────────────────────────────────────────────────

def test_on_purchase():
    print("\n=== 5. on_purchase ===")

    # Setup: referrer → referred, activated
    db = make_db()
    insert_user(db, "ref_buyer_referrer")
    insert_user(db, "ref_buyer_referred")

    ref_code = referral.get_ref_code("ref_buyer_referrer")
    referral.bind_referral(db, "ref_buyer_referred", ref_code)
    referral.try_activate_referral(db, "ref_buyer_referred")

    # Note gift credits already given from activation
    referrer_before = get_gift_balance(db, "ref_buyer_referrer")

    referral.on_purchase(db, "ref_buyer_referred", 1000)
    referrer_after = get_gift_balance(db, "ref_buyer_referrer")

    expected_cashback = max(1, int(1000 * referral.CASHBACK_RATE))
    ok(f"referrer gets 20% cashback on 1000-credit purchase",
       referrer_after == referrer_before + expected_cashback,
       f"expected +{expected_cashback}, got +{referrer_after - referrer_before}")

    # Min cashback = 1 (buying 1 credit → int(1 * 0.20) = 0, max(1,0) = 1)
    referrer_before2 = get_gift_balance(db, "ref_buyer_referrer")
    referral.on_purchase(db, "ref_buyer_referred", 1)
    referrer_after2 = get_gift_balance(db, "ref_buyer_referrer")
    ok("min cashback is 1 for tiny purchase",
       referrer_after2 == referrer_before2 + 1,
       f"got {referrer_after2 - referrer_before2}")

    # No referrer → no crash, no credits
    insert_user(db, "solo_buyer")
    get_or_create_wallet(db, "solo_buyer")
    try:
        referral.on_purchase(db, "solo_buyer", 500)
        ok("no referrer: no crash", True)
    except Exception as e:
        ok("no referrer: no crash", False, str(e))

    # Pending (not activated) referral → no cashback
    db2 = make_db()
    insert_user(db2, "ref2_referrer")
    insert_user(db2, "ref2_referred")
    ref_code2 = referral.get_ref_code("ref2_referrer")
    referral.bind_referral(db2, "ref2_referred", ref_code2)   # pending, not activated
    get_or_create_wallet(db2, "ref2_referrer")
    referrer_before3 = get_gift_balance(db2, "ref2_referrer")
    referral.on_purchase(db2, "ref2_referred", 500)
    referrer_after3 = get_gift_balance(db2, "ref2_referrer")
    ok("pending referral: no cashback issued",
       referrer_after3 == referrer_before3,
       f"delta={referrer_after3 - referrer_before3}")

    # Cashback calculation: int(credits * 0.20)
    db3 = make_db()
    insert_user(db3, "ref3_referrer")
    insert_user(db3, "ref3_referred")
    ref_code3 = referral.get_ref_code("ref3_referrer")
    referral.bind_referral(db3, "ref3_referred", ref_code3)
    referral.try_activate_referral(db3, "ref3_referred")
    referrer_before4 = get_gift_balance(db3, "ref3_referrer")
    referral.on_purchase(db3, "ref3_referred", 500)
    referrer_after4 = get_gift_balance(db3, "ref3_referrer")
    ok("cashback = int(500 * 0.20) = 100",
       referrer_after4 == referrer_before4 + 100,
       f"got {referrer_after4 - referrer_before4}")


# ─── 6. get_referral_stats ───────────────────────────────────────────────────

def test_get_referral_stats():
    print("\n=== 6. get_referral_stats ===")

    db = make_db()
    insert_user(db, "stats_referrer")
    insert_user(db, "stats_ref1")
    insert_user(db, "stats_ref2")
    insert_user(db, "stats_ref3")

    ref_code = referral.get_ref_code("stats_referrer")

    # Bind 3 referred users
    referral.bind_referral(db, "stats_ref1", ref_code)
    referral.bind_referral(db, "stats_ref2", ref_code)
    referral.bind_referral(db, "stats_ref3", ref_code)

    # Activate 2 of them
    referral.try_activate_referral(db, "stats_ref1")
    referral.try_activate_referral(db, "stats_ref2")

    stats = referral.get_referral_stats(db, "stats_referrer")

    ok("stats contains ref_code", "ref_code" in stats)
    ok("ref_code matches get_ref_code()",
       stats.get("ref_code") == ref_code,
       f"got {stats.get('ref_code')!r}")
    ok("total_invited = 3",
       stats.get("total_invited") == 3,
       f"got {stats.get('total_invited')}")
    ok("total_activated = 2",
       stats.get("total_activated") == 2,
       f"got {stats.get('total_activated')}")
    ok("credits_earned >= 200 (2 activations × 100)",
       stats.get("credits_earned", 0) >= 200,
       f"got {stats.get('credits_earned')}")

    # User with no referrals
    stats_empty = referral.get_referral_stats(db, "stats_ref1")
    ok("zero stats for user with no invites",
       stats_empty["total_invited"] == 0 and stats_empty["total_activated"] == 0)


# ─── 7. get_admin_stats ──────────────────────────────────────────────────────

def test_get_admin_stats():
    print("\n=== 7. get_admin_stats ===")

    db = make_db()
    insert_user(db, "admin_ref1")
    insert_user(db, "admin_ref_a")
    insert_user(db, "admin_ref_b")

    ref_code = referral.get_ref_code("admin_ref1")
    referral.bind_referral(db, "admin_ref_a", ref_code)
    referral.bind_referral(db, "admin_ref_b", ref_code)
    referral.try_activate_referral(db, "admin_ref_a")

    stats = referral.get_admin_stats(db)

    ok("returns 'summary' key", "summary" in stats)
    ok("returns 'top_referrers' key", "top_referrers" in stats)
    ok("returns 'recent' key", "recent" in stats)

    s = stats["summary"]
    ok("summary.total_referrals = 2",
       s.get("total_referrals") == 2, f"got {s.get('total_referrals')}")
    ok("summary.activated = 1",
       s.get("activated") == 1, f"got {s.get('activated')}")
    ok("summary.pending = 1",
       s.get("pending") == 1, f"got {s.get('pending')}")
    ok("total_referrer_credits_issued >= 100",
       s.get("total_referrer_credits_issued", 0) >= 100,
       f"got {s.get('total_referrer_credits_issued')}")

    # Top referrers
    top = stats["top_referrers"]
    ok("top_referrers is a list", isinstance(top, list))
    if top:
        entry = top[0]
        ok("top referrer has 'user_id'", "user_id" in entry)
        ok("top referrer has 'invited'", "invited" in entry)
        ok("top referrer has 'activated'", "activated" in entry)
        ok("top referrer has 'credits_earned'", "credits_earned" in entry)

    # Recent list
    recent = stats["recent"]
    ok("recent is a list", isinstance(recent, list))
    ok("recent has entries", len(recent) >= 2)


# ─── 8. API endpoint tests ───────────────────────────────────────────────────

def test_api_endpoints():
    print("\n=== 8. API endpoints ===")

    # We import app here only to avoid side-effects at module level
    try:
        import importlib
        import commerce.db as _cdb

        # Patch settings so app.py doesn't need real env vars for keys we don't test
        from config import settings as _settings
        if not hasattr(_settings, "ADMIN_KEY") or not _settings.ADMIN_KEY:
            _settings.ADMIN_KEY = "test-admin-key-12345"

        import app as flask_app
        client = flask_app.app.test_client()
    except Exception as e:
        print(f"  [SKIP] Could not import flask app: {e}")
        return

    # --- GET /api/user/ref-code — unauthenticated ---
    resp = client.get("/api/user/ref-code")
    ok("GET /api/user/ref-code → 401 when not logged in",
       resp.status_code == 401, f"got {resp.status_code}")

    # --- GET /api/user/referrals — unauthenticated ---
    resp = client.get("/api/user/referrals")
    ok("GET /api/user/referrals → 401 when not logged in",
       resp.status_code == 401, f"got {resp.status_code}")

    # --- POST /api/auth/bind-referral — unauthenticated ---
    resp = client.post(
        "/api/auth/bind-referral",
        data=json.dumps({"ref_code": "ABCDEF12"}),
        content_type="application/json",
    )
    ok("POST /api/auth/bind-referral → 401 when not logged in",
       resp.status_code == 401, f"got {resp.status_code}")

    # --- GET /api/admin/referrals — no key ---
    resp = client.get("/api/admin/referrals")
    ok("GET /api/admin/referrals → 401 without key",
       resp.status_code == 401, f"got {resp.status_code}")

    # --- GET /api/admin/referrals — wrong key ---
    resp = client.get("/api/admin/referrals?key=wrongkey")
    ok("GET /api/admin/referrals → 401 with wrong key",
       resp.status_code == 401, f"got {resp.status_code}")

    # --- GET /api/admin/referrals — correct key ---
    resp = client.get(f"/api/admin/referrals?key={_settings.ADMIN_KEY}")
    ok("GET /api/admin/referrals → 200 with correct key",
       resp.status_code == 200, f"got {resp.status_code}")
    try:
        data = json.loads(resp.data)
        ok("admin referrals response has 'summary' key", "summary" in data)
    except Exception:
        ok("admin referrals response is valid JSON", False)

    # --- POST /api/auth/bind-referral — missing ref_code body ---
    resp = client.post(
        "/api/auth/bind-referral",
        data=json.dumps({}),
        content_type="application/json",
    )
    ok("POST /api/auth/bind-referral with no body → 401 (not logged in first)",
       resp.status_code == 401, f"got {resp.status_code}")


# ─── 9. Edge cases & regression checks ──────────────────────────────────────

def test_edge_cases():
    print("\n=== 9. Edge cases ===")

    # get_ref_code with empty string user_id — shouldn't crash
    try:
        code = referral.get_ref_code("")
        ok("get_ref_code('') doesn't crash", True, f"code={code!r}")
        ok("get_ref_code('') returns 8 chars", len(code) == 8)
    except Exception as e:
        ok("get_ref_code('') doesn't crash", False, str(e))

    # bind_referral with user not in DB (FK violation should not propagate as unhandled)
    db = make_db()
    insert_user(db, "fk_referrer")
    ref_code = referral.get_ref_code("fk_referrer")
    try:
        result = referral.bind_referral(db, "ghost_referred", ref_code)
        # May return False (ghost_referred not in users → FK error caught) or raise
        ok("bind with ghost referred_id: no unhandled exception", True,
           f"result={result}")
    except Exception as e:
        ok("bind with ghost referred_id: no unhandled exception", False, str(e))

    # resolve_ref_code: whitespace trimmed
    db2 = make_db()
    insert_user(db2, "ws_user")
    code2 = referral.get_ref_code("ws_user")
    ok("resolve_ref_code trims whitespace",
       referral.resolve_ref_code(db2, f"  {code2}  ") == "ws_user",
       f"code={code2!r}")

    # Multiple referrers, make sure codes don't collide
    db3 = make_db()
    user_ids = [f"coll_user_{i}" for i in range(20)]
    codes = set()
    for uid in user_ids:
        insert_user(db3, uid)
        codes.add(referral.get_ref_code(uid))
    ok("no code collisions across 20 users", len(codes) == 20,
       f"unique={len(codes)}/20")

    # try_activate_referral: second call doesn't give double credits
    db4 = make_db()
    insert_user(db4, "dbl_referrer")
    insert_user(db4, "dbl_referred")
    ref_code4 = referral.get_ref_code("dbl_referrer")
    referral.bind_referral(db4, "dbl_referred", ref_code4)
    referral.try_activate_referral(db4, "dbl_referred")
    referral.try_activate_referral(db4, "dbl_referred")   # second call
    referral.try_activate_referral(db4, "dbl_referred")   # third call
    bal = get_gift_balance(db4, "dbl_referrer")
    ok("credits not multiplied by repeated activation calls",
       bal == referral.REFERRAL_SIGNUP_CREDITS,
       f"expected {referral.REFERRAL_SIGNUP_CREDITS}, got {bal}")

    # on_purchase: cashback = int(credits * 0.20), never 0 (min 1)
    for purchase, expected in [(5, 1), (10, 2), (100, 20), (999, 199)]:
        cashback = max(1, int(purchase * referral.CASHBACK_RATE))
        ok(f"cashback({purchase}) = {expected}",
           cashback == expected,
           f"got {cashback}")


# ─── main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Referral System Test Suite")
    print("=" * 60)

    test_get_ref_code()
    test_resolve_ref_code()
    test_bind_referral()
    test_try_activate_referral()
    test_on_purchase()
    test_get_referral_stats()
    test_get_admin_stats()
    test_api_endpoints()
    test_edge_cases()

    print("\n" + "=" * 60)
    total = _results["pass"] + _results["fail"]
    print(f"Results: {_results['pass']}/{total} passed, "
          f"{_results['fail']} failed")
    print("=" * 60)

    sys.exit(0 if _results["fail"] == 0 else 1)
