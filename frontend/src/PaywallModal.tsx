import { SubscriptionRequiredError } from './api';

type Props = {
  error: SubscriptionRequiredError;
  onSubscribe: () => void;
  onClose: () => void;
};

export default function PaywallModal({ error, onSubscribe, onClose }: Props) {
  return (
    <div className="paywall-overlay">
      <div className="paywall-modal">
        <button className="paywall-close" onClick={onClose}>×</button>
        <div className="paywall-icon">🔒</div>
        <h2>免费润色次数已用完</h2>
        <p className="paywall-usage">
          已使用 {error.free_used}/{error.free_limit} 次免费润色
        </p>
        <p className="paywall-desc">
          订阅会员，无限次使用 AI 图片润色，享更多权益
        </p>
        <div className="paywall-price">¥9.9 / 月</div>
        <button type="button" className="paywall-subscribe-btn" onClick={onSubscribe}>
          立即订阅
        </button>
        <button type="button" className="paywall-later-btn" onClick={onClose}>
          稍后再说
        </button>
      </div>
    </div>
  );
}
