export function postShareUrl(postId: number): string {
  return `${window.location.origin}${window.location.pathname}?post=${postId}`;
}

export function readSharePostId(): number | null {
  const id = Number(new URLSearchParams(window.location.search).get('post'));
  if (!Number.isFinite(id) || id <= 0) return null;
  return id;
}
