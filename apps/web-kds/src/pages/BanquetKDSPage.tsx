/**
 * BanquetKDSPage — 宴会KDS出品看板
 *
 * 路由：/banquet-kds
 * 功能：
 *   - 场次卡片列表（场次名/包厢/人数/出品进度条）
 *   - 点击场次 → 展开菜品出品列表
 *   - 每道菜：待出（灰）/ 出品中（橙）/ 已出（绿）状态色
 *   - 「叫菜」按钮 + 「标记出品」按钮
 *   - 每 10 秒自动刷新进度
 */
import { useState, useEffect, useCallback } from 'react';
import { getStoreToken } from '../api/index';

const TENANT_ID = import.meta.env.VITE_TENANT_ID || '';

// ─── 类型定义 ────────────────────────────────────────────────────────────────

interface BanquetSession {
  id: string;
  contact_name: string | null;
  guest_count: number;
  table_count: number;
  room_ids?: string[];
  session_date: string;
  time_slot: string;
  status: string;
  total_dishes: number;
  served_dishes: number;
  serving_dishes: number;
}

interface BanquetDish {
  id: string;
  dish_name: string;
  total_qty: number;
  served_qty: number;
  serve_status: 'pending' | 'serving' | 'served';
  sequence_no: number;
  called_at: string | null;
  served_at: string | null;
  notes: string | null;
}

// ─── API 函数 ────────────────────────────────────────────────────────────────

const BASE = '/api/v1/banquet/kds';

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getStoreToken() || '';
  const resp = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
      ...(TENANT_ID ? { 'X-Tenant-ID': TENANT_ID } : {}),
      ...(options?.headers ?? {}),
    },
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ error: { message: resp.statusText } }));
    throw new Error(err?.error?.message ?? resp.statusText);
  }
  const json = await resp.json();
  return json.data as T;
}

async function fetchSessions(storeId?: string): Promise<{ items: BanquetSession[]; total: number }> {
  const params = new URLSearchParams({ size: '50' });
  if (storeId) params.set('store_id', storeId);
  return apiFetch(`${BASE}/sessions?${params}`);
}

async function fetchDishes(sessionId: string): Promise<{ dishes: BanquetDish[] }> {
  return apiFetch(`${BASE}/${sessionId}/dishes`);
}

async function serveDish(sessionId: string, dishId: string): Promise<unknown> {
  return apiFetch(`${BASE}/${sessionId}/dishes/${dishId}/serve`, {
    method: 'POST',
    body: JSON.stringify({ served_qty: 1 }),
  });
}

async function callKitchen(sessionId: string, dishId?: string): Promise<unknown> {
  return apiFetch(`${BASE}/${sessionId}/call`, {
    method: 'POST',
    body: JSON.stringify({ dish_id: dishId ?? null }),
  });
}

// ─── 状态色配置 ───────────────────────────────────────────────────────────────

const STATUS_CONFIG = {
  pending:  { label: '待出', bg: '#2D3748', border: '#4A5568', text: '#A0AEC0', dot: '#718096' },
  serving:  { label: '出品中', bg: '#2D1B00', border: '#C05621', text: '#FBD38D', dot: '#ED8936' },
  served:   { label: '已出', bg: '#0F3D25', border: '#276749', text: '#9AE6B4', dot: '#48BB78' },
} as const;

// ─── 进度条组件 ───────────────────────────────────────────────────────────────

function ProgressBar({ served, total }: { served: number; total: number }) {
  const pct = total > 0 ? Math.round((served / total) * 100) : 0;
  const color = pct === 100 ? '#48BB78' : pct > 50 ? '#ED8936' : '#4299E1';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{
        flex: 1, height: 6, background: '#2D3748', borderRadius: 3, overflow: 'hidden',
      }}>
        <div style={{
          width: `${pct}%`, height: '100%', background: color,
          transition: 'width 0.4s ease', borderRadius: 3,
        }} />
      </div>
      <span style={{ fontSize: 12, color: '#A0AEC0', minWidth: 48, textAlign: 'right' }}>
        {served}/{total} ({pct}%)
      </span>
    </div>
  );
}

// ─── 菜品行组件 ───────────────────────────────────────────────────────────────

