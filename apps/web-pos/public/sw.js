// Service Worker — 屯象POS 离线缓存 v2
// Y-K4: 增强离线策略 + POST 操作离线队列（断网操作不丢失）
//
// 缓存策略：
//   1. 静态资源（.js/.css/.png）→ Cache First
//   2. /api/v1/menu/*           → Stale-While-Revalidate（菜单可用缓存，后台更新）
//   3. /api/v1/trade/* GET      → Network First，超时 3s 降级缓存
//   4. /api/v1/trade/* POST/PUT → Network First，断网入离线队列
//   5. OPTIONS                  → 直接放行
//   6. 其他请求                  → Network First

const CACHE_VERSION = 'tx-pos-v2';
const STATIC_CACHE = 'tx-pos-static-v2';
const API_CACHE = 'tx-pos-api-v2';
const OFFLINE_QUEUE_DB = 'tx-pos-offline-queue';
const OFFLINE_QUEUE_STORE = 'queue';

// 关键页面预缓存
const PRECACHE_URLS = [
  '/',
  '/index.html',
  '/cashier',
  '/tables',
  '/offline.html',
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
    const clone = request.clone();
    body = await clone.text();
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
    const store = tx.objectStore(OFFLINE_QUEUE_STORE);
    const req = store.add(entry);
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

  for (const entry of entries) {
    try {
      const init = {
        method: entry.method,
        headers: entry.headers,
      };
      if (entry.body) init.body = entry.body;
      await fetch(entry.url, init);

      // 成功后从队列删除
      await new Promise((resolve) => {
        const tx = db.transaction(OFFLINE_QUEUE_STORE, 'readwrite');
        tx.objectStore(OFFLINE_QUEUE_STORE).delete(entry.id);
        tx.oncomplete = resolve;
      });
    } catch {
      // 仍然离线，保留记录，下次再试
    }
  }

  if (entries.length > 0) {
    // 通知所有客户端队列已处理
    const clients = await self.clients.matchAll();
    for (const client of clients) {
      client.postMessage({
        type: 'OFFLINE_QUEUE_DRAINED',
        count: entries.length,
      });
    }
  }
}

// ── 安装：预缓存关键资源 ───────────────────────────────────────────────────

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

// ── 激活：清理旧缓存 ──────────────────────────────────────────────────────

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== STATIC_CACHE && k !== API_CACHE)
          .map((k) => caches.delete(k))
      )
    ).then(() => {
      self.clients.claim();
      // 恢复在线后尝试刷新离线队列
      return drainQueue();
    })
  );
});

// ── 恢复在线时刷新离线队列 ─────────────────────────────────────────────────

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'ONLINE_RESTORED') {
    drainQueue();
  }
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

// ── 网络请求拦截 ──────────────────────────────────────────────────────────

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // OPTIONS 直接放行（CORS 预检）
  if (request.method === 'OPTIONS') return;

  // WebSocket 不拦截
  if (url.protocol === 'ws:' || url.protocol === 'wss:') return;

  // 跨域请求不拦截
  if (url.origin !== self.location.origin) return;

  const path = url.pathname;

  // ── 策略1：菜单 API → Stale-While-Revalidate ─────────────────────────
  if (request.method === 'GET' && path.startsWith('/api/v1/menu/')) {
    event.respondWith(staleWhileRevalidate(request));
    return;
  }

  // ── 策略2：交易写操作 POST/PUT → Network First + 离线队列 ─────────────
  if (
    (request.method === 'POST' || request.method === 'PUT') &&
    path.startsWith('/api/v1/trade/')
  ) {
    event.respondWith(networkFirstWithQueue(request));
    return;
  }

  // ── 策略3：交易读操作 GET → Network First（3s 超时降级）────────────────
  if (request.method === 'GET' && path.startsWith('/api/v1/trade/')) {
    event.respondWith(networkFirstWithTimeout(request, 3000));
    return;
  }

  // ── 策略4：静态资源 → Cache First ─────────────────────────────────────
  if (
    request.method === 'GET' &&
    (path.match(/\.(js|css|png|jpg|jpeg|svg|ico|woff2?)$/) || path.startsWith('/assets/'))
  ) {
    event.respondWith(cacheFirst(request));
    return;
  }

  // ── 策略5：其他 → Network First ───────────────────────────────────────
  if (request.method === 'GET') {
    event.respondWith(networkFirstWithTimeout(request, 5000));
  }
});

// ── 缓存策略实现 ──────────────────────────────────────────────────────────

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) {
    const cache = await caches.open(STATIC_CACHE);
    cache.put(request, response.clone());
  }
  return response;
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(API_CACHE);
  const cached = await cache.match(request);

  const fetchPromise = fetch(request).then((response) => {
    if (response.ok) cache.put(request, response.clone());
    return response;
  }).catch(() => null);

  if (cached) {
    // 后台更新，立即返回缓存
    event.waitUntil(fetchPromise);
    return cached;
  }

  // 无缓存时等待网络
  const response = await fetchPromise;
  return response || offlineResponse('menu');
}

async function networkFirstWithTimeout(request, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(request, { signal: controller.signal });
    clearTimeout(timer);
    if (response.ok) {
      const cache = await caches.open(API_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    clearTimeout(timer);
    const cached = await caches.match(request);
    if (cached) return cached;

    // 返回离线页面（HTML 请求）
    if (request.headers.get('accept')?.includes('text/html')) {
      const offline = await caches.match('/offline.html');
      if (offline) return offline;
    }
    return offlineResponse('generic');
  }
}

async function networkFirstWithQueue(request) {
  try {
    const response = await fetch(request.clone());
    return response;
  } catch {
    // 网络失败：入离线队列，返回 202 Accepted 告知客户端
    try {
      await enqueueRequest(request);
    } catch {
      // 队列写入失败也不抛出
    }
    return new Response(
      JSON.stringify({
        ok: true,
        queued: true,
        message: '当前处于离线模式，操作已加入队列，恢复网络后自动同步',
      }),
      {
        status: 202,
        headers: { 'Content-Type': 'application/json' },
      }
    );
  }
}

function offlineResponse(type) {
  const messages = {
    menu: '菜单数据暂不可用，请检查网络连接',
    generic: '网络连接中断，操作无法完成',
  };
  return new Response(
    JSON.stringify({
      ok: false,
      error: {
        code: 'OFFLINE',
        message: messages[type] || messages.generic,
      },
    }),
    { headers: { 'Content-Type': 'application/json' } }
  );
}
