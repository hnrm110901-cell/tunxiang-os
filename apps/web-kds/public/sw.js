// Service Worker — 屯象KDS 离线缓存 v2
// Y-K4: 增强离线策略 + 出餐确认 POST 离线队列
//
// 缓存策略：
//   1. 静态资源（.js/.css/.png）→ Cache First
//   2. KDS/订单/部门 API GET    → Network First（缓存兜底）
//   3. 出餐确认 POST            → Network First，断网入离线队列
//   4. OPTIONS                  → 直接放行
//   5. 其他 GET                 → Network First

const CACHE_VERSION = 'tx-kds-v2';
const STATIC_CACHE = 'tx-kds-static-v2';
const KDS_API_CACHE = 'tx-kds-api-v2';
const OFFLINE_QUEUE_DB = 'tx-kds-offline-queue';
const OFFLINE_QUEUE_STORE = 'queue';

// 关键页面预缓存
const PRECACHE_URLS = ['/', '/index.html'];

// KDS 出餐确认操作路径前缀（需要离线队列）
const KDS_WRITE_PATHS = [
  '/api/v1/kds/',
  '/api/v1/orders/',
];

// KDS 可缓存的 GET API 前缀
const CACHEABLE_API_PREFIXES = [
  '/api/v1/kds/',
  '/api/v1/orders/',
  '/api/v1/production-depts/',
  '/api/v1/menu/',
];

// ── IndexedDB 离线队列 ─────────────────────────────────────────────────────

function openQueueDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(OFFLINE_QUEUE_DB, 1);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(OFFLINE_QUEUE_STORE)) {
        const store = db.createObjectStore(OFFLINE_QUEUE_STORE, {
          keyPath: 'id',
          autoIncrement: true,
        });
        store.createIndex('timestamp', 'timestamp');
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function enqueueRequest(request) {
  let body = null;
  try {
    body = await request.clone().text();
  } catch {
    body = null;
  }
  const entry = {
    url: request.url,
    method: request.method,
    headers: Object.fromEntries(request.headers.entries()),
    body,
    timestamp: Date.now(),
    retries: 0,
  };
  const db = await openQueueDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(OFFLINE_QUEUE_STORE, 'readwrite');
    const req = tx.objectStore(OFFLINE_QUEUE_STORE).add(entry);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function drainQueue() {
  const db = await openQueueDB();
  const entries = await new Promise((resolve, reject) => {
    const tx = db.transaction(OFFLINE_QUEUE_STORE, 'readonly');
    const req = tx.objectStore(OFFLINE_QUEUE_STORE).getAll();
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });

  let synced = 0;
  for (const entry of entries) {
    try {
      const init = { method: entry.method, headers: entry.headers };
      if (entry.body) init.body = entry.body;
      await fetch(entry.url, init);
      await new Promise((resolve) => {
        const tx = db.transaction(OFFLINE_QUEUE_STORE, 'readwrite');
        tx.objectStore(OFFLINE_QUEUE_STORE).delete(entry.id);
        tx.oncomplete = resolve;
      });
      synced++;
    } catch {
      // 仍离线，保留
    }
  }

  if (synced > 0) {
    const clients = await self.clients.matchAll();
    for (const client of clients) {
      client.postMessage({ type: 'OFFLINE_QUEUE_DRAINED', count: synced });
    }
  }
}

// ── 安装 ──────────────────────────────────────────────────────────────────

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) =>
      Promise.allSettled(
        PRECACHE_URLS.map((url) => cache.add(url).catch(() => {}))
      )
    )
  );
  self.skipWaiting();
});

// ── 激活 ──────────────────────────────────────────────────────────────────

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== STATIC_CACHE && k !== KDS_API_CACHE)
          .map((k) => caches.delete(k))
      )
    ).then(() => {
      self.clients.claim();
      return drainQueue();
    })
  );
});

// ── 消息处理 ──────────────────────────────────────────────────────────────

self.addEventListener('message', (event) => {
  if (event.data?.type === 'ONLINE_RESTORED') drainQueue();
  if (event.data?.type === 'SKIP_WAITING') self.skipWaiting();
});

// ── 请求拦截 ──────────────────────────────────────────────────────────────

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (request.method === 'OPTIONS') return;
  if (url.protocol === 'ws:' || url.protocol === 'wss:') return;
  if (url.origin !== self.location.origin) return;

  const path = url.pathname;

  // 出餐确认等 POST 操作 → Network First + 离线队列
  if (
    (request.method === 'POST' || request.method === 'PUT' || request.method === 'PATCH') &&
    KDS_WRITE_PATHS.some((p) => path.startsWith(p))
  ) {
    event.respondWith(networkFirstWithQueue(request));
    return;
  }

  // KDS 数据 GET → Network First + 缓存兜底
  if (
    request.method === 'GET' &&
    CACHEABLE_API_PREFIXES.some((p) => path.startsWith(p))
  ) {
    event.respondWith(networkFirstWithFallback(request));
    return;
  }

  // 静态资源 → Cache First
  if (
    request.method === 'GET' &&
    (path.match(/\.(js|css|png|jpg|jpeg|svg|ico|woff2?)$/) || path.startsWith('/assets/'))
  ) {
    event.respondWith(cacheFirst(request));
    return;
  }

  // 其他 GET → Network First
  if (request.method === 'GET') {
    event.respondWith(networkFirstWithFallback(request));
  }
});

// ── 策略实现 ──────────────────────────────────────────────────────────────

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) {
    (await caches.open(STATIC_CACHE)).put(request, response.clone());
  }
  return response;
}

async function networkFirstWithFallback(request) {
  const cache = await caches.open(KDS_API_CACHE);
  try {
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch {
    const cached = await cache.match(request);
    if (cached) return cached;
    if (request.headers.get('accept')?.includes('text/html')) {
      const offline = await caches.match('/offline.html');
      if (offline) return offline;
    }
    return new Response(
      JSON.stringify({
        ok: false,
        error: { code: 'OFFLINE', message: 'KDS 离线，显示最后缓存数据' },
      }),
      { headers: { 'Content-Type': 'application/json' } }
    );
  }
}

async function networkFirstWithQueue(request) {
  try {
    return await fetch(request.clone());
  } catch {
    try {
      await enqueueRequest(request);
    } catch {
      // 入队失败不抛出
    }
    return new Response(
      JSON.stringify({
        ok: true,
        queued: true,
        message: 'KDS 离线，出餐确认已入队，恢复网络后自动同步',
      }),
      {
        status: 202,
        headers: { 'Content-Type': 'application/json' },
      }
    );
  }
}
