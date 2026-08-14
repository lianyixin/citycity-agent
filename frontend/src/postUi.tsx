import { Post } from './api';

export const EXPORT_TIP = '润色图片后导出zip';

export const PLATFORM_AUTHOR = {
  name: '上海City不City',
  avatar_text: '城',
  avatar_url: '/brand-logo.png',
};

export function formatCount(count: number): string {
  if (count >= 10000) return `${(count / 10000).toFixed(1)}w`;
  if (count >= 1000) return `${(count / 1000).toFixed(1)}k`;
  return `${count}`;
}

function authorFor(post: Post) {
  return post.author ?? PLATFORM_AUTHOR;
}

function parseUtcDate(iso: string): Date {
  const raw = iso.trim();
  if (!raw) return new Date(NaN);
  if (/[zZ]$|[+-]\d{2}:\d{2}$/.test(raw)) return new Date(raw);
  return new Date(`${raw}Z`);
}

function formatPostTime(iso: string): string {
  const date = parseUtcDate(iso);
  if (Number.isNaN(date.getTime())) return '';
  const diffMs = Date.now() - date.getTime();
  if (diffMs < 60_000) return '刚刚';
  if (diffMs < 3_600_000) return `${Math.floor(diffMs / 60_000)}分钟前`;
  if (diffMs < 86_400_000) return `${Math.floor(diffMs / 3_600_000)}小时前`;
  if (diffMs < 7 * 86_400_000) return `${Math.floor(diffMs / 86_400_000)}天前`;
  return date.toLocaleDateString('zh-CN', { year: 'numeric', month: 'numeric', day: 'numeric' });
}

export function AuthorBadge({ post }: { post: Post }) {
  const author = authorFor(post);
  return (
    <span className="author">
      {author.avatar_url ? (
        <img src={author.avatar_url} alt="" className="author-logo" />
      ) : (
        <span className="author-logo author-logo-text">{author.avatar_text || author.name.slice(0, 1)}</span>
      )}
      {author.name}
    </span>
  );
}

const GENERATED_SOURCE_TYPES = new Set(['user_generated', 'platform_auto']);

export function PostCreatedAt({ post }: { post: Post }) {
  if (!GENERATED_SOURCE_TYPES.has(post.source_type)) return null;
  const text = formatPostTime(post.created_at);
  if (!text) return null;
  return (
    <time className="post-time" dateTime={post.created_at}>
      {text}
    </time>
  );
}
