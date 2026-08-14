import { useEffect, useState } from 'react';
import { useLogto } from '@logto/react';
import {
  createSubscription,
  fetchSubscriptionStatus,
  LoginRequiredError,
  type SubscriptionCreateResponse,
  type SubscriptionStatusResponse,
} from './api';

type Props = {
  onClose: () => void;
  onSubscribed?: () => void;
};

const DEFAULT_FREE_LIMIT = 2;

export default function SubscriptionPage({ onClose, onSubscribed }: Props) {
  const { isAuthenticated, signIn } = useLogto();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [order, setOrder] = useState<SubscriptionCreateResponse | null>(null);
  const [status, setStatus] = useState<SubscriptionStatusResponse | null>(null);
  const [statusReady, setStatusReady] = useState(false);
  const [polling, setPolling] = useState(false);

  // Ensure auth token is wired for subscription API calls
  useEffect(() => {
    if (!isAuthenticated) {
      setStatus(null);
      setStatusReady(false);
      return;
    }
    let cancelled = false;
    void fetchSubscriptionStatus()
      .then((data) => {
        if (cancelled) return;
        setStatus(data);
        setStatusReady(true);
      })
      .catch((err) => {
        if (cancelled) return;
        setStatusReady(true);
        if (err instanceof LoginRequiredError) {
          setError(err.message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated]);

  // Poll subscription status after order is created. We pass the order's
  // out_trade_no so the backend actively queries Alipay (alipay.trade.query) as
  // a fallback when the async webhook is delayed or blocked, otherwise the user
  // could pay and never see their membership activate.
  useEffect(() => {
    if (!order || !isAuthenticated) return;
    setPolling(true);
    let done = false;

    const check = () => {
      void fetchSubscriptionStatus(order.out_trade_no)
        .then((data) => {
          setStatus(data);
          if (data.has_active_subscription && !done) {
            done = true;
            window.clearInterval(timer);
            setPolling(false);
            onSubscribed?.();
          }
        })
        .catch(() => {
          /* keep polling */
        });
    };

    const timer = window.setInterval(check, 3000);
    // Re-check immediately when the user switches back from the Alipay tab.
    const onFocus = () => check();
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onFocus);

    return () => {
      window.clearInterval(timer);
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onFocus);
      setPolling(false);
    };
  }, [order, isAuthenticated, onSubscribed]);

  async function handleCreateOrder() {
    setLoading(true);
    setError('');
    try {
      const result = await createSubscription();
      setOrder(result);
      window.open(result.checkout_url, '_blank', 'noopener,noreferrer');
    } catch (err) {
      if (err instanceof LoginRequiredError) {
        setError(err.message);
      } else {
        setError(err instanceof Error ? err.message : '创建订单失败，请重试');
      }
    } finally {
      setLoading(false);
    }
  }

  if (!isAuthenticated) {
    return (
      <div className="subscription-overlay">
        <div className="subscription-modal">
          <button className="subscription-close" onClick={onClose}>
            ×
          </button>
          <h2>订阅上海City不City会员</h2>
          <p className="subscription-price">¥9.9 / 月</p>
          <ul className="subscription-benefits">
            <li>无限次 AI 图片润色</li>
            <li>高清导出所有玩法图片</li>
            <li>优先体验新功能</li>
          </ul>
          <p className="subscription-login-hint">请先登录后订阅</p>
          <button
            type="button"
            className="subscription-login-btn"
            onClick={() => {
              const origin = window.location.origin;
              void signIn(`${origin}/callback`);
            }}
          >
            登录 / 注册
          </button>
        </div>
      </div>
    );
  }

  if (status?.has_active_subscription) {
    return (
      <div className="subscription-overlay">
        <div className="subscription-modal">
          <button className="subscription-close" onClick={onClose}>
            ×
          </button>
          <h2>✅ 已是会员</h2>
          <p>你的会员有效，可无限次使用图片润色。</p>
          {status.subscription_expires_at && (
            <p className="subscription-expires">
              到期时间：{status.subscription_expires_at.slice(0, 10)}
            </p>
          )}
          <button type="button" className="subscription-close-btn" onClick={onClose}>
            关闭
          </button>
        </div>
      </div>
    );
  }

  const freeLimit = status?.free_polish_limit ?? DEFAULT_FREE_LIMIT;
  const freeUsed = status?.free_polish_used ?? 0;
  const freeRemaining = Math.max(0, freeLimit - freeUsed);

  return (
    <div className="subscription-overlay">
      <div className="subscription-modal">
        <button className="subscription-close" onClick={onClose}>
          ×
        </button>
        <h2>订阅上海City不City会员</h2>
        <p className="subscription-price">¥9.9 / 月</p>
        <ul className="subscription-benefits">
          <li>无限次 AI 图片润色</li>
          <li>高清导出所有玩法图片</li>
          <li>优先体验新功能</li>
        </ul>

        {!order && (
          <div className="subscription-order-section">
            <button
              type="button"
              className="subscription-create-btn"
              disabled={loading}
              onClick={handleCreateOrder}
            >
              {loading ? '创建订单中…' : '立即订阅 ¥9.9'}
            </button>
            {error && <p className="subscription-error">{error}</p>}
            <p className="subscription-free-info">
              {!statusReady
                ? '正在同步免费额度…'
                : `免费额度已用 ${freeUsed}/${freeLimit} 次${freeRemaining > 0 ? `（剩余 ${freeRemaining}）` : '（已用完）'}`}
            </p>
          </div>
        )}

        {order && (
          <div className="subscription-qr-section">
            <p className="subscription-qr-hint">请在支付宝收银台完成支付</p>
            <a
              className="subscription-create-btn"
              href={order.checkout_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              打开支付宝支付
            </a>
            <p className="subscription-amount">支付金额：¥{order.total_amount}</p>
            <p className="subscription-polling">{polling ? '等待支付结果…' : '✅ 支付成功'}</p>
          </div>
        )}
      </div>
    </div>
  );
}
