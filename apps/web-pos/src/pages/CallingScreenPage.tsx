/**
 * CallingScreenPage — 快餐叫号操作界面（收银台用）
 *
 * 布局：
 *   左侧：待叫号列表（取餐号 + 时间 + 类型，按创建时间排列）
 *   右侧：最近叫过的号（已完成/叫号中，灰色展示）
 *
 * 操作：
 *   点击「叫号」→ POST /quick-cashier/{id}/call → 号码移到右侧「叫号中」
 *   点击「取餐完成」→ POST /quick-cashier/{id}/complete → 号码灰化
 *   紧急重叫：对 calling 状态的号码再次点击叫号（重复广播）
 *
 * Store-POS 终端规范：
 *   - 所有点击区域 ≥ 48×48px，关键操作按钮 ≥ 56px
 *   - 最小字体 ≥ 16px
 *   - 触控反馈：按下 scale(0.97) + 200ms transition
 *   - 深色主题（与其他 POS 页面一致）
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

// ─── Design Tokens ───
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1A3A48',
  accent: '#FF6B35',
  accentActive: '#E55A28',
  success: '#0F6E56',
  warning: '#BA7517',
  danger: '#A32D2D',
  info: '#185FA5',
  muted: '#64748b',
  text: '#E0E0E0',
  white: '#FFFFFF',
  dimText: '#6B7280',
};

// ─── Types ───

interface QuickOrder {
  id: string;
  call_number: string;
  order_type: 'dine_in' | 'takeaway' | 'pack';
  status: 'pending' | 'calling' | 'completed' | 'cancelled';
  called_at: string | null;
  created_at: string;
}

type LoadingMap = Record<string, 'call' | 'complete' | null>;

const ORDER_TYPE_LABEL: Record<string, string> = {
  dine_in: '堂食',
  takeaway: '外带',
  pack: '打包',
};

const ORDER_TYPE_COLOR: Record<string, string> = {
  dine_in: C.success,
  takeaway: C.info,
  pack: C.warning,
};

// ─── API ───

function getBase(): string {
  return (window as Record<string, unknown>).__API_BASE__ as string || '';
}

function getTenantId(): string {
  return (
    (window as Record<string, unknown>).__TENANT_ID__ as string
    || localStorage.getItem('tenant_id')
    || ''
  );
}

function getStoreId(): string {
  return (
    (window as Record<string, unknown>).__STORE_ID__ as string
    || localStorage.getItem('store_id')
    || import.meta.env.VITE_STORE_ID
    || ''
  );
}

async function apiFetch<T = unknown>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${getBase()}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': getTenantId(),
      ...(init?.headers ?? {}),
    },
  });
  const json: unknown = await resp.json();
  if (!resp.ok) {
    const msg =
      (json as Record<string, unknown>)?.error as Record<string, string> | undefined;
    throw new Error(msg?.message ?? `HTTP ${resp.status}`);
  }
  return (json as { data: T }).data;
}

async function fetchCallingList(storeId: string): Promise<QuickOrder[]> {
  const data = await apiFetch<{ items: QuickOrder[] }>(
    `/api/v1/quick-cashier/calling?store_id=${encodeURIComponent(storeId)}&status=all`,
  );
  return data.items ?? [];
}

async function fetchRecentList(storeId: string): Promise<QuickOrder[]> {
  const data = await apiFetch<{ items: QuickOrder[] }>(
    `/api/v1/calling-screen/${encodeURIComponent(storeId)}/recent?n=20`,
  );
  return data.items ?? [];
}

async function apiCall(quickOrderId: string): Promise<{ call_number: string }> {
  return apiFetch<{ call_number: string }>(
    `/api/v1/quick-cashier/${encodeURIComponent(quickOrderId)}/call`,
    { method: 'POST' },
  );
}

async function apiComplete(quickOrderId: string): Promise<{ call_number: string }> {
  return apiFetch<{ call_number: string }>(
    `/api/v1/quick-cashier/${encodeURIComponent(quickOrderId)}/complete`,
    { method: 'POST' },
  );
}

// ─── 工具函数 ───

function formatTime(iso: string | null): string {
  if (!iso) return '--';
  const d = new Date(iso);
  const h = String(d.getHours()).padStart(2, '0');
  const m = String(d.getMinutes()).padStart(2, '0');
  const s = String(d.getSeconds()).padStart(2, '0');
  return `${h}:${m}:${s}`;
}

function elapsedMinutes(iso: string | null): number {
  if (!iso) return 0;
  return Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
}

// ─── 子组件：待叫号卡片 ───

function PendingCard({
  order,
  loading,
  onCall,
}: {
  order: QuickOrder;
  loading: LoadingMap;
  onCall: (id: string) => void;
}) {
  const elapsed = elapsedMinutes(order.created_at);
  const isCalling = order.status === 'calling';
  const isActing = !!loading[order.id];

  const timeColor =
    elapsed >= 10 ? C.danger : elapsed >= 5 ? C.warning : C.success;

  return (
    <div
      style={{
        background: isCalling ? '#0d2a1a' : C.card,
        border: `1px solid ${isCalling ? C.success : C.border}`,
        borderLeft: `5px solid ${isCalling ? C.success : C.accent}`,
        borderRadius: 12,
        padding: '14px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        transition: 'border-color 200ms ease',
      }}
    >
      {/* 取餐号 */}
      <div
        style={{
          flexShrink: 0,
          minWidth: 90,
          textAlign: 'center',
        }}
      >
        <div
          style={{
            fontSize: 34,
            fontWeight: 900,
            color: isCalling ? C.success : C.accent,
            fontFamily: 'JetBrains Mono, monospace',
            letterSpacing: 2,
            lineHeight: 1.1,
          }}
        >
          {order.call_number}
        </div>
        <div
          style={{
            fontSize: 16,
            marginTop: 4,
            padding: '2px 8px',
            borderRadius: 6,
            background: `${ORDER_TYPE_COLOR[order.order_type]}22`,
            color: ORDER_TYPE_COLOR[order.order_type],
            fontWeight: 600,
          }}
        >
          {ORDER_TYPE_LABEL[order.order_type] ?? order.order_type}
        </div>
      </div>

      {/* 时间信息 */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 18, color: C.text }}>
          <span style={{ color: C.dimText }}>下单 </span>
          {formatTime(order.created_at)}
        </div>
        {isCalling && order.called_at && (
          <div style={{ fontSize: 16, color: C.success, marginTop: 4 }}>
            叫号中 · {formatTime(order.called_at)}
          </div>
        )}
        <div
          style={{
            fontSize: 16,
            color: timeColor,
            marginTop: 4,
            fontWeight: elapsed >= 5 ? 700 : 400,
          }}
        >
          等待 {elapsed} 分钟{elapsed >= 10 ? ' ⚠' : ''}
        </div>
      </div>

      {/* 操作按钮组 */}
      <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {/* 叫号 / 重叫 按钮 */}
        <TxButton
          label={isCalling ? '重叫' : '叫号'}
          color={isCalling ? C.warning : C.accent}
          loading={loading[order.id] === 'call'}
          disabled={isActing}
          onPress={() => onCall(order.id)}
          minWidth={88}
        />
      </div>
    </div>
  );
}

