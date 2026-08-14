import { FormEvent, useEffect, useRef, useState } from 'react';
import { useLogto } from '@logto/react';
import {
  FeedSort,
  fetchGenerationStatus,
  fetchHotTags,
  fetchPost,
  fetchPosts,
  GenerationLogItem,
  LocationSuggestion,
  Post,
  searchPosts,
  startGeneration,
  suggestLocations,
  toggleFavorite,
  toggleLike,
} from './api';
import AuthMenu from './AuthMenu';
import { trackAIGenerate, trackAIPlanOpen, trackCardClick, trackHomepageView, trackSearch } from './analytics';
import LoginRequiredModal from './LoginRequiredModal';
import PaywallModal from './PaywallModal';
import SubscriptionPage from './SubscriptionPage';
import { SubscriptionRequiredError } from './api';
import { plainTextExcerpt } from './contentText';
import ExportModal from './ExportModal';
import { formatDistance, movedSignificantly, postMinDistanceMeters, useGeolocation, type Coords } from './geo';
import PostDetailArticle from './PostDetailArticle';
import { postShareUrl, readSharePostId } from './postShare';
import { AuthorBadge, EXPORT_TIP, formatCount } from './postUi';
import SharePostPage from './SharePostPage';

const preferenceOptions = ['拍照', '美食', 'Citywalk', '小众', '预算友好', '不累'];

const PAGE_SIZE = 20;
const GENERATION_POLL_MS = 700;
const HOME_GEO_REFRESH_MS = 120_000;
const FEED_SORT_OPTIONS: Array<{ id: FeedSort; label: string }> = [
  { id: 'recommend', label: '推荐' },
  { id: 'time', label: '最新' },
  { id: 'popular', label: '最热' },
  { id: 'distance', label: '离我最近' },
];

const STAGE_LABELS: Record<string, string> = {
  request: '任务',
  location: '定位',
  discovery: '玩法发现',
  workflow: '路线探索',
  planner: '灵感拓展',
  execute: '地点查找',
  agent: '进度',
  search: '地点查找',
  candidate_filter: '候选筛选',
  selection: '路线选定',
  xhs: '小红书生成',
  persist: '保存',
  error: '错误',
};

function parseUtcDate(iso: string): Date {
  const raw = iso.trim();
  if (!raw) return new Date(NaN);
  if (/[zZ]$|[+-]\d{2}:\d{2}$/.test(raw)) return new Date(raw);
  return new Date(`${raw}Z`);
}

