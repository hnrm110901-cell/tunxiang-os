// Service Worker — 屯象KDS 离线缓存
// 策略：静态资产 Cache First；KDS 订单数据 Network First + 缓存兜底
const CACHE_NAME = 'tunxiang-kds-v3';
const STATIC_URLS = ['/', '/index.html'];
const KDS_API_CACHE = 'tunxiang-kds-api-v3';

const CACHEABLE_API_PREFIXES = [
  '/api/v1/kds/',
  '/api/v1/orders/',
  '/api/v1/production-depts/',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_URLS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== CACHE_NAME && k !== KDS_API_CACHE)
          .map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  if (event.request.method !== 'GET') return;
  if (url.protocol === 'ws:' || url.protocol === 'wss:') return;

  const isKDSAPI = CACHEABLE_API_PREFIXES.some((prefix) => url.pathname.startsWith(prefix));

  if (isKDSAPI) {
    // Network First：KDS 出餐数据优先从网络取最新
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const clone = response.clone();
          caches.open(KDS_API_CACHE).then((cache) => cache.put(event.request, clone));
          return response;
        })
        .catch(() =>
          caches.match(event.request).then(
            (cached) =>
              cached ||
              new Response(
                JSON.stringify({ ok: false, error: { code: 'OFFLINE', message: 'KDS 离线，显示最后缓存数据' } }),
                { headers: { 'Content-Type': 'application/json' } }
              )
          )
        )
    );
  } else {
    // Cache First：静态资产
    event.respondWith(
      caches.match(event.request).then(
        (cached) =>
          cached ||
          fetch(event.request).then((response) => {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
            return response;
          })
      )
    );
  }
});
