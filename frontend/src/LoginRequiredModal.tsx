type Props = {
  onLogin: () => void;
  onClose: () => void;
};

export default function LoginRequiredModal({ onLogin, onClose }: Props) {
  return (
    <div className="login-required-overlay" onClick={onClose}>
      <div className="login-required-modal" onClick={(event) => event.stopPropagation()}>
        <button className="login-required-close" onClick={onClose} aria-label="关闭">
          ×
        </button>
        <div className="login-required-icon">🔐</div>
        <h2>请先登录</h2>
        <p className="login-required-desc">
          登录后即可使用 AI 图片润色功能，还可同步你的润色历史与订阅状态。
        </p>
        <button type="button" className="login-required-btn" onClick={onLogin}>
          登录 / 注册
        </button>
        <button type="button" className="login-required-later-btn" onClick={onClose}>
          稍后再说
        </button>
      </div>
    </div>
  );
}
