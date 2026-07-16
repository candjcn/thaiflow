"""
CommerceContext：编排完整 AI 调用计费链。

调用链（ARCHITECTURE.md v1.1）：
  Permission.check → Router.route → Wallet.Reserve(estimate)
    → Provider call（在调用方发生）
  → UsageLog.record(actual_units) → Wallet.Confirm(reservation_id)

失败路径：
  Provider raise → CommerceContext.release_on_error()
    → Wallet.Release → UsageLog.record(status=failed)

典型用法（非 SSE 路由）：
    ctx = CommerceContext(db, "anonymous", "translation", "standard", "free", "req-001")
    if not ctx.check_permission("CanTranslate"):
        return jsonify({"error": "权限不足"}), 403
    ctx.reserve({"char_count": 800})
    try:
        result, provider = translate_segments(...)
        ctx.settle({"char_count": 800}, provider, model_id, latency_ms)
    except Exception as e:
        ctx.release_on_error(e)
        raise

典型用法（SSE worker 线程内）：
    ctx = CommerceContext(...)
    ctx.reserve({"duration_seconds": duration})
    try:
        result = transcribe_video(...)
        ctx.settle({"duration_seconds": duration}, "groq", "whisper-large-v3", latency_ms)
    except Exception as e:
        ctx.release_on_error(e)
        progress_queue.put(("error", str(e)))
"""
import time
import uuid
from config import get_logger
from commerce.permission import check as _perm_check
from commerce.pricing import estimate_credits, calculate_credits
from commerce.router import route as _route, with_fallback, ProviderHandle
from commerce.wallet import (
    reserve as _reserve, confirm as _confirm,
    release as _release, InsufficientFundsError,
)
from commerce import usage_log as _log

logger = get_logger(__name__)


