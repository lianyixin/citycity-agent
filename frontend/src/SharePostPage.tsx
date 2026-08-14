import { useEffect, useState } from 'react';
import { useLogto } from '@logto/react';
import { fetchPost, Post, toggleFavorite, toggleLike } from './api';
import ExportModal from './ExportModal';
import LoginRequiredModal from './LoginRequiredModal';
import { useGeolocation } from './geo';
import PostDetailArticle from './PostDetailArticle';
import { postShareUrl } from './postShare';

type SharePostPageProps = {
  postId: number;
};

async function copyShareUrl(postId: number): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(postShareUrl(postId));
    return true;
  } catch {
    return false;
  }
}

export default function SharePostPage({ postId }: SharePostPageProps) {
  const [post, setPost] = useState<Post | null>(null);
  const [activeImage, setActiveImage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [exportModalOpen, setExportModalOpen] = useState(false);
  const [loginRequired, setLoginRequired] = useState(false);
  const geo = useGeolocation();
  const { signIn } = useLogto();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    void fetchPost(postId)
      .then((item) => {
        if (cancelled) return;
        setPost(item);
        document.title = `${item.title} · 上海City不City`;
      })
      .catch(() => {
        if (!cancelled) setError('内容暂时不可访问');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      document.title = '上海City不City';
    };
  }, [postId]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(''), 2400);
    return () => window.clearTimeout(timer);
  }, [toast]);

  function patchPost(patch: Partial<Post>) {
    setPost((current) => (current ? { ...current, ...patch } : current));
  }

  async function handleShare() {
    const copied = await copyShareUrl(postId);
    window.open(postShareUrl(postId), '_blank', 'noopener,noreferrer');
    setToast(copied ? '链接已复制，已在新页面打开' : '已在新页面打开分享页');
  }

  return (
    <div className="share-page">
      {toast && <div className="toast">{toast}</div>}

      <header className="share-page-topbar">
        <a className="share-page-brand" href={window.location.pathname}>
          <img src="/brand-logo.png" alt="" className="brand-logo" />
          <strong>上海City不City</strong>
        </a>
        <div className="share-page-actions">
          <button
            type="button"
            className="ghost"
            onClick={async () => {
              const copied = await copyShareUrl(postId);
              setToast(copied ? '链接已复制' : '复制失败，请手动复制地址栏链接');
            }}
          >
            复制链接
          </button>
          <a className="primary share-page-home" href={window.location.pathname}>
            去首页发现更多
          </a>
        </div>
      </header>

      <main className="share-page-body">
        {loading && <p className="share-page-status">正在加载玩法卡片…</p>}
        {!loading && error && <p className="banner error share-page-status">{error}</p>}
        {!loading && post && (
          <PostDetailArticle
            post={post}
            activeImage={activeImage}
            layout="page"
            userCoords={geo.coords}
            geoStatus={geo.status}
            onRequestLocation={geo.refresh}
            onImageChange={setActiveImage}
            onLike={async () => {
              const result = await toggleLike(post.id);
              patchPost({ is_liked: result.is_liked, like_count: result.like_count });
            }}
            onFavorite={async () => {
              const result = await toggleFavorite(post.id);
              patchPost({ is_favorited: result.is_favorited, favorite_count: result.favorite_count });
            }}
            onExport={() => setExportModalOpen(true)}
            onShare={() => void handleShare()}
          />
        )}
      </main>

      {post && exportModalOpen && (
        <ExportModal
          post={post}
          onClose={() => setExportModalOpen(false)}
          onLoginRequired={() => {
            setLoginRequired(true);
            setExportModalOpen(false);
          }}
        />
      )}

      {loginRequired && (
        <LoginRequiredModal
          onLogin={() => {
            setLoginRequired(false);
            const origin = window.location.origin;
            void signIn(`${origin}/callback`);
          }}
          onClose={() => setLoginRequired(false)}
        />
      )}
    </div>
  );
}
