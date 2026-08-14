declare global {
  interface Window {
    umami?: {
      track: (name: string, props?: Record<string, unknown>) => void;
    };
  }
}

const pendingEvents: Array<[string, Record<string, unknown> | undefined]> = [];
let umamiReady = typeof window !== 'undefined' && !!window.umami;

function loadUmamiIfConfigured(): void {
  const src = String(import.meta.env.VITE_UMAMI_SCRIPT_SRC || '').trim();
  const websiteId = String(import.meta.env.VITE_UMAMI_WEBSITE_ID || '').trim();
  if (!src || !websiteId || document.querySelector(`script[src="${src}"]`)) return;
  const script = document.createElement('script');
  script.defer = true;
  script.src = src;
  script.dataset.websiteId = websiteId;
  const domains = String(import.meta.env.VITE_UMAMI_DOMAINS || '').trim();
  if (domains) script.dataset.domains = domains;
  document.head.appendChild(script);
}

function flushPending(): void {
  if (!window.umami) return;
  while (pendingEvents.length > 0) {
    const [name, props] = pendingEvents.shift()!;
    try {
      window.umami.track(name, props);
    } catch {
      // Analytics should never break the app
    }
  }
  umamiReady = true;
}

if (typeof window !== 'undefined') {
  loadUmamiIfConfigured();
  // Poll for Umami script load (deferred script may load after first event)
  if (!umamiReady) {
    const interval = setInterval(() => {
      if (window.umami) {
        clearInterval(interval);
        flushPending();
      }
    }, 200);
    // Stop polling after 10s - don't leak forever
    setTimeout(() => clearInterval(interval), 10000);
  }
}

function track(name: string, props?: Record<string, unknown>): void {
  try {
    if (window.umami) {
      window.umami.track(name, props);
      return;
    }
    // Buffer event until Umami script loads
    pendingEvents.push([name, props]);
  } catch {
    // Analytics should never break the app
  }
}

export function trackHomepageView(): void {
  track('homepage_view');
}

export function trackAIGenerate(props: { location?: string; has_time_context: boolean; has_companion: boolean; preference_count: number }): void {
  track('ai_generate', props);
}

export function trackAIPlanOpen(): void {
  track('ai_plan_open');
}

export function trackImagePolish(props: { post_id: number }): void {
  track('image_polish', props);
}

export function trackZipDownload(props: { post_id: number; image_count: number }): void {
  track('zip_download', props);
}

export function trackCardClick(props: { post_id: number }): void {
  track('card_click', props);
}

export function trackSearch(props: { result_count: number }): void {
  track('search', props);
}

export function trackLogin(): void {
  track('user_login');
}

export function trackLogout(): void {
  track('user_logout');
}
