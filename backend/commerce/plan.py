"""套餐权益解析：质量档位只能由套餐决定，不能由前端 Provider 参数决定。"""

_DEFAULT_QUALITY = {
    "free": "economy",
    "plus": "standard",
    "pro": "premium",
    "enterprise": "premium",
}


def get_default_quality(plan_id: str) -> str:
    """返回套餐默认质量；未知套餐安全降级为 economy。"""
    return _DEFAULT_QUALITY.get(plan_id, "economy")
