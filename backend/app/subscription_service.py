"""订阅与免费额度服务：统一查询订阅状态、校验润色权限、累计免费次数。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine

from app.database import session_scope
from app.models import Subscription, User


def _free_polish_limit() -> int:
    """Read FREE_POLISH_LIMIT from env (default 2)."""
    try:
        return max(0, int(os.environ.get("FREE_POLISH_LIMIT", "2")))
    except ValueError:
        return 2


def _subscription_price_cents() -> int:
    try:
        return max(0, int(os.environ.get("SUBSCRIPTION_PRICE_CENTS", "990")))
    except ValueError:
        return 990


def get_subscription_price_cents() -> int:
    """Public accessor for subscription price in cents."""
    return _subscription_price_cents()


@dataclass
class PolishEligibility:
    allowed: bool
    reason: str  # "ok" | "free_limit_reached" | "subscription_required"
    free_used: int
    free_limit: int
    has_active_subscription: bool
    subscription_expires_at: datetime | None


def ensure_user(engine: Engine, user_id: str) -> User:
    """Get or create a User row."""
    with session_scope(engine) as session:
        user = session.get(User, user_id)
        if user is None:
            user = User(id=user_id, free_polish_used=0)
            session.add(user)
            session.flush()
        return user


def get_active_subscription(engine: Engine, user_id: str) -> Subscription | None:
    """Return active subscription or None."""
    from app.alipay_service import get_active_subscription as _get
    return _get(engine, user_id)


def check_polish_eligibility(engine: Engine, user_id: str) -> PolishEligibility:
    """Determine if user may polish another image.

    Rule: allowed if (free_used < FREE_POLISH_LIMIT) OR has active subscription.
    """
    user = ensure_user(engine, user_id)
    sub = get_active_subscription(engine, user_id)
    has_sub = sub is not None and sub.status == "active" and (
        sub.current_period_end is None or sub.current_period_end > datetime.utcnow()
    )
    free_limit = _free_polish_limit()
    free_used = user.free_polish_used
    if has_sub:
        return PolishEligibility(
            allowed=True,
            reason="ok",
            free_used=free_used,
            free_limit=free_limit,
            has_active_subscription=True,
            subscription_expires_at=sub.current_period_end if sub else None,
        )
    if free_used < free_limit:
        return PolishEligibility(
            allowed=True,
            reason="ok",
            free_used=free_used,
            free_limit=free_limit,
            has_active_subscription=False,
            subscription_expires_at=None,
        )
    return PolishEligibility(
        allowed=False,
        reason="subscription_required",
        free_used=free_used,
        free_limit=free_limit,
        has_active_subscription=False,
        subscription_expires_at=None,
    )


def increment_polish_usage(engine: Engine, user_id: str) -> None:
    """Increment user's free_polish_used counter. No-op for subscribers."""
    with session_scope(engine) as session:
        user = session.get(User, user_id)
        if user is None:
            user = User(id=user_id, free_polish_used=1)
            session.add(user)
        else:
            user.free_polish_used = user.free_polish_used + 1


def increment_polish_usage_if_not_subscribed(engine: Engine, user_id: str) -> None:
    """Increment free usage only if user has no active subscription.

    Called after a successful polish to avoid charging subscribers.
    """
    sub = get_active_subscription(engine, user_id)
    if sub is not None:
        return
    increment_polish_usage(engine, user_id)


def _latest_subscription(engine: Engine, user_id: str) -> Subscription | None:
    """Return the most recent subscription row (any status) for display.

    Unlike get_active_subscription this also surfaces an already-expired period so
    the UI can show "expired on <date>" instead of falling back to the
    never-subscribed state.
    """
    from sqlalchemy import select

    with session_scope(engine) as session:
        return session.execute(
            select(Subscription)
            .where(Subscription.user_id == user_id)
            .order_by(Subscription.current_period_end.desc().nullslast())
            .limit(1)
        ).scalars().first()


def subscription_status_payload(engine: Engine, user_id: str) -> dict:
    """Build the /api/auth/me subscription section payload."""
    # Keep the stored status column honest so the UI can distinguish
    # "never subscribed" from "expired".
    from app.alipay_service import expire_stale_subscriptions

    expire_stale_subscriptions(engine, user_id)

    user = ensure_user(engine, user_id)
    active = get_active_subscription(engine, user_id)
    latest = active or _latest_subscription(engine, user_id)
    free_limit = _free_polish_limit()

    now = datetime.utcnow()
    has_sub = active is not None and active.status == "active" and (
        active.current_period_end is None or active.current_period_end > now
    )

    expires_at = None
    days_remaining: int | None = None
    expiring_soon = False
    if active is not None and active.current_period_end is not None:
        expires_at = active.current_period_end.isoformat() + "Z"
        delta = active.current_period_end - now
        days_remaining = max(0, delta.days + (1 if delta.seconds > 0 else 0))
        expiring_soon = has_sub and days_remaining <= 3

    # When there is no active period but a past one exists, surface it so the UI
    # can render an "expired on" hint and a resubscribe CTA.
    expired_at = None
    if not has_sub and latest is not None and latest.current_period_end is not None:
        expired_at = latest.current_period_end.isoformat() + "Z"

    return {
        "has_active_subscription": has_sub,
        "subscription_expires_at": expires_at,
        "subscription_expired_at": expired_at,
        "subscription_days_remaining": days_remaining,
        "subscription_expiring_soon": expiring_soon,
        "free_polish_used": user.free_polish_used,
        "free_polish_limit": free_limit,
        "subscription_price_cents": _subscription_price_cents(),
    }
