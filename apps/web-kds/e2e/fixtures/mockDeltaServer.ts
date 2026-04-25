/**
 * mockDeltaServer.ts — 后厨 KDS delta 后端的本地 HTTP mock
 *
 * 用于 Sprint C / C4 的 4 小时零卡顿 E2E。它替代真实 tx-trade，
 * 让 KDS 前端能持续轮询 /api/v1/kds/orders/delta 而不依赖任何后端服务。
 *
 * 设计要点：
 *   - 端口随机：listen(0) 让操作系统分配，避免本地/CI 冲突
 *   - 每次 GET 返回 5-15 个订单的 churn（新订单 + 状态切换）
 *   - 使用 cursor（自增 ms epoch）保证客户端 next_cursor 推进
 *   - getRequestCount() 暴露给 spec 做断言（活跃度证据）
 *   - 启动 outage 时只需调用 setOutage(true) 让所有请求 503
 *
 * 这里**不**使用 express，零依赖：node:http 足够。
 */
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import { AddressInfo } from 'node:net';

export type DeltaOrder = {
  tenant_id: string;
  id: string;
  order_no: string;
  store_id: string;
  status: 'pending' | 'confirmed' | 'preparing' | 'ready';
  table_number: string | null;
  updated_at: string;
  items_count: number;
};

export interface MockDeltaServerOptions {
  /** 每次 GET 返回的订单数下界 */
  minChurn?: number;
  /** 每次 GET 返回的订单数上界 */
  maxChurn?: number;
  /** 后端建议的客户端 poll 间隔，毫秒 */
  pollIntervalMs?: number;
  /** 固定 tenant_id（默认随机 UUID v4 字符串） */
  tenantId?: string;
  /** 固定 store_id */
  storeId?: string;
  /** 用于复现的 RNG 种子 */
  seed?: number;
}

const DEFAULT_OPTIONS: Required<MockDeltaServerOptions> = {
  minChurn: 5,
  maxChurn: 15,
  pollIntervalMs: 3_000,
  tenantId: '00000000-0000-0000-0000-000000000001',
  storeId: '00000000-0000-0000-0000-0000000000a1',
  seed: 0xc0ffee,
};

const STATUSES: DeltaOrder['status'][] = ['pending', 'confirmed', 'preparing', 'ready'];

/**
 * 极简 LCG（Linear Congruential Generator），可重复种子。
 * 用 Math.random 会让 4h 跑两次结果不同，调试 jank 不便。
 */
function makeRng(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0xffffffff;
  };
}

export class MockDeltaServer {
  private server: Server | null = null;
  private requestCount = 0;
  private orderCount = 0;
  private outage = false;
  private readonly opts: Required<MockDeltaServerOptions>;
  private readonly rng: () => number;

  constructor(options: MockDeltaServerOptions = {}) {
    this.opts = { ...DEFAULT_OPTIONS, ...options };
    this.rng = makeRng(this.opts.seed);
  }

  start(): Promise<number> {
    return new Promise((resolve, reject) => {
      this.server = createServer((req, res) => this.handle(req, res));
      this.server.on('error', reject);
      this.server.listen(0, '127.0.0.1', () => {
        const addr = this.server!.address() as AddressInfo;
        resolve(addr.port);
      });
    });
  }

  stop(): Promise<void> {
    return new Promise((resolve) => {
      if (!this.server) {
        resolve();
        return;
      }
      this.server.close(() => resolve());
      this.server = null;
    });
  }

  get port(): number {
    if (!this.server) throw new Error('mockDeltaServer 未启动');
    const addr = this.server.address() as AddressInfo;
    return addr.port;
  }

  getRequestCount(): number {
    return this.requestCount;
  }

  /** 触发"后端断网"——所有请求返回 503 直到 setOutage(false) */
  setOutage(on: boolean): void {
    this.outage = on;
  }

  private handle(req: IncomingMessage, res: ServerResponse): void {
    this.requestCount += 1;

    // CORS：允许 vite dev server (http://localhost:5173)
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'content-type, authorization, x-tenant-id');
    if (req.method === 'OPTIONS') {
      res.statusCode = 204;
      res.end();
      return;
    }

