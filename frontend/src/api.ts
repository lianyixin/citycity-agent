export type Place = {
  name: string;
  address?: string | null;
  lat: number;
  lng: number;
  category?: string | null;
  rating?: number | null;
  amap_poi_id?: string | null;
  method_order?: number;
  method_title?: string | null;
};

export type RouteGroup = {
  section_index: number;
  section_label: string;
  title: string;
  places: Place[];
};

export type GenerationLogItem = {
  id: number;
  generation_request_id: number | null;
  stage: string;
  level: string;
  message: string;
  created_at: string;
};

export type GenerationStartResponse = {
  generation_request_id: number;
  status: string;
};

export type GenerationStatusResponse = {
  generation_request_id: number;
  status: 'pending' | 'running' | 'success' | 'failed';
  post_id: number | null;
  error_message: string | null;
  logs: GenerationLogItem[];
};

export type FeedSort = 'recommend' | 'time' | 'popular' | 'distance';

export type Post = {
  id: number;
  title: string;
  content: string;
  tags: string[];
  images: string[];
  cover_image?: string | null;
  source_query?: string | null;
  source_type: string;
  like_count: number;
  favorite_count: number;
  is_liked: boolean;
  is_favorited: boolean;
  created_at: string;
  author?: {
    name: string;
    avatar_text?: string | null;
    avatar_url?: string | null;
    type?: string;
    id?: string;
  };
  generation_request_id?: number;
  generation_logs?: Array<{
    id: number;
    stage: string;
    level: string;
    message: string;
    created_at: string;
  }>;
  places?: Place[];
  route_groups?: RouteGroup[];
  distance_meters?: number | null;
};

export type PostPage = {
  items: Post[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
  sort?: FeedSort;
};

export type GeneratePayload = {
  query: string;
  location_text?: string;
  location_lat?: number;
  location_lng?: number;
  time_context?: string;
  companion_type?: string;
  preference_tags: string[];
};

export type LocationSuggestion = {
  name: string;
  address: string;
  lat: number;
  lng: number;
  source: string;
  amap_id?: string | null;
};

// API base is injected by the Haven runner at preview build time so /api
// requests reach the reverse-proxied backend. Defaults to same-origin.
const API_BASE = import.meta.env.VITE_API_BASE ?? '';
const USER_KEY = 'citycity_user_id';

/** Subscription required error thrown when polish endpoint returns 402. */
export class SubscriptionRequiredError extends Error {
  free_used: number;
  free_limit: number;
  has_active_subscription: boolean;
  constructor(detail: {
    message?: string;
    free_used?: number;
    free_limit?: number;
    has_active_subscription?: boolean;
  }) {
    super(detail.message || '免费润色次数已用完，请订阅后继续使用');
    this.name = 'SubscriptionRequiredError';
    this.free_used = detail.free_used ?? 0;
    this.free_limit = detail.free_limit ?? 2;
    this.has_active_subscription = detail.has_active_subscription ?? false;
  }
}

/** Login required error thrown when an auth-required endpoint returns 401. */
export class LoginRequiredError extends Error {
  constructor(message = '请先登录后再继续') {
    super(message);
    this.name = 'LoginRequiredError';
  }
}

/** Auth token provider — set by AuthProvider so api.ts can read it without React context. */
let accessTokenGetter: (() => Promise<string | undefined>) | null = null;

export function setAccessTokenGetter(getter: (() => Promise<string | undefined>) | null) {
  accessTokenGetter = getter;
}

/**
 * Wait until the Logto token bridge can return a JWT.
 * `isAuthenticated` can become true before getIdToken() is ready; callers must
 * gate protected API calls on a real token, not the boolean alone.
 */
export async function waitForAccessToken(options?: {
  timeoutMs?: number;
  intervalMs?: number;
}): Promise<string | undefined> {
  const timeoutMs = options?.timeoutMs ?? 4000;
  const intervalMs = options?.intervalMs ?? 150;
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (!accessTokenGetter) {
      await new Promise((resolve) => window.setTimeout(resolve, intervalMs));
      continue;
    }
    try {
      const token = await accessTokenGetter();
      if (token) return token;
    } catch {
      /* retry until timeout */
    }
    await new Promise((resolve) => window.setTimeout(resolve, intervalMs));
  }
  if (!accessTokenGetter) return undefined;
  try {
    return (await accessTokenGetter()) ?? undefined;
  } catch {
    return undefined;
  }
}