function formatLogTime(iso: string): string {
  const date = parseUtcDate(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

const HIDDEN_USER_LOG_PHRASES = ['延展出', '正在查找', '玩法发现', '路线探索'] as const;
const HIDDEN_USER_LOG_STAGES = new Set(['discovery', 'workflow']);

function formatGenerationLog(log: GenerationLogItem): string {
  const label = STAGE_LABELS[log.stage];
  if (label) return `${label} · ${log.message}`;
  return log.message;
}

function isVisibleGenerationLog(log: GenerationLogItem): boolean {
  if (HIDDEN_USER_LOG_STAGES.has(log.stage)) return false;
  const display = formatGenerationLog(log);
  return !HIDDEN_USER_LOG_PHRASES.some((phrase) => display.includes(phrase));
}

function visibleGenerationLogs(logs: GenerationLogItem[]): GenerationLogItem[] {
  return logs.filter(isVisibleGenerationLog);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function liveDistanceForPost(post: Post, coords: Coords | null): number | null {
  if (!coords || !post.places?.length) return null;
  return postMinDistanceMeters(coords, post.places);
}

export default function App() {
  const sharePostId = readSharePostId();
  if (sharePostId !== null) {
    return <SharePostPage postId={sharePostId} />;
  }
  return <FeedApp />;
}

function FeedApp() {
  const { signIn } = useLogto();
  const [posts, setPosts] = useState<Post[]>([]);
  const [selectedPost, setSelectedPost] = useState<Post | null>(null);
  const [activeImage, setActiveImage] = useState(0);
  const [exportModalOpen, setExportModalOpen] = useState(false);
  const [exportPost, setExportPost] = useState<Post | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeTag, setActiveTag] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [page, setPage] = useState(1);
  const [feedMode, setFeedMode] = useState<'home' | 'search'>('home');
  const [homeSort, setHomeSort] = useState<FeedSort>('recommend');
  const [sortNotice, setSortNotice] = useState('');
  const [activeSearch, setActiveSearch] = useState('');
  const loadMoreRef = useRef<HTMLDivElement | null>(null);
  const lastFeedGeoRef = useRef<Coords | null>(null);
  const [hotTags, setHotTags] = useState<string[]>([]);
  const geo = useGeolocation();
  const [generating, setGenerating] = useState(false);
  const [generatorOpen, setGeneratorOpen] = useState(false);
  const [locationSuggestions, setLocationSuggestions] = useState<LocationSuggestion[]>([]);
  const [locationSuggesting, setLocationSuggesting] = useState(false);
  const [selectedLocation, setSelectedLocation] = useState<LocationSuggestion | null>(null);
  const [locationOpen, setLocationOpen] = useState(false);
  const locationBoxRef = useRef<HTMLDivElement | null>(null);
  const [generationLogs, setGenerationLogs] = useState<GenerationLogItem[]>([]);
  const [generationLogsExpanded, setGenerationLogsExpanded] = useState(false);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [form, setForm] = useState({
    query: '',
    location_text: '',
    time_context: '',
    companion_type: '',
    preference_tags: [] as string[],
  });
  const [subscriptionOpen, setSubscriptionOpen] = useState(false);
  const [authRefreshKey, setAuthRefreshKey] = useState(0);
  const [paywallError, setPaywallError] = useState<SubscriptionRequiredError | null>(null);
  const [loginRequired, setLoginRequired] = useState(false);

  useEffect(() => {
    if (!generatorOpen) return;
    if (form.location_text.trim()) return;
    if (!geo.coords) return;
    let cancelled = false;
    setLocationSuggesting(true);
    void suggestLocations({ lat: geo.coords.lat, lng: geo.coords.lng })
      .then((items) => {
        if (cancelled) return;
        setLocationSuggestions(items);
        if (items[0]) {
          setSelectedLocation(items[0]);
          setForm((current) => ({
            ...current,
            location_text: current.location_text || items[0].name,
          }));
        }
      })
      .catch(() => {
        if (!cancelled) setLocationSuggestions([]);
      })
      .finally(() => {
        if (!cancelled) setLocationSuggesting(false);
      });
    return () => {
      cancelled = true;
    };
  }, [generatorOpen, geo.coords?.lat, geo.coords?.lng]);

  useEffect(() => {
    if (!generatorOpen) return;
    // Skip querying when text matches an already-selected suggestion.
    if (selectedLocation && selectedLocation.name === form.location_text) return;
    const query = form.location_text.trim();
    if (query.length < 2) {
      setLocationSuggestions([]);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setLocationSuggesting(true);
      void suggestLocations({ query })
        .then((items) => {
          if (cancelled) return;
          setLocationSuggestions(items);
          setLocationOpen(true);
        })
        .catch(() => {
          if (!cancelled) setLocationSuggestions([]);
        })
        .finally(() => {
          if (!cancelled) setLocationSuggesting(false);
        });
    }, 350);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [generatorOpen, form.location_text, selectedLocation]);

  useEffect(() => {
    void fetchHotTags()
      .then(setHotTags)
      .catch(() => setHotTags([]));
    void loadHome();
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(''), 2400);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible' && feedMode === 'home') {
        geo.refresh();
      }
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [feedMode, geo.refresh]);

  useEffect(() => {
    if (feedMode !== 'home') return;
    const timer = window.setInterval(() => geo.refresh(), HOME_GEO_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [feedMode, geo.refresh]);

  useEffect(() => {
    if (!geo.coords || feedMode !== 'home') return;
    if (homeSort !== 'recommend' && homeSort !== 'distance') return;
    if (!movedSignificantly(lastFeedGeoRef.current, geo.coords)) return;
    lastFeedGeoRef.current = geo.coords;
    if (sortNotice) setSortNotice('');
    void reloadHomeFeed(homeSort);
  }, [geo.coords?.lat, geo.coords?.lng, feedMode, homeSort]);

  function homeFetchOptions(sort: FeedSort = homeSort, tag: string = activeTag) {
    return {
      sort,
      lat: geo.coords?.lat,
      lng: geo.coords?.lng,
      tag: tag.trim() || undefined,
    };
  }

  async function reloadHomeFeed(sort: FeedSort = homeSort, tag: string = activeTag) {
    if (feedMode !== 'home') return;
    setLoading(true);
    setError('');
    setPage(1);
    try {
      const result = await fetchPosts(1, PAGE_SIZE, homeFetchOptions(sort, tag));
      setPosts(result.items);
      setHasMore(result.has_more);
      if (geo.coords) {
        lastFeedGeoRef.current = geo.coords;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const target = loadMoreRef.current;
    if (!target || !hasMore) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          void loadMore();
        }
      },
      { rootMargin: '240px' },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [hasMore, loading, loadingMore, page, feedMode, activeSearch, posts.length]);

  async function loadHome() {
    setLoading(true);
    setError('');
    setActiveTag('');
    setFeedMode('home');
    setActiveSearch('');
    setSortNotice('');
    setHomeSort('recommend');
    setPage(1);
    trackHomepageView();
    try {
      const result = await fetchPosts(1, PAGE_SIZE, homeFetchOptions('recommend'));
      setPosts(result.items);
      setHasMore(result.has_more);
      if (geo.coords) {
        lastFeedGeoRef.current = geo.coords;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }

  async function onHomeSortChange(sort: FeedSort) {
    if (sort === 'distance' && !geo.coords) {
      setSortNotice('开启定位后，才能按离你远近排序');
      geo.request();
    } else {
      setSortNotice('');
    }
    setHomeSort(sort);
    setFeedMode('home');
    setPage(1);
    setLoading(true);
    setError('');
    if (sort === 'recommend' || sort === 'distance') {
      geo.refresh();
    }
    try {
      const result = await fetchPosts(1, PAGE_SIZE, homeFetchOptions(sort, activeTag));
      setPosts(result.items);
      setHasMore(result.has_more);
      if (geo.coords) {
        lastFeedGeoRef.current = geo.coords;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }

  async function loadMore() {
    if (loading || loadingMore || !hasMore) return;
    setLoadingMore(true);
    setError('');
    try {
      const nextPage = page + 1;
      const result =
        feedMode === 'search'
          ? await searchPosts(activeSearch, nextPage, PAGE_SIZE)
          : await fetchPosts(nextPage, PAGE_SIZE, homeFetchOptions());
      setPosts((current) => {
        const seen = new Set(current.map((post) => post.id));
        const merged = [...current];
        for (const post of result.items) {
          if (!seen.has(post.id)) merged.push(post);
        }
        return merged;
      });
      setPage(nextPage);
      setHasMore(result.has_more);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载更多失败');
    } finally {
      setLoadingMore(false);
    }
  }

  async function runSearch(query: string) {
    if (!query.trim()) {
      await loadHome();
      return;
    }
    setLoading(true);
    setError('');
    setFeedMode('search');
    setActiveSearch(query.trim());
    setPage(1);
    try {
      const result = await searchPosts(query.trim(), 1, PAGE_SIZE);
      setPosts(result.items);
      setHasMore(result.has_more);
      trackSearch({ result_count: result.items.length });
    } catch (err) {
      setError(err instanceof Error ? err.message : '搜索失败');
    } finally {
      setLoading(false);
    }
  }

  async function submitSearch(event: FormEvent) {
    event.preventDefault();
    setActiveTag('');
    await runSearch(searchQuery);
  }

  async function onTagClick(tag: string) {
    if (activeTag === tag) {
      setActiveTag('');
      setSearchQuery('');
      await loadHome();
      return;
    }
    setActiveTag(tag);
    setSearchQuery(tag);
    setFeedMode('home');
    setActiveSearch('');
    setSortNotice('');
    setPage(1);
    setLoading(true);
    setError('');
    try {
      const result = await fetchPosts(1, PAGE_SIZE, homeFetchOptions(homeSort, tag));
      setPosts(result.items);
      setHasMore(result.has_more);
      if (geo.coords) {
        lastFeedGeoRef.current = geo.coords;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }

  async function submitGenerate(event: FormEvent) {
    event.preventDefault();
    if (!form.query.trim()) {
      setError('先说说你想怎么玩');
      return;
    }
    setGenerating(true);
    setGenerationLogsExpanded(false);
    setGenerationLogs([]);
    setError('');
    trackAIGenerate({
      location: selectedLocation?.name || form.location_text.trim() || undefined,
      has_time_context: !!form.time_context.trim(),
      has_companion: !!form.companion_type.trim(),
      preference_count: form.preference_tags.length,
    });
    try {
      const started = await startGeneration({
        query: form.query.trim(),
        location_text: selectedLocation?.name || form.location_text.trim() || undefined,
        location_lat: selectedLocation?.lat ?? geo.coords?.lat,
        location_lng: selectedLocation?.lng ?? geo.coords?.lng,
        time_context: form.time_context.trim() || undefined,
        companion_type: form.companion_type.trim() || undefined,
        preference_tags: form.preference_tags,
      });
      let afterLogId = 0;
      let created: Post | null = null;
      while (true) {
        const status = await fetchGenerationStatus(started.generation_request_id, afterLogId || undefined);
        if (status.logs.length) {
          afterLogId = Math.max(afterLogId, ...status.logs.map((item) => item.id));
          setGenerationLogs((current) => [...current, ...status.logs]);
        }
        if (status.status === 'success' && status.post_id) {
          created = await fetchPost(status.post_id);
          break;
        }
        if (status.status === 'failed') {
          throw new Error(status.error_message || '生成失败');
        }
        await sleep(GENERATION_POLL_MS);
      }
      if (!created) {
        throw new Error('生成完成但未返回帖子');
      }
      setPosts((current) => [created, ...current]);
      openDetail(created);
      setForm({ query: '', location_text: '', time_context: '', companion_type: '', preference_tags: [] });
      setSelectedLocation(null);
      setLocationSuggestions([]);
      setGeneratorOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : '生成失败');
    } finally {
      setGenerating(false);
    }
  }

  async function updateLike(post: Post) {
    const result = await toggleLike(post.id);
    patchPost(post.id, { is_liked: result.is_liked, like_count: result.like_count });
  }

  async function updateFavorite(post: Post) {
    const result = await toggleFavorite(post.id);
    patchPost(post.id, { is_favorited: result.is_favorited, favorite_count: result.favorite_count });
  }

  function openExportModal(post: Post) {
    setExportPost(post);
    setExportModalOpen(true);
  }

  function closeExportModal() {
    setExportModalOpen(false);
    setExportPost(null);
  }

  async function sharePost(post: Post) {
    const url = postShareUrl(post.id);
    window.open(url, '_blank', 'noopener,noreferrer');
    try {
      await navigator.clipboard.writeText(url);
      setToast('链接已复制，已在新页面打开');
    } catch {
      setToast('已在新页面打开分享页');
    }
  }

  function patchPost(postId: number, patch: Partial<Post>) {
    setPosts((current) => current.map((post) => (post.id === postId ? { ...post, ...patch } : post)));
    setSelectedPost((current) => (current?.id === postId ? { ...current, ...patch } : current));
  }

  function togglePreference(tag: string) {
    setForm((current) => ({
      ...current,
      preference_tags: current.preference_tags.includes(tag)
        ? current.preference_tags.filter((item) => item !== tag)
        : [...current.preference_tags, tag],
    }));
  }

  function chooseLocation(item: LocationSuggestion) {
    setSelectedLocation(item);
    setForm((current) => ({ ...current, location_text: item.name }));
    setLocationOpen(false);
  }

  useEffect(() => {
    if (!locationOpen) return;
    function onClick(event: MouseEvent) {
      if (locationBoxRef.current && !locationBoxRef.current.contains(event.target as Node)) {
        setLocationOpen(false);
      }
    }
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [locationOpen]);

  function openDetail(post: Post) {
    trackCardClick({ post_id: post.id });
    setSelectedPost(post);
    setActiveImage(0);
    closeExportModal();
  }

  function closeDetail() {
    setSelectedPost(null);
    closeExportModal();
  }

  useEffect(() => {
    if (!selectedPost) return;
    const total = selectedPost.images.length;
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setSelectedPost(null);
      } else if (event.key === 'ArrowLeft' && total > 0) {
        setActiveImage((index) => ((index - 1 + total) % total));
      } else if (event.key === 'ArrowRight' && total > 0) {
        setActiveImage((index) => ((index + 1) % total));
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selectedPost, activeImage]);

  const shownGenerationLogs = visibleGenerationLogs(generationLogs);

  return (
    <div className="app">
      {toast && <div className="toast">{toast}</div>}

      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <img src="/brand-logo.png" alt="上海 City Walk" className="brand-logo" />
            <div className="brand-text">
              <strong>上海City不City</strong>
              <small>发现 · 收藏 · 生成你的城市玩法</small>
            </div>
          </div>
          <form className="search" onSubmit={submitSearch}>
            <svg viewBox="0 0 24 24" className="search-icon" aria-hidden="true">
              <path
                d="M21 21l-4.3-4.3m1.3-5.2a6.5 6.5 0 11-13 0 6.5 6.5 0 0113 0z"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
            <input
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="搜索静安寺、亲子、夜景、拍照…"
            />
            {searchQuery && (
              <button
                type="button"
                className="search-clear"
                onClick={async () => {
                  setSearchQuery('');
                  setActiveTag('');
                  await loadHome();
                }}
              >
                清除
              </button>
            )}
            <button type="submit" className="search-go">搜索</button>
          </form>
          <button
            className="generate-trigger"
            onClick={() => setGeneratorOpen((open) => {
              if (!open) trackAIPlanOpen();
              return !open;
            })}
          >
            ✨ AI规划玩法
          </button>
          <AuthMenu
            onOpenSubscription={() => setSubscriptionOpen(true)}
            refreshSignal={authRefreshKey}
          />
        </div>

        {hotTags.length > 0 && (
          <div className="tag-rail">
            <button
              className={activeTag === '' ? 'tag-pill active' : 'tag-pill'}
              onClick={() => onTagClick(activeTag)}
            >
              全部
            </button>
            {hotTags.map((tag) => (
              <button
                key={tag}
                className={activeTag === tag ? 'tag-pill active' : 'tag-pill'}
                onClick={() => onTagClick(tag)}
              >
                {tag}
              </button>
            ))}
          </div>
        )}

        {feedMode === 'home' && (
          <div className="sort-rail">
            {FEED_SORT_OPTIONS.map((option) => (
              <button
                key={option.id}
                type="button"
                className={homeSort === option.id ? 'sort-pill active' : 'sort-pill'}
                onClick={() => void onHomeSortChange(option.id)}
              >
                {option.label}
              </button>
            ))}
          </div>
        )}
      </header>

      {generatorOpen && (
        <section className="generator">
          <div className="generator-head">
            <div>
              <h2>帮我生成一条玩法</h2>
              <p>说说你的场景，我会生成一篇小红书风格的玩法卡片，并加入到下面的内容流。</p>
            </div>
            <button className="ghost" onClick={() => setGeneratorOpen(false)}>收起</button>
          </div>
          <form onSubmit={submitGenerate}>
            <textarea
              value={form.query}
              onChange={(event) => setForm({ ...form, query: event.target.value })}
              placeholder="例如：周六晚上想在静安寺附近和朋友拍照吃饭"
            />
            <div className="form-grid">
              <div className="location-field" ref={locationBoxRef}>
                <input
                  value={form.location_text}
                  onChange={(event) => {
                    setSelectedLocation(null);
                    setLocationOpen(true);
                    setForm({ ...form, location_text: event.target.value });
                  }}
                  onFocus={() => {
                    if (locationSuggestions.length > 0) setLocationOpen(true);
                  }}
                  placeholder="出发位置（默认当前定位）"
                />
                {(locationOpen && (locationSuggesting || locationSuggestions.length > 0)) && (
                  <div className="location-dropdown">
                    {locationSuggesting && locationSuggestions.length === 0 && (
                      <div className="location-row location-row-hint">正在查找地点…</div>
                    )}
                    {locationSuggestions.map((item) => (
                      <button
                        key={`${item.name}-${item.lat}-${item.lng}`}
                        type="button"
                        className={`location-row${
                          selectedLocation?.lat === item.lat && selectedLocation?.lng === item.lng ? ' active' : ''
                        }`}
                        onClick={() => chooseLocation(item)}
                      >
                        <span className="location-row-icon">📍</span>
                        <span className="location-row-text">
                          <strong>{item.name}</strong>
                          {item.address && item.address !== item.name && <small>{item.address}</small>}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <input
                value={form.time_context}
                onChange={(event) => setForm({ ...form, time_context: event.target.value })}
                placeholder="时间场景（可选）"
              />
              <input
                value={form.companion_type}
                onChange={(event) => setForm({ ...form, companion_type: event.target.value })}
                placeholder="同行人群（可选）"
              />
            </div>
            <div className="chips">
              {preferenceOptions.map((tag) => (
                <button
                  key={tag}
                  className={form.preference_tags.includes(tag) ? 'chip active' : 'chip'}
                  type="button"
                  onClick={() => togglePreference(tag)}
                >
                  {tag}
                </button>
              ))}
            </div>
            <button className="primary" type="submit" disabled={generating}>
              {generating ? '正在生成…' : '生成小红书卡片'}
            </button>
            {(generating || shownGenerationLogs.length > 0) && (
              <div className="generation-progress">
                <div className="generation-progress-header">
                  <strong>{generating ? '正在生成玩法' : '最近一次生成记录'}</strong>
                  {shownGenerationLogs.length > 1 && (
                    <button
                      type="button"
                      className="generation-progress-toggle"
                      onClick={() => setGenerationLogsExpanded((open) => !open)}
                    >
                      {generationLogsExpanded ? '收起' : `展开全部 (${shownGenerationLogs.length})`}
                    </button>
                  )}
                </div>
                {generating && !generationLogsExpanded && (
                  <p className="generation-progress-current">
                    <span className="generation-spinner" aria-hidden="true" />
                    <span>
                      {shownGenerationLogs.length > 0
                        ? formatGenerationLog(shownGenerationLogs[shownGenerationLogs.length - 1])
                        : '正在为你规划路线…'}
                    </span>
                  </p>
                )}
                {(generationLogsExpanded || !generating || shownGenerationLogs.length <= 1) && shownGenerationLogs.length > 0 && (
                  <ol className="generation-progress-list">
                    {shownGenerationLogs.map((log) => (
                      <li key={log.id} className={log.level === 'error' ? 'log-error' : undefined}>
                        <time dateTime={log.created_at}>{formatLogTime(log.created_at)}</time>
                        <span>{formatGenerationLog(log)}</span>
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            )}
          </form>
        </section>
      )}

      <main className="feed">
        {error && <p className="banner error">{error}</p>}
        {feedMode === 'home' && sortNotice && (
          <p className="banner sort-notice">
            {sortNotice}
            {!geo.coords && (
              <button type="button" className="sort-notice-action" onClick={() => geo.request()}>
                开启定位
              </button>
            )}
          </p>
        )}
        {feedMode === 'home' && !geo.coords && !sortNotice && geo.status !== 'granted' && geo.status !== 'locating' && (
          <p className="banner sort-notice">
            {geo.status === 'denied' && '定位授权被拒绝，请在浏览器站点设置中重新允许定位后刷新页面'}
            {geo.status === 'insecure' && (geo.error || '当前页面非 HTTPS，无法请求定位')}
            {geo.status === 'unsupported' && (geo.error || '当前环境不支持定位')}
            {(geo.status === 'idle' || !geo.status) && '开启定位，查看离你更近的玩法'}
            {geo.status !== 'denied' && geo.status !== 'insecure' && geo.status !== 'unsupported' && (
              <button type="button" className="sort-notice-action" onClick={() => geo.request()}>
                开启定位
              </button>
            )}
          </p>
        )}

        {loading ? (
          <div className="masonry">
            {Array.from({ length: 6 }).map((_, index) => (
              <div className="card skeleton" key={index}>
                <div className="skeleton-img" />
                <div className="skeleton-line" />
                <div className="skeleton-line short" />
              </div>
            ))}
          </div>
        ) : posts.length === 0 ? (
          <div className="empty">
            <p>还没有匹配的玩法。</p>
            <button
              className="primary"
              onClick={() => {
                trackAIPlanOpen();
                setGeneratorOpen(true);
              }}
            >
              让系统帮你生成一条
            </button>
          </div>
        ) : (
          <div className="masonry">
            {posts.map((post) => (
              <article className="card" key={post.id}>
                <button className="card-cover" onClick={() => openDetail(post)}>
                  {post.cover_image ? (
                    <img src={post.cover_image} alt={post.title} loading="lazy" />
                  ) : (
                    <div className="cover-fallback">
                      <span>{post.title.slice(0, 2)}</span>
                    </div>
                  )}
                </button>
                <div className="card-body">
                  <div className="card-title-row">
                    <h3 onClick={() => openDetail(post)}>{post.title}</h3>
                    {liveDistanceForPost(post, geo.coords) != null && (
                      <span className="distance-badge">
                        距你 {formatDistance(liveDistanceForPost(post, geo.coords)!)}
                      </span>
                    )}
                  </div>
                  <p className="excerpt">{plainTextExcerpt(post.content)}</p>
                  <div className="card-foot">
                    <AuthorBadge post={post} />
                    <div className="reactions">
                      <button
                        type="button"
                        className={post.is_liked ? 'react liked' : 'react'}
                        onClick={() => updateLike(post)}
                      >
                        <span className="react-icon" aria-hidden="true">♥</span>
                        <span className="react-count">{formatCount(post.like_count)}</span>
                      </button>
                      <button
                        type="button"
                        className={post.is_favorited ? 'react saved' : 'react'}
                        onClick={() => updateFavorite(post)}
                      >
                        <span className="react-icon" aria-hidden="true">☆</span>
                        <span className="react-count">{formatCount(post.favorite_count)}</span>
                      </button>
                      <button
                        type="button"
                        className="card-icon-btn"
                        onClick={(event) => {
                          event.stopPropagation();
                          openExportModal(post);
                        }}
                        disabled={post.images.length === 0}
                        data-tip={EXPORT_TIP}
                        aria-label={EXPORT_TIP}
                      >
                        ⇩
                      </button>
                    </div>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
        {!loading && hasMore && (
          <div ref={loadMoreRef} className="load-more">
            {loadingMore ? '正在加载更多…' : '继续下滑加载更多'}
          </div>
        )}
        {!loading && !hasMore && posts.length > 0 && (
          <p className="feed-end">已经到底啦</p>
        )}
      </main>

      {selectedPost && (
        <div className="modal" onClick={closeDetail}>
          <PostDetailArticle
            post={selectedPost}
            activeImage={activeImage}
            layout="modal"
            userCoords={geo.coords}
            geoStatus={geo.status}
            onRequestLocation={geo.refresh}
            onImageChange={setActiveImage}
            onLike={() => void updateLike(selectedPost)}
            onFavorite={() => void updateFavorite(selectedPost)}
            onExport={() => openExportModal(selectedPost)}
            onShare={() => void sharePost(selectedPost)}
            onClose={closeDetail}
          />
        </div>
      )}

      {exportPost && exportModalOpen && (
        <ExportModal
          post={exportPost}
          onClose={closeExportModal}
          onPaywall={(err) => {
            setPaywallError(err);
            closeExportModal();
          }}
          onLoginRequired={() => {
            setLoginRequired(true);
            closeExportModal();
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

      {paywallError && (
        <PaywallModal
          error={paywallError}
          onSubscribe={() => {
            setPaywallError(null);
            setSubscriptionOpen(true);
          }}
          onClose={() => setPaywallError(null)}
        />
      )}

      {subscriptionOpen && (
        <SubscriptionPage
          onClose={() => setSubscriptionOpen(false)}
          onSubscribed={() => {
            setSubscriptionOpen(false);
            setAuthRefreshKey((k) => k + 1);
            setToast('订阅成功！可无限次使用润色');
            window.setTimeout(() => setToast(''), 3000);
          }}
        />
      )}
    </div>
  );
}
