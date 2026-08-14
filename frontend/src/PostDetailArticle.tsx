import { Post } from './api';
import { Coords } from './geo';
import MarkdownContent from './MarkdownContent';
import { AuthorBadge, EXPORT_TIP, formatCount, PostCreatedAt } from './postUi';
import RouteTimeline from './RouteTimeline';

type PostDetailArticleProps = {
  post: Post;
  activeImage: number;
  layout: 'modal' | 'page';
  userCoords: Coords | null;
  geoStatus: string;
  onRequestLocation: () => void;
  onImageChange: (index: number) => void;
  onLike: () => void;
  onFavorite: () => void;
  onExport: () => void;
  onShare: () => void;
  onClose?: () => void;
};

export default function PostDetailArticle({
  post,
  activeImage,
  layout,
  userCoords,
  geoStatus,
  onRequestLocation,
  onImageChange,
  onLike,
  onFavorite,
  onExport,
  onShare,
  onClose,
}: PostDetailArticleProps) {
  const total = post.images.length;
  const articleClass = layout === 'page' ? 'detail share-detail' : 'detail';

  function showImage(index: number) {
    if (total === 0) return;
    onImageChange(((index % total) + total) % total);
  }

  return (
    <article
      className={articleClass}
      onClick={layout === 'modal' ? (event) => event.stopPropagation() : undefined}
    >
      {layout === 'modal' && onClose && (
        <button className="detail-close" onClick={onClose} aria-label="关闭">
          ×
        </button>
      )}
      <div className="detail-media">
        {post.images.length > 0 ? (
          <>
            <div className="carousel">
              <img src={post.images[activeImage]} alt={post.title} />
              <button
                type="button"
                className="image-polish-hint"
                onClick={onExport}
                aria-label="使用 AI 图片润色"
              >
                <span className="image-polish-hint-icon">✨</span>
                <span className="image-polish-hint-text">图片质量不好？一键让图片更出片</span>
              </button>
              {post.images.length > 1 && (
                <>
                  <button
                    type="button"
                    className="carousel-nav prev"
                    onClick={() => showImage(activeImage - 1)}
                    aria-label="上一张"
                  >
                    ‹
                  </button>
                  <button
                    type="button"
                    className="carousel-nav next"
                    onClick={() => showImage(activeImage + 1)}
                    aria-label="下一张"
                  >
                    ›
                  </button>
                  <span className="carousel-counter">
                    {activeImage + 1} / {post.images.length}
                  </span>
                </>
              )}
            </div>
            {post.images.length > 1 && (
              <div className="thumbs">
                {post.images.map((image, index) => (
                  <button
                    key={image}
                    className={index === activeImage ? 'thumb active' : 'thumb'}
                    onClick={() => showImage(index)}
                  >
                    <img src={image} alt="" />
                  </button>
                ))}
              </div>
            )}
          </>
        ) : (
          <div className="cover-fallback large">
            <span>{post.title.slice(0, 2)}</span>
          </div>
        )}
      </div>
      <div className="detail-body">
        <div className="detail-top">
          <div className="detail-title-row">
            <h2>{post.title}</h2>
            <div className="detail-title-actions">
              <button
                type="button"
                className="detail-icon-action export"
                onClick={onExport}
                disabled={post.images.length === 0}
                data-tip={EXPORT_TIP}
                aria-label={EXPORT_TIP}
              >
                ⇩
              </button>
              <button
                type="button"
                className="detail-icon-action share"
                onClick={onShare}
                data-tip="分享链接"
                aria-label="分享链接"
              >
                ↗
              </button>
            </div>
          </div>
          <div className="detail-meta">
            <AuthorBadge post={post} />
            <PostCreatedAt post={post} />
          </div>
        </div>
        {post.route_groups && post.route_groups.length > 0 && (
          <div className="detail-route-panel">
            <RouteTimeline
              routeGroups={post.route_groups}
              userCoords={userCoords}
              geoStatus={geoStatus}
              onRequestLocation={onRequestLocation}
            />
          </div>
        )}
        <div className="detail-scroll">
          <MarkdownContent content={post.content} className="detail-content markdown-content" />
          <div className="tags">
            {post.tags.map((tag) => (
              <span key={tag}>#{tag}</span>
            ))}
          </div>
          <div className="detail-actions">
            <button className={post.is_liked ? 'react liked' : 'react'} onClick={onLike}>
              ♥ 点赞 {formatCount(post.like_count)}
            </button>
            <button className={post.is_favorited ? 'react saved' : 'react'} onClick={onFavorite}>
              ☆ 收藏 {formatCount(post.favorite_count)}
            </button>
          </div>
        </div>
      </div>
    </article>
  );
}