// ─── 子组件：叫号中卡片（右侧） ───

function CallingCard({
  order,
  loading,
  onComplete,
  onRecall,
}: {
  order: QuickOrder;
  loading: LoadingMap;
  onComplete: (id: string) => void;
  onRecall: (id: string) => void;
}) {
  const isCompleted = order.status === 'completed';
  const isActing = !!loading[order.id];

  return (
    <div
      style={{
        background: isCompleted ? '#0a0a0a' : '#0a1c10',
        border: `1px solid ${isCompleted ? '#222' : C.success}`,
        borderRadius: 10,
        padding: '12px 14px',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        opacity: isCompleted ? 0.55 : 1,
      }}
    >
      {/* 号码 */}
      <div
        style={{
          fontSize: 28,
          fontWeight: 800,
          color: isCompleted ? C.dimText : C.success,
          fontFamily: 'JetBrains Mono, monospace',
          minWidth: 72,
        }}
      >
        {order.call_number}
      </div>

      {/* 时间 */}
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 16, color: C.dimText }}>
          {isCompleted ? '已完成' : '叫号中'}
          {order.called_at ? ` · ${formatTime(order.called_at)}` : ''}
        </div>
        <div style={{ fontSize: 16, color: C.dimText, marginTop: 2 }}>
          {ORDER_TYPE_LABEL[order.order_type] ?? order.order_type}
        </div>
      </div>

      {/* 操作 */}
      {!isCompleted && (
        <div style={{ flexShrink: 0, display: 'flex', gap: 8 }}>
          <TxButton
            label="取餐完成"
            color={C.success}
            loading={loading[order.id] === 'complete'}
            disabled={isActing}
            onPress={() => onComplete(order.id)}
            minWidth={92}
          />
          <TxButton
            label="重叫"
            color={C.warning}
            loading={loading[order.id] === 'call'}
            disabled={isActing}
            onPress={() => onRecall(order.id)}
            minWidth={64}
          />
        </div>
      )}
    </div>
  );
}

