"""支付宝电脑网站支付（PagePay）订阅服务。

流程：
1. 用户点击订阅 → 后端生成 alipay.trade.page.pay URL
2. 前端在新标签页打开支付宝收银台
3. 支付宝异步通知 webhook → RSA2 验签 → 激活订阅（30 天）
4. 前端轮询 /api/subscriptions/status 检查是否已激活

签名：所有业务参数按 key 字典序拼成 key=value&...，用商户私钥 SHA256 签名。
"""

from __future__ import annotations

import base64
import hashlib
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from sqlalchemy import Engine, select
from sqlalchemy.exc import SQLAlchemyError

from app.database import session_scope
from app.models import Subscription, User


GATEWAY_SANDBOX = "https://openapi-sandbox.dl.alipaydev.com/gateway.do"
GATEWAY_PRODUCTION = "https://openapi.alipay.com/gateway.do"
SUBSCRIPTION_DURATION_DAYS = 30


def _load_alipay_config() -> dict[str, str]:
    """Load Alipay config from env. Returns dict with keys:
    app_id, private_key_pem, sandbox (bool), gateway, notify_url.
    """
    app_id = os.environ.get("ALIPAY_APP_ID", "").strip()
    private_key_b64 = os.environ.get("ALIPAY_PRIVATE_KEY", "").strip()
    sandbox = os.environ.get("ALIPAY_SANDBOX", "false").lower() in {"1", "true", "yes"}
    notify_url = os.environ.get("ALIPAY_NOTIFY_URL", "").strip()
    if not app_id or not private_key_b64:
        raise RuntimeError("Alipay not configured: ALIPAY_APP_ID/ALIPAY_PRIVATE_KEY missing")
    # Wrap raw base64 key into PEM
    private_key_pem = _wrap_private_key_pem(private_key_b64)
    return {
        "app_id": app_id,
        "private_key_pem": private_key_pem,
        "sandbox": str(sandbox).lower(),
        "gateway": GATEWAY_SANDBOX if sandbox else GATEWAY_PRODUCTION,
        "notify_url": notify_url,
    }


def _wrap_private_key_pem(raw: str) -> str:
    """Wrap a raw base64 RSA private key (PKCS#8 or PKCS#1) into PEM format."""
    raw = raw.strip()
    if "BEGIN" in raw:
        return raw
    # Try PKCS#8 first, then PKCS#1
    for header, footer in (
        ("-----BEGIN PRIVATE KEY-----", "-----END PRIVATE KEY-----"),
        ("-----BEGIN RSA PRIVATE KEY-----", "-----END RSA PRIVATE KEY-----"),
    ):
        # Re-wrap at 64 chars per line per PEM convention
        body = "\n".join(raw[i : i + 64] for i in range(0, len(raw), 64))
        return f"{header}\n{body}\n{footer}"
    return raw


def _wrap_public_key_pem(raw: str) -> str:
    """Wrap a raw base64 RSA public key (X.509 SubjectPublicKeyInfo) into PEM.

    Alipay dashboards hand out the public key as a single base64 line with no PEM
    header. `load_pem_public_key` requires the armored PEM form, so wrap it here.
    """
    raw = raw.strip()
    if "BEGIN" in raw:
        return raw
    body = "\n".join(raw[i : i + 64] for i in range(0, len(raw), 64))
    return f"-----BEGIN PUBLIC KEY-----\n{body}\n-----END PUBLIC KEY-----"


def _load_private_key(pem: str):
    """Load RSA private key from PEM, trying PKCS#8 then PKCS#1."""
    try:
        return serialization.load_pem_private_key(
            pem.encode("utf-8"),
            password=None,
            backend=default_backend(),
        )
    except ValueError:
        # Try wrapping as PKCS#1
        raise RuntimeError("invalid ALIPAY_PRIVATE_KEY: cannot parse PEM")


