import { useCallback, useEffect, useRef, useState } from 'react';
import { useLogto } from '@logto/react';
import { fetchAuthMe, setAccessTokenGetter, type AuthMeResponse } from './api';
import { postLogoutRedirectUri } from './auth';
import { trackLogin, trackLogout } from './analytics';

type Props = {
  onOpenSubscription: () => void;
  /** Bump this to force a re-fetch of /api/auth/me (e.g. right after payment). */
  refreshSignal?: number;
};

type MeLoadState = 'idle' | 'loading' | 'ready' | 'error';

const DEFAULT_FREE_LIMIT = 2;

export default function AuthMenu({ onOpenSubscription, refreshSignal = 0 }: Props) {
  const { isAuthenticated, signIn, signOut, getIdToken } = useLogto();
  const [me, setMe] = useState<AuthMeResponse | null>(null);
  const [meState, setMeState] = useState<MeLoadState>('idle');
  const [menuOpen, setMenuOpen] = useState(false);
  const wasAuthenticated = useRef(false);

  // Track login when authentication state transitions to true
  useEffect(() => {
    if (isAuthenticated && !wasAuthenticated.current) {
      trackLogin();
    }
    wasAuthenticated.current = isAuthenticated;
  }, [isAuthenticated]);

  // Wire ID token getter so api.ts can attach Bearer headers.
  // ID token is always a JWT with the user's sub - verifiable by backend JWKS.
  useEffect(() => {
    setAccessTokenGetter(async () => {
      if (!isAuthenticated) return undefined;
      try {
        const token = await getIdToken();
        return token ?? undefined;
      } catch {
        return undefined;
      }
    });
    return () => setAccessTokenGetter(null);
  }, [isAuthenticated, getIdToken]);

  // Fetch /api/auth/me only after a real JWT is available.
  const refreshMe = useCallback(
    (signal?: { cancelled: boolean }) => {
      setMeState('loading');
      void fetchAuthMe()
        .then((data) => {
          if (signal?.cancelled) return;
          if (!data.authenticated) {
            setMe(null);
            setMeState('error');
            return;
          }
          setMe(data);
          setMeState('ready');
        })
        .catch(() => {
          if (signal?.cancelled) return;
          setMe(null);
          setMeState('error');
        });
    },
    [],
  );

  useEffect(() => {
    if (!isAuthenticated) {
      setMe(null);
      setMeState('idle');
      return;
    }
    const signal = { cancelled: false };
    refreshMe(signal);
    // Re-sync when the tab regains focus (e.g. returning from Alipay checkout).
    const onFocus = () => refreshMe();
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onFocus);
    return () => {
      signal.cancelled = true;
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onFocus);
    };
  }, [isAuthenticated, refreshSignal, refreshMe]);

  if (!isAuthenticated) {
    return (
      <button
        type="button"
        className="auth-login-btn"
        onClick={() => {
          const origin = window.location.origin;
          void signIn(`${origin}/callback`);
        }}
      >
        登录
      </button>
    );
  }

  const sub = me?.subscription;
  const freeLimit = sub?.free_polish_limit ?? DEFAULT_FREE_LIMIT;
  // Display as used/limit (0/2 → 2/2). While loading or sync failed, assume unused.
  const freeUsed = meState === 'ready' && sub ? sub.free_polish_used : 0;
  const freeRemaining = Math.max(0, freeLimit - freeUsed);

  const triggerLabel = sub?.has_active_subscription
    ? '⭐ 会员'
    : meState === 'loading'
      ? `免费 …/${freeLimit}`
      : `免费 ${freeUsed}/${freeLimit}`;

  return (
    <div className="auth-menu">
      <button
        type="button"
        className="auth-menu-trigger"
        onClick={() => setMenuOpen((v) => !v)}
      >
        {triggerLabel}
      </button>
      {menuOpen && (
        <div className="auth-menu-dropdown">
          <div className="auth-menu-item auth-menu-status">
            {sub?.has_active_subscription ? (
              <span>
                会员有效
                <br />
                到期：{sub.subscription_expires_at?.slice(0, 10) ?? '—'}
                {typeof sub.subscription_days_remaining === 'number' && (
                  <>
                    <br />
                    {sub.subscription_expiring_soon
                      ? `⚠️ 还剩 ${sub.subscription_days_remaining} 天，即将到期`
                      : `剩余 ${sub.subscription_days_remaining} 天`}
                  </>
                )}
              </span>
            ) : meState === 'loading' ? (
              <span>正在同步额度…</span>
            ) : meState === 'error' ? (
              <span>
                额度同步失败
                <br />
                默认已用 0/{DEFAULT_FREE_LIMIT} 次
              </span>
            ) : (
              <span>
                {sub?.subscription_expired_at && (
                  <>
                    会员已到期（{sub.subscription_expired_at.slice(0, 10)}）
                    <br />
                  </>
                )}
                免费润色已用 {freeUsed}/{freeLimit} 次
                {freeRemaining > 0 ? `（剩余 ${freeRemaining}）` : '（已用完）'}
              </span>
            )}
          </div>
          {!sub?.has_active_subscription && (
            <button
              type="button"
              className="auth-menu-item auth-menu-subscribe"
              onClick={() => {
                setMenuOpen(false);
                onOpenSubscription();
              }}
            >
              {sub?.subscription_expired_at ? '续订会员 ¥9.9/月' : '订阅会员 ¥9.9/月'}
            </button>
          )}
          <button
            type="button"
            className="auth-menu-item auth-menu-logout"
            onClick={() => {
              const origin = window.location.origin;
              trackLogout();
              void signOut(postLogoutRedirectUri(origin));
            }}
          >
            退出登录
          </button>
        </div>
      )}
    </div>
  );
}