// ─── 子组件：通用触控按钮 ───

function TxButton({
  label,
  color,
  loading,
  disabled,
  onPress,
  minWidth = 80,
}: {
  label: string;
  color: string;
  loading: boolean;
  disabled: boolean;
  onPress: () => void;
  minWidth?: number;
}) {
  return (
    <button
      onClick={onPress}
      disabled={disabled || loading}
      style={{
        minHeight: 56,
        minWidth,
        padding: '0 16px',
        background: disabled || loading ? C.muted : color,
        border: 'none',
        borderRadius: 10,
        color: C.white,
        fontSize: 17,
        fontWeight: 700,
        cursor: disabled || loading ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        transition: 'transform 200ms ease, background 150ms ease',
      }}
      onPointerDown={e => {
        if (!disabled && !loading) {
          (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)';
        }
      }}
      onPointerUp={e => {
        (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
      }}
      onPointerLeave={e => {
        (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
      }}
    >
      {loading ? '处理中...' : label}
    </button>
  );
}

// ─── 主组件 ───

export function CallingScreenPage() {
  const navigate = useNavigate();
  const storeId = getStoreId();

  const [pendingList, setPendingList] = useState<QuickOrder[]>([]);
  const [recentList, setRecentList] = useState<QuickOrder[]>([]);
  const [loadingMap, setLoadingMap] = useState<LoadingMap>({});
  const [errorMsg, setErrorMsg] = useState<string>('');
  const [tick, setTick] = useState(0);

  const loadingRef = useRef(false);

  // ── 每秒刷新等待时间 ──
  useEffect(() => {
    const timer = setInterval(() => setTick(t => t + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  void tick; // 触发重渲染以更新等待时间

  // ── 拉取数据 ──
  const refresh = useCallback(async () => {
    if (!storeId || loadingRef.current) return;
    loadingRef.current = true;
    try {
      const [pending, recent] = await Promise.all([
        fetchCallingList(storeId),
        fetchRecentList(storeId),
      ]);
      setPendingList(pending);
      setRecentList(recent);
      setErrorMsg('');
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : '获取叫号列表失败');
    } finally {
      loadingRef.current = false;
    }
  }, [storeId]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 8000); // 8 秒轮询
    return () => clearInterval(timer);
  }, [refresh]);

  // ── 叫号操作 ──
  const handleCall = useCallback(async (id: string) => {
    setLoadingMap(prev => ({ ...prev, [id]: 'call' }));
    try {
      await apiCall(id);
      await refresh();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : '叫号失败');
    } finally {
      setLoadingMap(prev => ({ ...prev, [id]: null }));
    }
  }, [refresh]);

  // ── 取餐完成操作 ──
  const handleComplete = useCallback(async (id: string) => {
    setLoadingMap(prev => ({ ...prev, [id]: 'complete' }));
    try {
      await apiComplete(id);
      await refresh();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : '完成操作失败');
    } finally {
      setLoadingMap(prev => ({ ...prev, [id]: null }));
    }
  }, [refresh]);

  // 分拆：待叫号（pending）和叫号中（calling）
  const waitingOrders = pendingList.filter(o => o.status === 'pending');
  const callingOrders = pendingList.filter(o => o.status === 'calling');

  // 右侧：叫号中 + 最近完成（合并去重）
  const rightItems: QuickOrder[] = [
    ...callingOrders,
    ...recentList.filter(r => r.status !== 'calling'), // 已完成的
  ].filter((item, idx, arr) => arr.findIndex(x => x.id === item.id) === idx);

  return (
    <div
      style={{
        display: 'flex',
        height: '100vh',
        background: C.bg,
        color: C.text,
        fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
        flexDirection: 'column',
      }}
    >
      {/* ── 顶栏 ── */}
      <header
        style={{
          padding: '12px 20px',
          borderBottom: `1px solid ${C.border}`,
          display: 'flex',
          alignItems: 'center',
          gap: 16,
          flexShrink: 0,
          background: C.card,
          minHeight: 64,
        }}
      >
        <button
          onClick={() => navigate('/quick-cashier')}
          style={{
            minHeight: 48,
            minWidth: 48,
            padding: '8px 16px',
            background: 'transparent',
            border: `1px solid ${C.border}`,
            borderRadius: 8,
            color: C.text,
            fontSize: 16,
            cursor: 'pointer',
          }}
          onPointerDown={e => {
            (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)';
          }}
          onPointerUp={e => {
            (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
          }}
          onPointerLeave={e => {
            (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
          }}
        >
          {'<'} 收银
        </button>

        <h1 style={{ margin: 0, fontSize: 24, fontWeight: 800, color: C.white }}>
          叫号管理
        </h1>

        {/* 统计角标 */}
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          {waitingOrders.length > 0 && (
            <span
              style={{
                background: C.accent,
                color: C.white,
                fontSize: 18,
                fontWeight: 700,
                padding: '4px 12px',
                borderRadius: 16,
              }}
            >
              待叫 {waitingOrders.length}
            </span>
          )}
          {callingOrders.length > 0 && (
            <span
              style={{
                background: C.success,
                color: C.white,
                fontSize: 18,
                fontWeight: 700,
                padding: '4px 12px',
                borderRadius: 16,
              }}
            >
              叫号中 {callingOrders.length}
            </span>
          )}
        </div>

        {/* 刷新按钮 */}
        <button
          onClick={refresh}
          style={{
            marginLeft: 'auto',
            minHeight: 48,
            padding: '0 20px',
            background: 'transparent',
            border: `1px solid ${C.border}`,
            borderRadius: 8,
            color: C.muted,
            fontSize: 16,
            cursor: 'pointer',
          }}
          onPointerDown={e => {
            (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)';
          }}
          onPointerUp={e => {
            (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
          }}
          onPointerLeave={e => {
            (e.currentTarget as HTMLElement).style.transform = 'scale(1)';
          }}
        >
          刷新
        </button>
      </header>

      {/* ── 错误提示 ── */}
      {errorMsg && (
        <div
          style={{
            padding: '10px 20px',
            background: `${C.danger}22`,
            borderBottom: `1px solid ${C.danger}`,
            color: C.danger,
            fontSize: 16,
            flexShrink: 0,
          }}
        >
          {errorMsg}
        </div>
      )}

      {/* ── 主内容区（左右分屏） ── */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          overflow: 'hidden',
          gap: 0,
        }}
      >
        {/* ═══ 左侧：待叫号列表 ═══ */}
        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            borderRight: `1px solid ${C.border}`,
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              padding: '12px 20px',
              borderBottom: `1px solid ${C.border}`,
              flexShrink: 0,
              fontSize: 20,
              fontWeight: 700,
              color: C.accent,
            }}
          >
            待叫号
            {waitingOrders.length > 0 && (
              <span
                style={{
                  marginLeft: 8,
                  fontSize: 17,
                  color: C.dimText,
                  fontWeight: 400,
                }}
              >
                （按下单时间排序）
              </span>
            )}
          </div>

          <div
            style={{
              flex: 1,
              overflowY: 'auto',
              WebkitOverflowScrolling: 'touch',
              padding: 16,
              display: 'flex',
              flexDirection: 'column',
              gap: 10,
            }}
          >
            {waitingOrders.length === 0 ? (
              <div
                style={{
                  textAlign: 'center',
                  color: C.dimText,
                  fontSize: 20,
                  marginTop: 60,
                  lineHeight: 2,
                }}
              >
                <div style={{ fontSize: 40, marginBottom: 12 }}>🎉</div>
                <div>暂无待叫号订单</div>
                <div style={{ fontSize: 16, marginTop: 8 }}>
                  收银后新订单将自动出现在此处
                </div>
              </div>
            ) : (
              waitingOrders.map(order => (
                <PendingCard
                  key={order.id}
                  order={order}
                  loading={loadingMap}
                  onCall={handleCall}
                />
              ))
            )}
          </div>
        </div>

        {/* ═══ 右侧：叫号中 + 已完成 ═══ */}
        <div
          style={{
            width: 380,
            flexShrink: 0,
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              padding: '12px 20px',
              borderBottom: `1px solid ${C.border}`,
              flexShrink: 0,
              fontSize: 20,
              fontWeight: 700,
              color: C.success,
            }}
          >
            叫号中 / 最近完成
          </div>

          <div
            style={{
              flex: 1,
              overflowY: 'auto',
              WebkitOverflowScrolling: 'touch',
              padding: 16,
              display: 'flex',
              flexDirection: 'column',
              gap: 8,
            }}
          >
            {rightItems.length === 0 ? (
              <div
                style={{
                  textAlign: 'center',
                  color: C.dimText,
                  fontSize: 18,
                  marginTop: 60,
                }}
              >
                暂无叫号记录
              </div>
            ) : (
              rightItems.map(order => (
                <CallingCard
                  key={order.id}
                  order={order}
                  loading={loadingMap}
                  onComplete={handleComplete}
                  onRecall={handleCall}
                />
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