def _sign_params(params: dict[str, str], private_key_pem: str) -> str:
    """Sign params with RSA2 (SHA256 with RSA). Returns base64 signature."""
    # Sort keys, join as key=value&... (values NOT URL-encoded in sign string)
    sorted_items = sorted(params.items())
    # sign_type is a signed Alipay common parameter. Only the generated `sign`
    # value itself is excluded from request signing.
    sign_string = "&".join(f"{k}={v}" for k, v in sorted_items if v and k != "sign")
    private_key = _load_private_key(private_key_pem)
    signature = private_key.sign(
        sign_string.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


def _build_common_params(config: dict[str, str], method: str) -> dict[str, str]:
    """Build Alipay common params for a given method."""
    return {
        "app_id": config["app_id"],
        "method": method,
        "format": "JSON",
        "charset": "utf-8",
        "sign_type": "RSA2",
        "timestamp": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        "version": "1.0",
    }


def create_subscription_checkout(
    user_id: str,
    *,
    price_cents: int,
    subject: str = "上海City不City 月度订阅",
) -> dict[str, Any]:
    """Build an alipay.trade.page.pay checkout URL.

    The shared EasyLaunch merchant account is contracted for PagePay, not
    Face-to-Face precreate. Keep the original browser open so it can poll the
    subscription status while the user completes payment in a new tab.
    """
    config = _load_alipay_config()
    out_trade_no = f"SUB{int(time.time() * 1000)}{uuid.uuid4().hex[:8]}"
    total_amount = f"{price_cents / 100:.2f}"

    biz_content = {
        "out_trade_no": out_trade_no,
        "total_amount": total_amount,
        "subject": subject,
        "product_code": "FAST_INSTANT_TRADE_PAY",
    }

    import json

    params = _build_common_params(config, "alipay.trade.page.pay")
    if config.get("notify_url"):
        # notify_url is an Alipay common parameter, not part of biz_content.
        # It remains project-specific while the shared merchant collects funds.
        params["notify_url"] = config["notify_url"]
    params["biz_content"] = json.dumps(
        biz_content,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    params["sign"] = _sign_params(params, config["private_key_pem"])

    checkout_url = f"{config['gateway']}?{urlencode(params)}"

    return {
        "out_trade_no": out_trade_no,
        "checkout_url": checkout_url,
        "total_amount": total_amount,
    }


def query_trade_status(out_trade_no: str) -> str | None:
    """Actively query Alipay for the trade status of an order (alipay.trade.query).

    Returns the Alipay trade_status string (e.g. "TRADE_SUCCESS",
    "WAIT_BUYER_PAY", "TRADE_CLOSED") or None when the order is not found /
    cannot be queried. This is the reliable confirmation path for PagePay: the
    async webhook can be lost or blocked, so status polling must be able to fall
    back to querying the gateway directly instead of waiting forever.
    """
    import json

    try:
        config = _load_alipay_config()
    except RuntimeError:
        return None

    biz_content = {"out_trade_no": out_trade_no}
    params = _build_common_params(config, "alipay.trade.query")
    params["biz_content"] = json.dumps(
        biz_content,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    params["sign"] = _sign_params(params, config["private_key_pem"])

    try:
        import httpx

        response = httpx.get(config["gateway"], params=params, timeout=8.0)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return None

    # Alipay wraps the result under alipay_trade_query_response.
    body = data.get("alipay_trade_query_response") or {}
    if str(body.get("code", "")) != "10000":
        return None
    trade_status = body.get("trade_status")
    return str(trade_status) if trade_status else None


def reconcile_pending_subscription(engine: Engine, out_trade_no: str) -> Subscription | None:
    """Query Alipay for a pending order and activate it if already paid.

    Used as a fallback when the async webhook has not (yet) arrived. Idempotent:
    returns the active subscription without re-querying if it is already active.
    """
    sub = find_pending_subscription(engine, out_trade_no)
    if sub is None:
        return None
    if sub.status == "active":
        return sub
    trade_status = query_trade_status(out_trade_no)
    if trade_status not in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
        return None
    return activate_subscription(
        engine,
        user_id=sub.user_id,
        out_trade_no=out_trade_no,
        alipay_trade_no=sub.alipay_trade_no or "",
    )


def expire_stale_subscriptions(engine: Engine, user_id: str) -> None:
    """Lazily flip active subscriptions whose period has ended to "expired".

    The active-subscription query already filters by current_period_end, so this
    is purely to keep the stored status column honest (for admin/reporting and so
    the UI can distinguish "never subscribed" from "expired").
    """
    with session_scope(engine) as session:
        now = datetime.utcnow()
        stale = session.execute(
            select(Subscription)
            .where(Subscription.user_id == user_id)
            .where(Subscription.status == "active")
            .where(Subscription.current_period_end.isnot(None))
            .where(Subscription.current_period_end <= now)
        ).scalars().all()
        for row in stale:
            row.status = "expired"


def verify_webhook_signature(params: dict[str, str], alipay_public_key_pem: str) -> bool:
    """Verify Alipay webhook RSA2 signature.

    1. Drop sign and sign_type from params
    2. Sort keys, join key=value&...
    3. Verify with Alipay public key (SHA256)
    """
    sign = params.get("sign", "")
    if not sign:
        return False
    sign_string = "&".join(
        f"{k}={v}"
        for k, v in sorted(params.items())
        if v and k not in {"sign", "sign_type"}
    )
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
    except ImportError:
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
    try:
        public_key = load_pem_public_key(
            _wrap_public_key_pem(alipay_public_key_pem).encode("utf-8"),
            backend=default_backend(),
        )
    except Exception:
        return False
    try:
        public_key.verify(
            base64.b64decode(sign),
            sign_string.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except Exception:
        return False


def get_active_subscription(engine: Engine, user_id: str) -> Subscription | None:
    """Return the user's currently active subscription, or None."""
    with session_scope(engine) as session:
        row = session.execute(
            select(Subscription)
            .where(Subscription.user_id == user_id)
            .where(Subscription.status == "active")
            .where(Subscription.current_period_end > datetime.utcnow())
            .order_by(Subscription.current_period_end.desc())
            .limit(1)
        ).scalars().first()
        return row


def activate_subscription(
    engine: Engine,
    *,
    user_id: str,
    out_trade_no: str,
    alipay_trade_no: str,
) -> Subscription:
    """Mark a subscription active for 30 days from now. Create User if missing."""
    with session_scope(engine) as session:
        # Ensure User exists
        user = session.get(User, user_id)
        if user is None:
            user = User(id=user_id, free_polish_used=0)
            session.add(user)

        # Look up pending subscription by out_trade_no, else create
        sub = session.execute(
            select(Subscription)
            .where(Subscription.out_trade_no == out_trade_no)
            .limit(1)
        ).scalars().first()
        now = datetime.utcnow()
        period_end = now + timedelta(days=SUBSCRIPTION_DURATION_DAYS)
        if sub is None:
            sub = Subscription(
                user_id=user_id,
                status="active",
                alipay_trade_no=alipay_trade_no,
                out_trade_no=out_trade_no,
                current_period_end=period_end,
                paid_at=now,
            )
            session.add(sub)
        else:
            sub.status = "active"
            sub.alipay_trade_no = alipay_trade_no
            sub.current_period_end = period_end
            sub.paid_at = now
        session.flush()
        return sub


def find_pending_subscription(engine: Engine, out_trade_no: str) -> Subscription | None:
    with session_scope(engine) as session:
        return session.execute(
            select(Subscription).where(Subscription.out_trade_no == out_trade_no).limit(1)
        ).scalars().first()


def create_pending_subscription(engine: Engine, *, user_id: str, out_trade_no: str) -> Subscription:
    """Record a pending subscription row right after precreate, so webhook can match it."""
    with session_scope(engine) as session:
        user = session.get(User, user_id)
        if user is None:
            user = User(id=user_id, free_polish_used=0)
            session.add(user)
        sub = Subscription(
            user_id=user_id,
            status="inactive",
            out_trade_no=out_trade_no,
        )
        session.add(sub)
        session.flush()
        return sub