class CommerceContext:
    """
    一次 AI 调用的完整计费上下文。

    线程安全：每个请求/线程创建独立实例，不共享状态。
    db 连接来自 commerce.db.get_db()（threading.local，线程安全）。
    """

    def __init__(
        self,
        db,
        user_id: str,
        capability: str,
        quality_tier: str = "standard",
        plan_id: str = "free",
        request_id: str = None,
        extra: dict = None,
    ):
        self.db           = db
        self.user_id      = user_id
        self.capability   = capability
        self.quality_tier = quality_tier
        self.plan_id      = plan_id
        self.request_id   = request_id or str(uuid.uuid4())
        self.extra        = extra or {}

        self._reservation_id: str | None = None
        self._reserved_credits: int      = 0
        self._requested_at: str | None   = None
        self.log_id: str | None          = None

    # ── 权限检查 ─────────────────────────────────────────────────────────────

    def check_permission(self, permission: str) -> bool:
        """检查用户是否拥有指定权限（委托给 Permission Engine）。"""
        result = _perm_check(self.db, self.user_id, permission)
        if not result:
            logger.info(
                f"[commerce] permission denied: {self.user_id} → {permission} "
                f"(plan={self.plan_id})"
            )
        return result

    # ── 预扣 ─────────────────────────────────────────────────────────────────

    def reserve(self, input_metadata: dict) -> str:
        """
        按 estimate_credits 预扣 Credits。

        Args:
            input_metadata: {"duration_seconds": float} / {"char_count": int} 等

        Returns:
            reservation_id（同时保存在 self._reservation_id）

        Raises:
            InsufficientFundsError: 余额不足
        """
        import datetime as _dt
        credits = estimate_credits(
            self.db, self.capability, self.quality_tier,
            self.plan_id, input_metadata,
        )
        self._reserved_credits = credits
        self._requested_at = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        if credits > 0:
            self._reservation_id = _reserve(self.db, self.user_id, credits)
            logger.debug(
                f"[commerce] reserved {credits} credits for {self.user_id} "
                f"cap={self.capability} rid={self._reservation_id}"
            )
        else:
            # 免费操作（romanize_zh / export）不预扣，reservation_id 留 None
            self._reservation_id = None

        return self._reservation_id or ""

    # ── 路由 ─────────────────────────────────────────────────────────────────

    def get_handle(self, preferred_provider: str = None) -> ProviderHandle:
        """选择 Provider，返回 ProviderHandle。"""
        return _route(
            self.capability,
            self.quality_tier,
            self.plan_id,
            preferred_provider=preferred_provider,
        )

    # ── 结算 ─────────────────────────────────────────────────────────────────

    def settle(
        self,
        actual_usage: dict,
        provider_id: str,
        model_id: str,
        latency_ms: int,
        status: str = "success",
        fallback_used: bool = False,
        fallback_from: str = None,
        retry_count: int = 0,
    ) -> None:
        """
        AI 调用成功后结算。

        1. 精确计算 (credits, cost_usd)——仅用于 UsageLog 记录，不影响用户余额
        2. 写 UsageLog（actual_units + cost_usd）
        3. Wallet.Confirm（estimate 即最终扣款）

        Args:
            actual_usage: Provider 返回后的实际用量（用于精确计算和日志）
            provider_id / model_id: 实际使用的 Provider（日志用）
            latency_ms: Provider 调用耗时
        """
        import datetime as _dt

        credits_charged, cost_usd = calculate_credits(
            self.db, self.capability, self.quality_tier, self.plan_id,
            provider_id, model_id, actual_usage,
        )

        # 确定计费单位类型
        unit_type = _infer_unit_type(actual_usage)
        input_units = _extract_input_units(actual_usage)

        completed_at = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        self.log_id = _log.record(
            self.db,
            user_id=self.user_id,
            capability=self.capability,
            quality_tier=self.quality_tier,
            provider_id=provider_id,
            model_id=model_id,
            plan_id=self.plan_id,
            input_units=input_units,
            input_unit_type=unit_type,
            provider_cost_usd=cost_usd,
            credits_reserved=self._reserved_credits,
            credits_charged=self._reserved_credits,  # 实际扣款 = estimate（Confirm 不重算）
            latency_ms=latency_ms,
            status=status,
            fallback_used=fallback_used,
            fallback_from=fallback_from,
            retry_count=retry_count,
            requested_at=self._requested_at,
            completed_at=completed_at,
            reservation_id=self._reservation_id,
            request_id=self.request_id,
            extra=self.extra,
        )

        # Wallet.Confirm（免费操作 reservation_id=None，跳过）
        if self._reservation_id:
            _confirm(self.db, self._reservation_id)

        logger.info(
            f"[commerce] settled: {self.user_id} cap={self.capability} "
            f"provider={provider_id} reserved={self._reserved_credits} "
            f"cost_usd={cost_usd:.6f} latency={latency_ms}ms"
        )

    # ── 失败释放 ─────────────────────────────────────────────────────────────

    def release_on_error(self, error: Exception) -> None:
        """
        AI 调用失败时释放预扣，并写入 failed 状态的 UsageLog。

        保证用户余额完全恢复，不丢失任何已预扣 Credits。
        """
        import datetime as _dt

        if self._reservation_id:
            try:
                _release(self.db, self._reservation_id)
                logger.info(
                    f"[commerce] released {self._reserved_credits} credits "
                    f"for {self.user_id} (error: {error})"
                )
            except Exception as rel_err:
                logger.error(f"[commerce] release failed: {rel_err}")

        completed_at = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        self.log_id = _log.record(
            self.db,
            user_id=self.user_id,
            capability=self.capability,
            quality_tier=self.quality_tier,
            provider_id="unknown",
            model_id="unknown",
            plan_id=self.plan_id,
            credits_reserved=self._reserved_credits,
            credits_charged=0,
            latency_ms=None,
            status="failed",
            error_code=type(error).__name__,
            requested_at=self._requested_at,
            completed_at=completed_at,
            reservation_id=self._reservation_id,
            request_id=self.request_id,
            extra=self.extra,
        )


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _infer_unit_type(usage: dict) -> str:
    if "duration_seconds" in usage:
        return "seconds"
    if "char_count" in usage:
        return "chars"
    if "token_count" in usage:
        return "tokens"
    if "image_count" in usage:
        return "images"
    return "requests"


def _extract_input_units(usage: dict) -> float | None:
    if "duration_seconds" in usage:
        return usage["duration_seconds"]
    if "char_count" in usage:
        return float(usage["char_count"])
    if "token_count" in usage:
        return float(usage["token_count"])
    if "image_count" in usage:
        return float(usage["image_count"])
    return None
