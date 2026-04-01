// Service Worker — 屯象POS 离线缓存
// 策略：静态资产 Cache First；API 请求 Network First + 缓存兜底
const CACHE_NAME = 'tunxiang-pos-v3';
const STATIC_URLS = ['/', '/index.html'];
const API_CACHE_NAME = 'tunxiang-pos-api-v3';

// 离线时允许缓存兜底的 API 路径前缀
const CACHEABLE_API_PREFIXES = [
  '/api/v1/menu/',
  '/api/v1/tables/',
  '/api/v1/orders/',
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
          .filter((k) => k !== CACHE_NAME && k !== API_CACHE_NAME)
          .map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // 跳过非 GET 请求（POST/PUT 等写操作不缓存）
  if (event.request.method !== 'GET') return;

  // 跳过 WebSocket
  if (url.protocol === 'ws:' || url.protocol === 'wss:') return;

  const isAPI = CACHEABLE_API_PREFIXES.some((prefix) => url.pathname.startsWith(prefix));

  if (isAPI) {
    // API：Network First，失败降级到缓存
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const clone = response.clone();
          caches.open(API_CACHE_NAME).then((cache) => cache.put(event.request, clone));
          return response;
        })
        .catch(() =>
          caches.match(event.request).then(
            (cached) =>
              cached ||
              new Response(
                JSON.stringify({ ok: false, error: { code: 'OFFLINE', message: '设备离线，暂无缓存数据' } }),
                { headers: { 'Content-Type': 'application/json' } }
              )
          )
        )
    );
  } else {
    // 静态资产：Cache First
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