    if (this.outage) {
      res.statusCode = 503;
      res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify({ ok: false, error: { message: 'simulated outage' } }));
      return;
    }

    const url = req.url ?? '/';

    if (url.startsWith('/api/v1/kds/orders/delta')) {
      this.handleDelta(res);
      return;
    }
    if (url.startsWith('/api/v1/kds/device/heartbeat')) {
      this.handleHeartbeat(res);
      return;
    }
    if (url === '/__mock__/health') {
      res.statusCode = 200;
      res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify({ ok: true, requestCount: this.requestCount }));
      return;
    }

    if (url === '/' || url === '/board' || url.startsWith('/board?')) {
      res.statusCode = 200;
      res.setHeader('content-type', 'text/html; charset=utf-8');
      res.end(this.renderTestPage());
      return;
    }

    // 兜底：所有其他 KDS API 都给空数组，避免前端 throw
    res.statusCode = 200;
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify({ ok: true, data: { items: [], total: 0 } }));
  }

  /**
   * 内置测试页：模拟后厨看板的核心运行时——3 秒一次 fetch /api/v1/kds/orders/delta，
   * 渲染最新 churn 的订单列表，并在内部维护订单 Map（淘汰超过 200 条的旧单）。
   *
   * 为什么不用真 vite dev server？
   *   工作目录的 vite 在某些 worktree 状态下因 packages/* 不在 pnpm-workspace
   *   导致 import-analysis 失败（详见 e2e/README.md 的"已知限制"）。
   *   一旦上游修复，把 KDS_BASE_URL 指向 http://localhost:5173 即可复用同一组 spec。
   *
   * 该测试页 ≠ 真实 KDS UI，但它运行在真 Chromium、真 fetch、真 DOM，
   * 充分代表 4 小时连续轮询对浏览器内存/GC/帧率的压力。
   */
  private renderTestPage(): string {
    return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>KDS E2E Test Harness</title>
  <style>
    body { margin: 0; padding: 12px; font-family: -apple-system, sans-serif; background: #0d1117; color: #f0f0f0; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 8px; }
    .card { background: #111827; border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; padding: 8px; font-size: 12px; }
    .card.preparing { border-color: #BA7517; }
    .card.ready { border-color: #0F6E56; }
    .card.pending { border-color: rgba(255,255,255,0.2); }
    .stat { padding: 8px 0; font-size: 14px; color: rgba(255,255,255,0.7); }
  </style>
</head>
<body>
  <div class="stat" id="stat">starting...</div>
  <div class="grid" id="grid"></div>
  <script>
    (function() {
      const stat = document.getElementById('stat');
      const grid = document.getElementById('grid');
      // 内存型 LRU：最多保留 200 条订单（KDS 实际场景 2-3 小时累计 ~150 单）
      const orders = new Map();
      const MAX_ORDERS = 200;
      let ticks = 0;
      let lastError = '';
      let consecutiveErrors = 0;

      async function tick() {
        ticks++;
        try {
          const resp = await fetch('/api/v1/kds/orders/delta?store_id=demo&device_id=mock-kds-001&device_kind=kds&limit=20');
          if (!resp.ok) throw new Error('HTTP ' + resp.status);
          const json = await resp.json();
          consecutiveErrors = 0;
          const list = (json && json.data && json.data.orders) || [];
          for (const o of list) {
            orders.set(o.id, o);
          }
          // LRU 淘汰：保留最近 200 条
          while (orders.size > MAX_ORDERS) {
            const firstKey = orders.keys().next().value;
            if (firstKey === undefined) break;
            orders.delete(firstKey);
          }
          render();
        } catch (e) {
          consecutiveErrors++;
          lastError = String(e.message || e);
          stat.textContent = 'tick=' + ticks + ' size=' + orders.size + ' errors=' + consecutiveErrors + ' last=' + lastError;
        }
      }

      function render() {
        stat.textContent = 'tick=' + ticks + ' size=' + orders.size + ' errors=' + consecutiveErrors;
        // 增量更新 DOM：删除已不存在的卡片，追加新订单
        const seen = new Set();
        for (const [id, o] of orders) {
          let el = document.querySelector('[data-id="' + id + '"]');
          if (!el) {
            el = document.createElement('div');
            el.dataset.id = id;
            el.className = 'card ' + o.status;
            el.innerHTML = '<div>' + o.order_no + '</div><div>桌 ' + (o.table_number || '-') + '</div><div>' + o.status + '</div>';
            grid.appendChild(el);
          } else if (el.className !== 'card ' + o.status) {
            el.className = 'card ' + o.status;
          }
          seen.add(id);
        }
        // 移除 LRU 淘汰掉的卡片
        for (const el of grid.querySelectorAll('.card')) {
          if (!seen.has(el.dataset.id)) el.remove();
        }
      }

      // 3 秒一次轮询节奏
      tick();
      setInterval(tick, 3000);
    })();
  </script>
</body>
</html>`;
  }

  private handleDelta(res: ServerResponse): void {
    const churn = Math.floor(
      this.opts.minChurn + this.rng() * (this.opts.maxChurn - this.opts.minChurn + 1),
    );
    const now = Date.now();
    const orders: DeltaOrder[] = [];
    for (let i = 0; i < churn; i++) {
      this.orderCount += 1;
      orders.push({
        tenant_id: this.opts.tenantId,
        id: `ord-${this.orderCount.toString(16).padStart(8, '0')}`,
        order_no: `K${this.orderCount.toString().padStart(6, '0')}`,
        store_id: this.opts.storeId,
        status: STATUSES[Math.floor(this.rng() * STATUSES.length)],
        table_number: `T${Math.floor(this.rng() * 200) + 1}`,
        updated_at: new Date(now - Math.floor(this.rng() * 30_000)).toISOString(),
        items_count: 1 + Math.floor(this.rng() * 8),
      });
    }
    res.statusCode = 200;
    res.setHeader('content-type', 'application/json');
    res.end(
      JSON.stringify({
        ok: true,
        data: {
          orders,
          next_cursor: String(now),
          server_time: new Date(now).toISOString(),
          poll_interval_ms: this.opts.pollIntervalMs,
          device_id: 'mock-kds-001',
          device_kind: 'kds',
        },
      }),
    );
  }

  private handleHeartbeat(res: ServerResponse): void {
    res.statusCode = 200;
    res.setHeader('content-type', 'application/json');
    res.end(
      JSON.stringify({
        ok: true,
        data: {
          device_id: 'mock-kds-001',
          device_kind: 'kds',
          server_time: new Date().toISOString(),
          poll_interval_ms: this.opts.pollIntervalMs,
        },
      }),
    );
  }
}

/**
 * 便捷工厂：start() 完成后返回实例与 baseURL，方便 spec 一行起服。
 */
export async function startMockDeltaServer(
  options: MockDeltaServerOptions = {},
): Promise<{ server: MockDeltaServer; baseURL: string }> {
  const server = new MockDeltaServer(options);
  const port = await server.start();
  return { server, baseURL: `http://127.0.0.1:${port}` };
}