function generateId(): string {
  const globalCrypto = typeof crypto !== 'undefined' ? crypto : undefined;
  if (globalCrypto && typeof globalCrypto.randomUUID === 'function') {
    return globalCrypto.randomUUID();
  }
  if (globalCrypto && typeof globalCrypto.getRandomValues === 'function') {
    const bytes = globalCrypto.getRandomValues(new Uint8Array(16));
    return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  }
  return `${Date.now().toString(16)}${Math.random().toString(16).slice(2)}`;
}

export function getUserId(): string {
  const existing = localStorage.getItem(USER_KEY);
  if (existing) return existing;
  const created = `web_${generateId()}`;
  localStorage.setItem(USER_KEY, created);
  return created;
}

export async function fetchPosts(
  page = 1,
  pageSize = 20,
  options?: { sort?: FeedSort; lat?: number; lng?: number; tag?: string },
): Promise<PostPage> {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
    user_id: getUserId(),
    sort: options?.sort ?? 'recommend',
  });
  if (options?.lat != null && options?.lng != null) {
    params.set('lat', String(options.lat));
    params.set('lng', String(options.lng));
  }
  if (options?.tag?.trim()) {
    params.set('tag', options.tag.trim());
  }
  return request(`/api/posts?${params.toString()}`);
}

export async function fetchHotTags(limit = 12): Promise<string[]> {
  const payload = await request<{ items: Array<{ tag: string; count: number }> }>(
    `/api/tags/hot?limit=${limit}`,
  );
  return payload.items.map((item) => item.tag);
}

export async function searchPosts(query: string, page = 1, pageSize = 20): Promise<PostPage> {
  const params = new URLSearchParams({
    query,
    page: String(page),
    page_size: String(pageSize),
    user_id: getUserId(),
  });
  return request(`/api/search?${params.toString()}`);
}

export async function toggleLike(postId: number): Promise<{ is_liked: boolean; like_count: number }> {
  return request(`/api/posts/${postId}/like`, {
    method: 'POST',
    body: JSON.stringify({ user_id: getUserId() }),
  });
}

export async function toggleFavorite(postId: number): Promise<{ is_favorited: boolean; favorite_count: number }> {
  return request(`/api/posts/${postId}/favorite`, {
    method: 'POST',
    body: JSON.stringify({ user_id: getUserId() }),
  });
}

export async function startGeneration(payload: GeneratePayload): Promise<GenerationStartResponse> {
  return request('/api/generate', {
    method: 'POST',
    body: JSON.stringify({ ...payload, user_id: getUserId() }),
  });
}

export async function fetchGenerationStatus(
  requestId: number,
  afterLogId?: number,
): Promise<GenerationStatusResponse> {
  const params = new URLSearchParams();
  if (afterLogId) params.set('after_log_id', String(afterLogId));
  const query = params.toString();
  return request(`/api/generation-requests/${requestId}${query ? `?${query}` : ''}`);
}

export async function fetchPost(postId: number): Promise<Post> {
  return request(`/api/posts/${postId}?user_id=${encodeURIComponent(getUserId())}`);
}

/** @deprecated 请使用 startGeneration + fetchGenerationStatus 轮询 */
export async function generatePost(payload: GeneratePayload): Promise<Post> {
  const started = await startGeneration(payload);
  let afterLogId = 0;
  while (true) {
    const status = await fetchGenerationStatus(started.generation_request_id, afterLogId || undefined);
    if (status.logs.length) {
      afterLogId = Math.max(afterLogId, ...status.logs.map((item) => item.id));
    }
    if (status.status === 'success' && status.post_id) {
      return fetchPost(status.post_id);
    }
    if (status.status === 'failed') {
      throw new Error(status.error_message || '生成失败');
    }
    await new Promise((resolve) => window.setTimeout(resolve, 700));
  }
}