function DishRow({
  dish,
  sessionId,
  onUpdate,
}: {
  dish: BanquetDish;
  sessionId: string;
  onUpdate: () => void;
}) {
  const [loading, setLoading] = useState(false);
  const cfg = STATUS_CONFIG[dish.serve_status];

  const handleServe = async () => {
    setLoading(true);
    try {
      await serveDish(sessionId, dish.id);
      onUpdate();
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleCall = async () => {
    setLoading(true);
    try {
      await callKitchen(sessionId, dish.id);
      onUpdate();
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12,
      padding: '10px 14px',
      background: cfg.bg,
      border: `1px solid ${cfg.border}`,
      borderRadius: 8,
      marginBottom: 6,
    }}>
      {/* 序号 */}
      <span style={{ color: '#718096', fontSize: 12, minWidth: 20, textAlign: 'center' }}>
        {dish.sequence_no}
      </span>

      {/* 状态圆点 */}
      <span style={{
        width: 8, height: 8, borderRadius: '50%', background: cfg.dot,
        flexShrink: 0,
      }} />

      {/* 菜名 */}
      <span style={{ flex: 1, color: cfg.text, fontSize: 15, fontWeight: 500 }}>
        {dish.dish_name}
      </span>

      {/* 出品进度 */}
      <span style={{ color: '#A0AEC0', fontSize: 13, minWidth: 60, textAlign: 'right' }}>
        {dish.served_qty}/{dish.total_qty}
      </span>

      {/* 状态标签 */}
      <span style={{
        padding: '2px 8px', borderRadius: 12,
        background: cfg.border, color: cfg.text, fontSize: 12,
        minWidth: 52, textAlign: 'center',
      }}>
        {cfg.label}
      </span>

      {/* 操作按钮 */}
      <div style={{ display: 'flex', gap: 6 }}>
        {dish.serve_status !== 'served' && (
          <>
            {dish.serve_status === 'pending' && (
              <button
                onClick={handleCall}
                disabled={loading}
                style={{
                  padding: '4px 10px', borderRadius: 6, border: 'none',
                  background: '#2B4C7E', color: '#90CDF4', fontSize: 12,
                  cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.6 : 1,
                }}
              >
                叫菜
              </button>
            )}
            <button
              onClick={handleServe}
              disabled={loading}
              style={{
                padding: '4px 10px', borderRadius: 6, border: 'none',
                background: '#276749', color: '#9AE6B4', fontSize: 12,
                cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.6 : 1,
              }}
            >
              出品
            </button>
          </>
        )}
        {dish.serve_status === 'served' && (
          <span style={{ color: '#48BB78', fontSize: 12 }}>✓ 完成</span>
        )}
      </div>
    </div>
  );
}

// ─── 场次卡片组件 ─────────────────────────────────────────────────────────────

function SessionCard({
  session,
  expanded,
  onToggle,
}: {
  session: BanquetSession;
  expanded: boolean;
  onToggle: () => void;
}) {
  const [dishes, setDishes] = useState<BanquetDish[]>([]);
  const [loadingDishes, setLoadingDishes] = useState(false);
  const [callingAll, setCallingAll] = useState(false);

  const loadDishes = useCallback(async () => {
    setLoadingDishes(true);
    try {
      const data = await fetchDishes(session.id);
      setDishes(data.dishes);
    } catch (e) {
      console.error('加载菜品失败', e);
    } finally {
      setLoadingDishes(false);
    }
  }, [session.id]);

  useEffect(() => {
    if (expanded) {
      loadDishes();
    }
  }, [expanded, loadDishes]);

  const handleCallAll = async () => {
    setCallingAll(true);
    try {
      await callKitchen(session.id);
      await loadDishes();
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setCallingAll(false);
    }
  };

  const statusColor = session.status === 'serving' ? '#ED8936' : '#4299E1';
  const totalDishes = session.total_dishes || dishes.length;
  const servedDishes = session.served_dishes;

  return (
    <div style={{
      background: '#111827',
      border: '1px solid rgba(255,255,255,0.08)',
      borderRadius: 12,
      marginBottom: 12,
      overflow: 'hidden',
    }}>
      {/* 场次头部 */}
      <div
        onClick={onToggle}
        style={{
          display: 'flex', alignItems: 'center', gap: 12,
          padding: '14px 18px',
          cursor: 'pointer',
          background: expanded ? 'rgba(255,255,255,0.03)' : 'transparent',
          transition: 'background 0.2s',
        }}
      >
        {/* 展开箭头 */}
        <span style={{
          color: '#718096', fontSize: 14,
          transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)',
          transition: 'transform 0.2s',
          display: 'inline-block',
        }}>▶</span>

        {/* 场次信息 */}
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <span style={{ color: '#F0F0F0', fontSize: 16, fontWeight: 600 }}>
              {session.contact_name ?? '未命名场次'}
            </span>
            <span style={{
              padding: '1px 8px', borderRadius: 10,
              background: statusColor + '22', color: statusColor, fontSize: 12,
            }}>
              {session.status === 'serving' ? '出品中' : '备餐中'}
            </span>
          </div>
          <div style={{ color: '#718096', fontSize: 13 }}>
            {session.session_date} {session.time_slot === 'dinner' ? '晚宴' : session.time_slot === 'lunch' ? '午宴' : session.time_slot}
            &nbsp;·&nbsp;{session.guest_count} 人 · {session.table_count} 桌
          </div>
        </div>

        {/* 进度条 */}
        <div style={{ minWidth: 180 }}>
          <ProgressBar served={servedDishes} total={totalDishes} />
        </div>

        {/* 叫全部 */}
        {expanded && (
          <button
            onClick={(e) => { e.stopPropagation(); handleCallAll(); }}
            disabled={callingAll}
            style={{
              padding: '6px 14px', borderRadius: 8, border: 'none',
              background: '#2B4C7E', color: '#90CDF4', fontSize: 13,
              cursor: callingAll ? 'not-allowed' : 'pointer',
              opacity: callingAll ? 0.6 : 1, fontWeight: 500,
            }}
          >
            {callingAll ? '叫菜中…' : '叫全部'}
          </button>
        )}
      </div>

      {/* 菜品列表 */}
      {expanded && (
        <div style={{ padding: '4px 18px 14px' }}>
          {loadingDishes ? (
            <div style={{ color: '#718096', padding: '16px 0', textAlign: 'center' }}>
              加载中…
            </div>
          ) : dishes.length === 0 ? (
            <div style={{ color: '#4A5568', padding: '16px 0', textAlign: 'center', fontSize: 14 }}>
              暂无菜品记录（排菜方案为空）
            </div>
          ) : (
            dishes.map(dish => (
              <DishRow
                key={dish.id}
                dish={dish}
                sessionId={session.id}
                onUpdate={loadDishes}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export function BanquetKDSPage() {
  const [sessions, setSessions] = useState<BanquetSession[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  const loadSessions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchSessions();
      setSessions(data.items);
      setTotal(data.total);
      setLastRefresh(new Date());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  // 初始加载
  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  // 每 10 秒自动刷新
  useEffect(() => {
    const timer = setInterval(loadSessions, 10_000);
    return () => clearInterval(timer);
  }, [loadSessions]);

  const toggleExpand = (id: string) => {
    setExpandedId(prev => (prev === id ? null : id));
  };

  return (
    <div style={{
      minHeight: '100vh',
      background: '#0D1117',
      color: '#F0F0F0',
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif',
    }}>
      {/* 顶栏 */}
      <div style={{
        position: 'sticky', top: 0, zIndex: 50,
        background: '#111827',
        borderBottom: '1px solid rgba(255,255,255,0.08)',
        padding: '0 24px',
        height: 56,
        display: 'flex', alignItems: 'center', gap: 16,
      }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: '#FF6B35' }}>🍽 宴会出品</span>
        <span style={{ color: '#718096', fontSize: 14 }}>
          共 {total} 场在进行
        </span>
        <div style={{ flex: 1 }} />
        <span style={{ color: '#4A5568', fontSize: 12 }}>
          刷新于 {lastRefresh.toLocaleTimeString()}
        </span>
        <button
          onClick={loadSessions}
          disabled={loading}
          style={{
            padding: '6px 16px', borderRadius: 8, border: 'none',
            background: loading ? '#2D3748' : '#1A365D',
            color: loading ? '#718096' : '#90CDF4',
            fontSize: 13, cursor: loading ? 'not-allowed' : 'pointer',
          }}
        >
          {loading ? '刷新中…' : '刷新'}
        </button>
      </div>

      {/* 内容区 */}
      <div style={{ padding: '20px 24px', maxWidth: 960, margin: '0 auto' }}>
        {error && (
          <div style={{
            background: '#2D1B1B', border: '1px solid #742A2A',
            borderRadius: 10, padding: '12px 16px', marginBottom: 16,
            color: '#FC8181', fontSize: 14,
          }}>
            加载失败：{error}
            <button
              onClick={loadSessions}
              style={{
                marginLeft: 12, padding: '2px 10px', borderRadius: 6,
                border: '1px solid #742A2A', background: 'transparent',
                color: '#FC8181', cursor: 'pointer', fontSize: 13,
              }}
            >
              重试
            </button>
          </div>
        )}

        {!loading && !error && sessions.length === 0 && (
          <div style={{
            textAlign: 'center', padding: '80px 0',
            color: '#4A5568', fontSize: 16,
          }}>
            <div style={{ fontSize: 48, marginBottom: 16 }}>🍽</div>
            <div>暂无进行中的宴会场次</div>
            <div style={{ fontSize: 13, marginTop: 8 }}>仅显示状态为「备餐中」或「出品中」的场次</div>
          </div>
        )}

        {sessions.map(session => (
          <SessionCard
            key={session.id}
            session={session}
            expanded={expandedId === session.id}
            onToggle={() => toggleExpand(session.id)}
          />
        ))}
      </div>
    </div>
  );
}

export default BanquetKDSPage;
