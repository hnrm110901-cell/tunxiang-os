/**
 * ManagerControlScreen — 控菜大屏（厨师长视角）
 *
 * 天财商龙特色功能：厨师长独立大屏，俯视全店所有桌/档口出品进度。
 *
 * 核心功能：
 *   - 实时显示每桌的出品进度（已上/总菜品数）
 *   - 高亮超时桌台（红色边框）
 *   - 一键整桌叫起（标记整桌所有 cooking 菜品进入 calling 状态）
 *   - 向指定档口发送加急/停菜指令
 *   - 汇总各档口实时负载
 *
 * 布局：
 *   左侧：档口负载监控（每个档口的 pending/cooking 数量）
 *   右侧：桌台网格（每桌一个卡片，实时进度条）
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { txFetch } from '../api/index';

// ─── Types ───

interface TableProgress {
  table_no: string;
  order_id: string;
  total_dishes: number;
  done_dishes: number;
  cooking_dishes: number;
  pending_dishes: number;
  calling_dishes: number;
  is_overtime: boolean;
  max_wait_min: number;
  vip: boolean;
}

interface DeptLoad {
  dept_id: string;
  dept_name: string;
  pending_count: number;
  cooking_count: number;
  avg_cook_min: number;
}

interface ManagerData {
  tables: TableProgress[];
  depts: DeptLoad[];
  summary: {
    total_tables: number;
    overtime_tables: number;
    calling_pending: number;
  };
}

// ─── Constants ───

const API_BASE = (window as any).__STORE_API_BASE__ || '';
const TENANT_ID = (window as any).__TENANT_ID__ || '';
const STORE_ID = (window as any).__STORE_ID__ || '';
const REFRESH_MS = 10_000;

// ─── Sub-components ───

function DeptLoadCard({ dept }: { dept: DeptLoad }) {
  const isHeavy = dept.pending_count + dept.cooking_count > 10;
  return (
    <div
      style={{
        background: '#1A1A1A',
        border: `1px solid ${isHeavy ? '#FF6B35' : '#2A2A2A'}`,
        borderRadius: 10,
        padding: '12px 16px',
        marginBottom: 8,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 16, fontWeight: 700, color: '#fff' }}>
          {dept.dept_name}
        </span>
        <span style={{ fontSize: 13, color: '#888' }}>
          均 {dept.avg_cook_min.toFixed(0)}分钟
        </span>
      </div>
      <div style={{ display: 'flex', gap: 12, marginTop: 8 }}>
        <span
          style={{
            fontSize: 28,
            fontWeight: 700,
            color: '#FF9F0A',
            fontFamily: 'monospace',
          }}
        >
          {dept.pending_count}
        </span>
        <span style={{ fontSize: 13, color: '#666', alignSelf: 'flex-end', marginBottom: 4 }}>
          待制作
        </span>
        <span
          style={{
            fontSize: 28,
            fontWeight: 700,
            color: '#FF6B35',
            fontFamily: 'monospace',
          }}
        >
          {dept.cooking_count}
        </span>
        <span style={{ fontSize: 13, color: '#666', alignSelf: 'flex-end', marginBottom: 4 }}>
          制作中
        </span>
      </div>
    </div>
  );
}

function TableCard({
  table,
  onCallUp,
  onRush,
}: {
  table: TableProgress;
  onCallUp: (orderId: string) => void;
  onRush: (orderId: string) => void;
}) {
  const progress =
    table.total_dishes > 0 ? table.done_dishes / table.total_dishes : 0;
  const borderColor = table.is_overtime
    ? '#FF3B30'
    : table.vip
    ? '#FFD60A'
    : '#2A2A2A';

  return (
    <div
      style={{
        background: '#1A1A1A',
        border: `2px solid ${borderColor}`,
        borderRadius: 12,
        padding: 14,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        animation: table.is_overtime ? 'pulse 1.5s infinite' : undefined,
      }}
    >
      {/* 桌号 + VIP */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span
          style={{
            fontSize: 24,
            fontWeight: 700,
            color: table.is_overtime ? '#FF3B30' : '#fff',
          }}
        >
          {table.table_no}
        </span>
        {table.vip && (
          <span
            style={{
              background: '#FFD60A',
              color: '#000',
              fontSize: 11,
              fontWeight: 700,
              borderRadius: 4,
              padding: '1px 6px',
            }}
          >
            VIP
          </span>
        )}
      </div>

      {/* 出品进度：done/total */}
      <div style={{ fontSize: 14, color: '#888' }}>
        <span style={{ color: '#30D158', fontWeight: 700 }}>{table.done_dishes}</span>
        <span style={{ color: '#555' }}> / {table.total_dishes} 道</span>
        {table.calling_dishes > 0 && (
          <span style={{ color: '#FF9F0A', marginLeft: 8 }}>
            {table.calling_dishes}道等叫
          </span>
        )}
      </div>

      {/* 进度条 */}
      <div
        style={{
          height: 6,
          borderRadius: 3,
          background: '#2A2A2A',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${progress * 100}%`,
            height: '100%',
            background:
              table.is_overtime
                ? '#FF3B30'
                : progress >= 1
                ? '#30D158'
                : '#FF6B35',
            transition: 'width 0.3s',
          }}
        />
      </div>

      {/* 等待时间 */}
      {table.max_wait_min > 0 && (
        <div
          style={{
            fontSize: 13,
            color: table.is_overtime ? '#FF3B30' : '#888',
          }}
        >
          最长等待 {table.max_wait_min.toFixed(0)}分钟
        </div>
      )}

      {/* 操作按钮 */}
      <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
        {table.calling_dishes > 0 && (
          <button
            onClick={() => onCallUp(table.order_id)}
            style={{
              flex: 1,
              minHeight: 48,
              background: '#FF6B35',
              color: '#fff',
              border: 'none',
              borderRadius: 8,
              fontSize: 14,
              fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            整桌叫起
          </button>
        )}
        {table.is_overtime && (
          <button
            onClick={() => onRush(table.order_id)}
            style={{
              flex: 1,
              minHeight: 48,
              background: '#FF3B30',
              color: '#fff',
              border: 'none',
              borderRadius: 8,
              fontSize: 14,
              fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            加急！
          </button>
        )}
      </div>
    </div>
  );
}

// ─── Main ───

export function ManagerControlScreen() {
  const [data, setData] = useState<ManagerData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchData = useCallback(async () => {
    if (!STORE_ID) {
      // Mock
      setData({
        tables: [
          { table_no: 'A01', order_id: 'o1', total_dishes: 5, done_dishes: 3, cooking_dishes: 1, pending_dishes: 1, calling_dishes: 1, is_overtime: false, max_wait_min: 12, vip: true },
          { table_no: 'A02', order_id: 'o2', total_dishes: 8, done_dishes: 2, cooking_dishes: 4, pending_dishes: 2, calling_dishes: 0, is_overtime: true, max_wait_min: 38, vip: false },
          { table_no: 'B01', order_id: 'o3', total_dishes: 3, done_dishes: 3, cooking_dishes: 0, pending_dishes: 0, calling_dishes: 0, is_overtime: false, max_wait_min: 5, vip: false },
          { table_no: 'B03', order_id: 'o4', total_dishes: 6, done_dishes: 1, cooking_dishes: 3, pending_dishes: 2, calling_dishes: 2, is_overtime: false, max_wait_min: 18, vip: false },
        ],
        depts: [
          { dept_id: 'd1', dept_name: '热菜档', pending_count: 5, cooking_count: 3, avg_cook_min: 15 },
          { dept_id: 'd2', dept_name: '凉菜档', pending_count: 2, cooking_count: 1, avg_cook_min: 8 },
          { dept_id: 'd3', dept_name: '主食档', pending_count: 1, cooking_count: 2, avg_cook_min: 10 },
        ],
        summary: { total_tables: 4, overtime_tables: 1, calling_pending: 3 },
      });
      setLoading(false);
      return;
    }

    try {
      const res = await txFetch(
        `${API_BASE}/api/v1/kitchen-monitor/manager/${STORE_ID}`,
        undefined,
        TENANT_ID,
      );
      if (res.ok) {
        setData(res.data as ManagerData);
        setError(null);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    timerRef.current = setInterval(fetchData, REFRESH_MS);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [fetchData]);

  const handleCallUp = useCallback(async (orderId: string) => {
    try {
      await txFetch(
        `${API_BASE}/api/v1/kds/orders/${orderId}/call-up`,
        { method: 'POST' },
        TENANT_ID,
      );
      setActionMsg('整桌叫起成功');
      setTimeout(() => setActionMsg(null), 2500);
      await fetchData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '叫起失败');
    }
  }, [fetchData]);

  const handleRush = useCallback(async (orderId: string) => {
    try {
      await txFetch(
        `${API_BASE}/api/v1/kds/orders/${orderId}/rush-all`,
        { method: 'POST' },
        TENANT_ID,
      );
      setActionMsg('已发出全桌加急');
      setTimeout(() => setActionMsg(null), 2500);
      await fetchData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加急失败');
    }
  }, [fetchData]);

  const summary = data?.summary ?? { total_tables: 0, overtime_tables: 0, calling_pending: 0 };

  return (
    <div
      style={{
        background: '#0B0B0B',
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        fontFamily: 'Noto Sans SC, sans-serif',
        color: '#E0E0E0',
      }}
    >
      {/* 标题栏 */}
      <header
        style={{
          background: '#111',
          padding: '12px 20px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          borderBottom: '1px solid #222',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <span style={{ fontSize: 22, fontWeight: 700, color: '#fff' }}>
            控菜大屏
          </span>
          <span style={{ fontSize: 13, color: '#555' }}>厨师长视角</span>
        </div>
        <div style={{ display: 'flex', gap: 24 }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 32, fontWeight: 700, color: '#fff', lineHeight: 1, fontFamily: 'monospace' }}>
              {summary.total_tables}
            </div>
            <div style={{ fontSize: 12, color: '#555' }}>进行中桌台</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div
              style={{
                fontSize: 32,
                fontWeight: 700,
                color: summary.overtime_tables > 0 ? '#FF3B30' : '#30D158',
                lineHeight: 1,
                fontFamily: 'monospace',
              }}
            >
              {summary.overtime_tables}
            </div>
            <div style={{ fontSize: 12, color: '#555' }}>超时桌台</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div
              style={{
                fontSize: 32,
                fontWeight: 700,
                color: summary.calling_pending > 0 ? '#FF9F0A' : '#555',
                lineHeight: 1,
                fontFamily: 'monospace',
              }}
            >
              {summary.calling_pending}
            </div>
            <div style={{ fontSize: 12, color: '#555' }}>待叫起</div>
          </div>
        </div>
      </header>

      {/* 操作反馈 */}
      {actionMsg && (
        <div
          style={{
            background: '#0A2218',
            borderBottom: '2px solid #30D158',
            padding: '8px 20px',
            color: '#30D158',
            fontSize: 15,
            fontWeight: 600,
          }}
        >
          ✓ {actionMsg}
        </div>
      )}
      {error && (
        <div
          style={{
            background: '#2A0000',
            borderBottom: '2px solid #FF3B30',
            padding: '8px 20px',
            color: '#FF3B30',
            fontSize: 14,
          }}
        >
          {error}
        </div>
      )}

      {/* 主体：左档口负载 + 右桌台网格 */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          overflow: 'hidden',
        }}
      >
        {/* 左：档口负载 */}
        <div
          style={{
            width: 240,
            flexShrink: 0,
            background: '#111',
            borderRight: '1px solid #1A1A1A',
            overflowY: 'auto',
            padding: 12,
          }}
        >
          <div style={{ fontSize: 14, color: '#555', marginBottom: 10, fontWeight: 600 }}>
            档口实时负载
          </div>
          {(data?.depts ?? []).map((dept) => (
            <DeptLoadCard key={dept.dept_id} dept={dept} />
          ))}
        </div>

        {/* 右：桌台网格 */}
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: 16,
            WebkitOverflowScrolling: 'touch',
          }}
        >
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
              gap: 12,
            }}
          >
            {loading ? (
              <div style={{ gridColumn: '1/-1', color: '#555', textAlign: 'center', padding: 40 }}>
                加载中…
              </div>
            ) : (data?.tables ?? []).length === 0 ? (
              <div
                style={{
                  gridColumn: '1/-1',
                  color: '#333',
                  textAlign: 'center',
                  padding: '60px 0',
                  fontSize: 18,
                }}
              >
                当前暂无进行中的桌台
              </div>
            ) : (
              (data?.tables ?? []).map((t) => (
                <TableCard
                  key={t.order_id}
                  table={t}
                  onCallUp={handleCallUp}
                  onRush={handleRush}
                />
              ))
            )}
          </div>
        </div>
      </div>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.7; }
        }
      `}</style>
    </div>
  );
}
