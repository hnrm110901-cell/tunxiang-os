/**
 * 外卖聚合接单面板 — Delivery Aggregator
 * 统一管理美团 / 饿了么 / 抖音三平台外卖订单
 */
import { useEffect, useState, useCallback } from 'react';
import { txFetchData } from '../../../api';

// ─── 类型定义 ───

interface DeliveryOrder {
  id: string;
  platform: 'meituan' | 'eleme' | 'douyin';
  platform_order_id: string;
  store_id: string;
  status: 'pending' | 'confirmed' | 'delivering' | 'completed' | 'cancelled' | 'rejected';
  items: { name: string; qty: number; price_fen: number }[];
  total_amount_fen: number;
  commission_fen: number;
  created_at: string;
}

interface DailyStats {
  total_orders: number;
  total_amount_fen: number;
  total_commission_fen: number;
  by_platform: Record<string, { orders: number; amount_fen: number }>;
}

interface Platform {
  id: string;
  name: string;
}

// ─── 常量 ───

const REFRESH_INTERVAL = 30_000; // 30秒

const PLATFORM_META: Record<string, { label: string; emoji: string; color: string }> = {
  meituan: { label: '美团', emoji: '🍊', color: '#FF6B00' },
  eleme:   { label: '饿了么', emoji: '🔵', color: '#0078FF' },
  douyin:  { label: '抖音', emoji: '🎵', color: '#FE2C55' },
};

const STATUS_META: Record<string, { label: string; color: string; bg: string }> = {
  pending:   { label: '待接单', color: '#E8820C', bg: '#E8820C22' },
  confirmed: { label: '已接单', color: '#3B9EFF', bg: '#3B9EFF22' },
  delivering:{ label: '配送中', color: '#3B9EFF', bg: '#3B9EFF22' },
  completed: { label: '已完成', color: '#0F6E56', bg: '#0F6E5622' },
  cancelled: { label: '已取消', color: '#666',    bg: '#66666622' },
  rejected:  { label: '已拒单', color: '#A32D2D', bg: '#A32D2D22' },
};

// ─── 工具函数 ───

