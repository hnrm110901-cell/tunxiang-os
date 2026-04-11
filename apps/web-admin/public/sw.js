// 缓存关键资源，支持离线访问首页
const CACHE_NAME = 'tunxiang-admin-v1';
const URLS_TO_CACHE = ['/', '/m/dashboard', '/static/js/main.js'];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      // 逐个尝试缓存，失败不阻断安装
      return Promise.allSettled(
        URLS_TO_CACHE.map(url => cache.add(url).catch(() => {}))
      );
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames =>
      Promise.all(
        cacheNames
          .filter(name => name !== CACHE_NAME)
          .map(name => caches.delete(name))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  // 只处理 GET 请求
  if (event.request.method !== 'GET') return;

  // API 请求不缓存，直接走网络
  if (event.request.url.includes('/api/')) {
    event.respondWith(fetch(event.request));
    return;
  }

  event.respondWith(
    caches.match(event.request).then(response => {
      if (response) return response;
      return fetch(event.request).then(networkResponse => {
        // 缓存 HTML 和静态资源
        if (
          networkResponse.ok &&
          (event.request.url.includes('/m/') || event.request.url.includes('/static/'))
        ) {
          const responseClone = networkResponse.clone();
          caches.open(CACHE_NAME).then(cache => {
            cache.put(event.request, responseClone);
          });
        }
        return networkResponse;
      }).catch(() => {
        // 离线降级：返回缓存的首页
        if (event.request.headers.get('accept').includes('text/html')) {
          return caches.match('/m/dashboard');
        }
      });
    })
  );
});