export async function suggestLocations(payload: {
  query?: string;
  lat?: number;
  lng?: number;
}): Promise<LocationSuggestion[]> {
  const response = await request<{ items: LocationSuggestion[] }>('/api/locations/suggest', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return response.items;
}

export type ImagePolishStatus = {
  polish_request_id?: number;
  status: 'pending' | 'running' | 'success' | 'failed';
  original_url?: string;
  prompt?: string;
  polished_image_url?: string;
  error_message?: string;
  cached?: boolean;
};

export async function startImagePolish(imageUrl: string, prompt: string, postId?: number): Promise<ImagePolishStatus> {
  return request<ImagePolishStatus>('/api/images/polish', {
    method: 'POST',
    body: JSON.stringify({ image_url: imageUrl, prompt, post_id: postId }),
    auth: true,
  });
}

export async function fetchImagePolishStatus(requestId: number): Promise<ImagePolishStatus> {
  return request<ImagePolishStatus>(`/api/images/polish/${requestId}`, { auth: true });
}

/** Auth & subscription API */

export type SubscriptionStatus = {
  has_active_subscription: boolean;
  subscription_expires_at: string | null;
  subscription_expired_at: string | null;
  subscription_days_remaining: number | null;
  subscription_expiring_soon: boolean;
  free_polish_used: number;
  free_polish_limit: number;
  subscription_price_cents: number;
};

export type AuthMeResponse = {
  authenticated: boolean;
  user_id?: string;
  subscription?: SubscriptionStatus;
};

export async function fetchAuthMe(): Promise<AuthMeResponse> {
  return request<AuthMeResponse>('/api/auth/me', { auth: true });
}

export type SubscriptionCreateResponse = {
  out_trade_no: string;
  checkout_url: string;
  total_amount: string;
  price_cents: number;
};

export async function createSubscription(): Promise<SubscriptionCreateResponse> {
  return request<SubscriptionCreateResponse>('/api/subscriptions/create', {
    method: 'POST',
    body: JSON.stringify({}),
    auth: true,
  });
}

export type SubscriptionStatusResponse = SubscriptionStatus;

export async function fetchSubscriptionStatus(
  reconcileOutTradeNo?: string,
): Promise<SubscriptionStatusResponse> {
  const query = reconcileOutTradeNo
    ? `?reconcile=${encodeURIComponent(reconcileOutTradeNo)}`
    : '';
  return request<SubscriptionStatusResponse>(`/api/subscriptions/status${query}`, {
    auth: true,
  });
}

export type PolishedImageRecord = {
  original_url: string;
  polished_url: string;
  prompt: string;
  created_at: string;
};

export async function fetchPolishedImages(postId: number): Promise<PolishedImageRecord[]> {
  const response = await request<{ items: PolishedImageRecord[] }>(`/api/posts/${postId}/polished-images`);
  return response.items;
}

export async function exportPostZip(postId: number, imageUrls: string[]): Promise<Blob> {
  const response = await fetch(`${API_BASE}/api/posts/${postId}/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ image_urls: imageUrls }),
  });
  if (!response.ok) {
    const text = await response.text();
    try {
      const body = JSON.parse(text) as { detail?: unknown };
      if (typeof body.detail === 'string' && body.detail.trim()) {
        throw new Error(body.detail);
      }
    } catch (err) {
      if (err instanceof Error && err.message && !err.message.startsWith('{')) {
        throw err;
      }
    }
    throw new Error(text || `导出失败: ${response.status}`);
  }
  return response.blob();
}

async function request<T>(path: string, init?: RequestInit & { auth?: boolean }): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((init?.headers as Record<string, string>) ?? {}),
  };
  if (init?.auth) {
    const token = await waitForAccessToken();
    if (!token) {
      throw new LoginRequiredError('登录凭证尚未就绪，请稍后重试或重新登录');
    }
    headers['Authorization'] = `Bearer ${token}`;
  }
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  });
  if (!response.ok) {
    if (response.status === 402) {
      // Subscription required — parse detail and throw typed error
      try {
        const body = await response.json();
        const detail = body?.detail ?? body;
        throw new SubscriptionRequiredError({
          message: detail?.message,
          free_used: detail?.free_used,
          free_limit: detail?.free_limit,
          has_active_subscription: detail?.has_active_subscription,
        });
      } catch (parseErr) {
        if (parseErr instanceof SubscriptionRequiredError) throw parseErr;
        throw new SubscriptionRequiredError({});
      }
    }
    if (response.status === 401) {
      const loginHint = path.includes('/subscriptions')
        ? '请先登录后再订阅'
        : path.includes('/polish')
          ? '请先登录后再使用润色功能'
          : '请先登录后再继续';
      throw new LoginRequiredError(loginHint);
    }
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}
