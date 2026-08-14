"""订阅生命周期测试：激活、临近到期、过期惰性失效、查单兜底归属校验。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine

from app.database import init_db, session_scope
from app.models import Subscription
from app import alipay_service, subscription_service


@pytest.fixture()
def engine():
    eng = create_engine("sqlite:///:memory:", future=True)
    init_db(eng)
    return eng


def _set_period_end(eng, out_trade_no: str, when: datetime) -> None:
    from sqlalchemy import select

    with session_scope(eng) as session:
        sub = session.execute(
            select(Subscription).where(Subscription.out_trade_no == out_trade_no)
        ).scalars().first()
        sub.current_period_end = when


def test_active_subscription_payload_reports_days_remaining(engine):
    alipay_service.activate_subscription(
        engine, user_id="u1", out_trade_no="SUB1", alipay_trade_no="T1"
    )
    payload = subscription_service.subscription_status_payload(engine, "u1")
    assert payload["has_active_subscription"] is True
    assert payload["subscription_expires_at"] is not None
    assert payload["subscription_expired_at"] is None
    # 30-day window → around 29-30 days remaining
    assert payload["subscription_days_remaining"] >= 28
    assert payload["subscription_expiring_soon"] is False


def test_expiring_soon_flag_when_within_three_days(engine):
    alipay_service.activate_subscription(
        engine, user_id="u2", out_trade_no="SUB2", alipay_trade_no="T2"
    )
    _set_period_end(engine, "SUB2", datetime.utcnow() + timedelta(days=2, hours=1))
    payload = subscription_service.subscription_status_payload(engine, "u2")
    assert payload["has_active_subscription"] is True
    assert payload["subscription_expiring_soon"] is True
    assert payload["subscription_days_remaining"] <= 3


def test_expired_subscription_is_lazily_marked_and_surfaced(engine):
    alipay_service.activate_subscription(
        engine, user_id="u3", out_trade_no="SUB3", alipay_trade_no="T3"
    )
    _set_period_end(engine, "SUB3", datetime.utcnow() - timedelta(days=1))

    payload = subscription_service.subscription_status_payload(engine, "u3")
    assert payload["has_active_subscription"] is False
    assert payload["subscription_expires_at"] is None
    # Past period surfaced so the UI can show "expired on <date>"
    assert payload["subscription_expired_at"] is not None

    # Stored status column flipped to expired (not left dangling as active)
    from sqlalchemy import select

    with session_scope(engine) as session:
        sub = session.execute(
            select(Subscription).where(Subscription.out_trade_no == "SUB3")
        ).scalars().first()
        assert sub.status == "expired"


def test_never_subscribed_has_no_expired_date(engine):
    payload = subscription_service.subscription_status_payload(engine, "newuser")
    assert payload["has_active_subscription"] is False
    assert payload["subscription_expired_at"] is None
    assert payload["subscription_days_remaining"] is None


def test_reconcile_activates_pending_on_success(engine, monkeypatch):
    alipay_service.create_pending_subscription(
        engine, user_id="u4", out_trade_no="SUB4"
    )
    monkeypatch.setattr(
        alipay_service, "query_trade_status", lambda otn: "TRADE_SUCCESS"
    )
    sub = alipay_service.reconcile_pending_subscription(engine, "SUB4")
    assert sub is not None
    assert sub.status == "active"
    payload = subscription_service.subscription_status_payload(engine, "u4")
    assert payload["has_active_subscription"] is True


def test_reconcile_noop_when_not_paid(engine, monkeypatch):
    alipay_service.create_pending_subscription(
        engine, user_id="u5", out_trade_no="SUB5"
    )
    monkeypatch.setattr(
        alipay_service, "query_trade_status", lambda otn: "WAIT_BUYER_PAY"
    )
    sub = alipay_service.reconcile_pending_subscription(engine, "SUB5")
    assert sub is None
    payload = subscription_service.subscription_status_payload(engine, "u5")
    assert payload["has_active_subscription"] is False