function fenToYuan(fen: number): string {
  return (fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function timeAgo(isoStr: string): string {
  const diff = Math.floor((Date.now() - new Date(isoStr).getTime()) / 60000);
  if (diff < 1) return '刚刚';
  if (diff < 60) return `${diff}分钟前`;
  if (diff < 1440) return `${Math.floor(diff / 60)}小时前`;
  return `${Math.floor(diff / 1440)}天前`;
}

function itemsPreview(items: DeliveryOrder['items']): string {
  const shown = items.slice(0, 3).map(i => `${i.name}×${i.qty}`).join(' + ');
  const extra = items.length > 3 ? ` 等${items.length - 3}项` : '';
  return shown + extra;
}

// ─── 统计卡片 ───

function StatCard({
  title, value, sub, accent,
}: { title: string; value: string; sub?: string; accent?: string }) {
  return (
    <div style={{
      background: '#1a2a33', borderRadius: 10, padding: '16px 20px',
      border: '1px solid #2a3a44', flex: 1,
    }}>
      <div style={{ color: '#888', fontSize: 12, marginBottom: 6 }}>{title}</div>
      <div style={{ fontSize: 26, fontWeight: 700, color: accent || '#fff' }}>{value}</div>
      {sub && <div style={{ color: '#888', fontSize: 12, marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

// ─── 订单卡片 ───

function OrderCard({
  order,
  onConfirm,
  onReject,
}: {
  order: DeliveryOrder;
  onConfirm: (id: string) => void;
  onReject: (id: string) => void;
}) {
  const plat = PLATFORM_META[order.platform] || { label: order.platform, emoji: '📦', color: '#888' };
  const stat = STATUS_META[order.status] || { label: order.status, color: '#888', bg: '#88888822' };
  const isPending = order.status === 'pending';

  return (
    <div style={{
      background: '#1a2a33',
      borderRadius: 10,
      border: '1px solid #2a3a44',
      borderLeft: isPending ? '4px solid #E8820C' : '4px solid transparent',
      padding: '14px 16px',
      marginBottom: 10,
    }}>
      {/* 第一行：平台 + 订单号 + 时间 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 16 }}>{plat.emoji}</span>
          <span style={{ fontSize: 13, fontWeight: 700, color: plat.color }}>{plat.label}</span>
          <span style={{ fontSize: 12, color: '#999', fontFamily: 'monospace' }}>
            #{order.platform_order_id}
          </span>
        </div>
        <span style={{ fontSize: 12, color: '#888' }}>⏰ {timeAgo(order.created_at)}</span>
      </div>

      {/* 第二行：菜品列表 */}
      <div style={{ fontSize: 13, color: '#ccc', marginBottom: 10, lineHeight: 1.5 }}>
        {itemsPreview(order.items)}
      </div>

      {/* 第三行：金额 + 状态 + 按钮 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 18, fontWeight: 700, color: '#fff' }}>
            ¥{fenToYuan(order.total_amount_fen)}
          </span>
          <span style={{
            fontSize: 11, padding: '2px 10px', borderRadius: 10,
            background: stat.bg, color: stat.color,
          }}>
            {stat.label}
          </span>
        </div>

        {isPending && (
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={() => onConfirm(order.id)}
              style={{
                minWidth: 80, height: 44, borderRadius: 8,
                background: '#0F6E56', color: '#fff', border: 'none',
                cursor: 'pointer', fontSize: 14, fontWeight: 600,
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4,
              }}
            >
              ✅ 接单
            </button>
            <button
              onClick={() => onReject(order.id)}
              style={{
                minWidth: 80, height: 44, borderRadius: 8,
                background: 'transparent', color: '#A32D2D',
                border: '1px solid #A32D2D44',
                cursor: 'pointer', fontSize: 14, fontWeight: 600,
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4,
              }}
            >
              ❌ 拒单
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── 拒单弹窗 ───

function RejectModal({
  orderId,
  onClose,
  onConfirm,
}: {
  orderId: string;
  onClose: () => void;
  onConfirm: (id: string, reason: string) => void;
}) {
  const [reason, setReason] = useState('');

  return (
    <div style={{
      position: 'fixed', inset: 0, background: '#000000cc',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999,
    }}>
      <div style={{
        background: '#1a2a33', borderRadius: 12, padding: 28, width: 400,
        border: '1px solid #2a3a44',
      }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 16, fontWeight: 700, color: '#fff' }}>
          ❌ 拒单原因
        </h3>
        <p style={{ color: '#888', fontSize: 13, margin: '0 0 12px' }}>
          请填写拒单原因（必填），系统将通知用户。
        </p>
        <textarea
          autoFocus
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="例：门店暂停营业 / 食材不足 / 配送范围外..."
          style={{
            width: '100%', height: 100, borderRadius: 8,
            background: '#0d1e28', border: '1px solid #2a3a44',
            color: '#fff', fontSize: 13, padding: '10px 12px',
            resize: 'vertical', outline: 'none', boxSizing: 'border-box',
          }}
        />
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 16 }}>
          <button
            onClick={onClose}
            style={{
              padding: '8px 20px', borderRadius: 8, border: '1px solid #2a3a44',
              background: 'transparent', color: '#888', cursor: 'pointer', fontSize: 14,
            }}
          >
            取消
          </button>
          <button
            onClick={() => {
              if (reason.trim()) onConfirm(orderId, reason.trim());
            }}
            disabled={!reason.trim()}
            style={{
              padding: '8px 20px', borderRadius: 8, border: 'none',
              background: reason.trim() ? '#A32D2D' : '#A32D2D44',
              color: reason.trim() ? '#fff' : '#666',
              cursor: reason.trim() ? 'pointer' : 'not-allowed',
              fontSize: 14, fontWeight: 600,
            }}
          >
            确认拒单
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── 主页面 ───

export function DeliveryPage() {
  const [orders, setOrders] = useState<DeliveryOrder[]>([]);
  const [stats, setStats] = useState<DailyStats | null>(null);
  const [stores, setStores] = useState<{ id: string; name: string }[]>([]);
  const [selectedStore, setSelectedStore] = useState<string>('');
  const [platformFilter, setPlatformFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [countdown, setCountdown] = useState(REFRESH_INTERVAL / 1000);
  const [rejectTarget, setRejectTarget] = useState<string | null>(null);

  // ─ 数据加载 ─

  const fetchOrders = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (selectedStore) params.set('store_id', selectedStore);
      if (platformFilter !== 'all') params.set('platform', platformFilter);
      if (statusFilter !== 'all') params.set('status', statusFilter);
      const data = await txFetchData<{ items: DeliveryOrder[]; total: number }>(
        `/api/v1/delivery/orders${params.toString() ? '?' + params.toString() : ''}`,
      );
      setOrders(data.items);
    } catch {
      /* 保留旧数据 */
    }
  }, [selectedStore, platformFilter, statusFilter]);

  const fetchStats = useCallback(async () => {
    try {
      const params = selectedStore ? `?store_id=${encodeURIComponent(selectedStore)}` : '';
      const data = await txFetchData<DailyStats>(`/api/v1/delivery/stats/daily${params}`);
      setStats(data);
    } catch {
      /* 保留旧数据 */
    }
  }, [selectedStore]);

  const fetchAll = useCallback(async () => {
    await Promise.all([fetchOrders(), fetchStats()]);
    setLastRefresh(new Date());
    setCountdown(REFRESH_INTERVAL / 1000);
    setLoading(false);
  }, [fetchOrders, fetchStats]);

  // 初始加载门店列表
  useEffect(() => {
    txFetchData<{ items: { id: string; name: string }[] }>('/api/v1/delivery/platforms')
      .then((d) => setStores(d.items || []))
      .catch(() => {/* 忽略 */});
  }, []);

  // 自动刷新
  useEffect(() => {
    fetchAll();
    const timer = setInterval(fetchAll, REFRESH_INTERVAL);
    return () => clearInterval(timer);
  }, [fetchAll]);

  // 倒计时
  useEffect(() => {
    const timer = setInterval(() => setCountdown((c) => Math.max(0, c - 1)), 1000);
    return () => clearInterval(timer);
  }, [lastRefresh]);

  // ─ 操作 ─

  const handleConfirm = useCallback(async (orderId: string) => {
    // 乐观更新
    setOrders((prev) =>
      prev.map((o) => (o.id === orderId ? { ...o, status: 'confirmed' as const } : o)),
    );
    try {
      await txFetchData(`/api/v1/delivery/orders/${orderId}/confirm`, { method: 'POST' });
    } catch {
      /* 回滚或忽略，下次刷新会同步 */
    }
    fetchOrders();
  }, [fetchOrders]);

  const handleReject = useCallback(async (orderId: string, reason: string) => {
    setRejectTarget(null);
    // 乐观更新
    setOrders((prev) =>
      prev.map((o) => (o.id === orderId ? { ...o, status: 'rejected' as const } : o)),
    );
    try {
      await txFetchData(`/api/v1/delivery/orders/${orderId}/reject`, {
        method: 'POST',
        body: JSON.stringify({ reason }),
      });
    } catch {
      /* 回滚或忽略 */
    }
    fetchOrders();
  }, [fetchOrders]);

  // ─ 派生数据 ─

  const pendingCount = orders.filter((o) => o.status === 'pending').length;
  const displayOrders = orders; // 筛选已由后端完成

  // ─ 统计数字 ─

  const totalOrders = stats?.total_orders ?? 0;
  const totalAmount = stats?.total_amount_fen ?? 0;
  const totalCommission = stats?.total_commission_fen ?? 0;
  const byPlatform = stats?.by_platform ?? {};

  const platformSubline = Object.entries(PLATFORM_META)
    .map(([k, v]) => `${v.emoji}${byPlatform[k]?.orders ?? 0}`)
    .join('  ');

  // ─ 渲染 ─

  const PLATFORM_TABS = [
    { key: 'all', label: '全部' },
    { key: 'meituan', label: '🍊 美团' },
    { key: 'eleme',   label: '🔵 饿了么' },
    { key: 'douyin',  label: '🎵 抖音' },
  ];

  const STATUS_TABS = [
    { key: 'all',       label: '全部' },
    { key: 'pending',   label: '待接单' },
    { key: 'delivering',label: '配送中' },
    { key: 'completed', label: '已完成' },
    { key: 'cancelled', label: '已取消' },
  ];

  return (
    <div style={{ padding: 24, minHeight: '100vh', background: '#0d1e28', color: '#fff' }}>

      {/* 页头 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>🛵 外卖聚合接单</h2>
          <p style={{ color: '#888', margin: '4px 0 0', fontSize: 13 }}>
            美团 / 饿了么 / 抖音 三平台统一管理
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {/* 门店选择 */}
          <select
            value={selectedStore}
            onChange={(e) => setSelectedStore(e.target.value)}
            style={{
              padding: '6px 12px', borderRadius: 6, border: '1px solid #2a3a44',
              background: '#1a2a33', color: '#ccc', fontSize: 13, cursor: 'pointer',
              outline: 'none',
            }}
          >
            <option value="">全部门店</option>
            {stores.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
          {/* 刷新按钮 + 倒计时 */}
          <div style={{ textAlign: 'right' }}>
            <button
              onClick={fetchAll}
              style={{
                padding: '6px 14px', borderRadius: 6, border: '1px solid #2a3a44',
                background: 'transparent', color: '#888', cursor: 'pointer',
                fontSize: 13, display: 'block', marginBottom: 2,
              }}
            >
              ↻ 刷新
            </button>
            <div style={{ color: '#888', fontSize: 11 }}>
              {countdown}s 后自动刷新 · {lastRefresh.toLocaleTimeString('zh-CN')}
            </div>
          </div>
        </div>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 60, color: '#888' }}>加载中...</div>
      ) : (
        <>
          {/* 顶部统计行 */}
          <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
            <StatCard
              title="待接单"
              value={String(pendingCount)}
              sub="需立即处理"
              accent={pendingCount > 0 ? '#E8820C' : '#0F6E56'}
            />
            <StatCard
              title="今日订单数"
              value={String(totalOrders)}
              sub={platformSubline}
            />
            <StatCard
              title="今日营业额"
              value={`¥${fenToYuan(totalAmount)}`}
              sub="含三平台"
            />
            <StatCard
              title="总佣金"
              value={`¥${fenToYuan(totalCommission)}`}
              sub={totalAmount > 0 ? `占比 ${((totalCommission / totalAmount) * 100).toFixed(1)}%` : '—'}
              accent="#A32D2D"
            />
          </div>

          {/* 平台筛选 Tabs */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            {PLATFORM_TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setPlatformFilter(tab.key)}
                style={{
                  padding: '6px 16px', borderRadius: 20, fontSize: 13, cursor: 'pointer',
                  border: platformFilter === tab.key ? '1px solid #3B9EFF' : '1px solid #2a3a44',
                  background: platformFilter === tab.key ? '#3B9EFF22' : 'transparent',
                  color: platformFilter === tab.key ? '#3B9EFF' : '#888',
                  transition: 'all .15s',
                }}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* 订单状态筛选 */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
            {STATUS_TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setStatusFilter(tab.key)}
                style={{
                  padding: '5px 14px', borderRadius: 16, fontSize: 12, cursor: 'pointer',
                  border: statusFilter === tab.key ? '1px solid #2a3a44' : '1px solid transparent',
                  background: statusFilter === tab.key ? '#1a2a33' : 'transparent',
                  color: statusFilter === tab.key ? '#fff' : '#666',
                  transition: 'all .15s',
                }}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* 订单列表 */}
          {displayOrders.length === 0 ? (
            <div style={{
              textAlign: 'center', padding: 60, color: '#888',
              background: '#1a2a33', borderRadius: 10, border: '1px solid #2a3a44',
            }}>
              暂无订单
            </div>
          ) : (
            <div>
              {displayOrders.map((order) => (
                <OrderCard
                  key={order.id}
                  order={order}
                  onConfirm={handleConfirm}
                  onReject={(id) => setRejectTarget(id)}
                />
              ))}
            </div>
          )}
        </>
      )}

      {/* 拒单弹窗 */}
      {rejectTarget && (
        <RejectModal
          orderId={rejectTarget}
          onClose={() => setRejectTarget(null)}
          onConfirm={handleReject}
        />
      )}
    </div>
  );
}
