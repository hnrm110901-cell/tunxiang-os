/**
 * KitchenMonitorDashboard — 厨房综合异常监控大屏
 *
 * 三列布局：超时 | 沽清 | 退菜
 * 每60秒自动刷新
 *
 * 颜色约定：
 *   超时 = #FF3B30
 *   沽清 = #FF9500
 *   退菜 = #FFCC00
 */
import { useCallback, useEffect, useState } from 'react';

// ─── Types ───

interface OvertimeTask {
  task_id: string;
  table_no: string;
  dish_name: string;
  elapsed_min: number;
  standard_min: number;
  overtime_min: number;
  status: 'warning' | 'critical';
  dept: string;
}

interface ShortageAlert {
  dish_id: string;
  dish_name: string;
  shortage_count: number;
  latest_at: string;
}

interface RemakeTask {
  task_id: string;
  table_no: string;
  dish_name: string;
  reason: string;
  created_at: string;
}

interface DashboardData {
  overtime_tasks: OvertimeTask[];
  shortage_alerts: ShortageAlert[];
  remake_tasks: RemakeTask[];
  summary: {
    overtime_count: number;
    shortage_count: number;
    remake_count: number;
    total_anomalies: number;
  };
}

// ─── Constants ───

const COLOR_OVERTIME = '#FF3B30';
const COLOR_SHORTAGE = '#FF9500';
const COLOR_REMAKE = '#FFCC00';
const REFRESH_INTERVAL_MS = 60_000;

const API_BASE = (window as any).__STORE_API_BASE__ || '/api/v1/kitchen-monitor';
const STORE_ID = (window as any).__STORE_ID__ || '';
const TENANT_ID = (window as any).__TENANT_ID__ || '';

// ─── Helpers ───

function _formatTime(iso: string): string {
  if (!iso) return '--:--';
  try {
    const d = new Date(iso);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  } catch {
    return iso;
  }
}

function _badgeStyle(color: string, size: number = 22): React.CSSProperties {
  return {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    minWidth: size,
    height: size,
    padding: '0 6px',
    borderRadius: size / 2,
    background: color,
    color: '#fff',
    fontSize: size - 6,
    fontWeight: 'bold',
    marginLeft: 8,
    lineHeight: 1,
  };
}

// ─── Sub-components ───

function ColumnHeader({
  title,
  count,
  color,
}: {
  title: string;
  count: number;
  color: string;
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        padding: '10px 14px',
        borderBottom: `2px solid ${color}`,
        background: '#111',
        position: 'sticky',
        top: 0,
        zIndex: 1,
      }}
    >
      <span style={{ fontWeight: 'bold', fontSize: 18, color }}>
        {title}
      </span>
      {count > 0 && (
        <span style={_badgeStyle(color, 26)}>{count}</span>
      )}
    </div>
  );
}

function OvertimeCard({ task }: { task: OvertimeTask }) {
  const overRatio =
    task.standard_min > 0
      ? Math.min(1, task.elapsed_min / (task.standard_min * 2))
      : 0;
  const isCritical = task.status === 'critical';

  return (
    <div
      style={{
        background: isCritical ? '#2A0000' : '#1A0000',
        border: `1px solid ${isCritical ? COLOR_OVERTIME : '#550000'}`,
        borderRadius: 10,
        padding: 14,
        marginBottom: 8,
      }}
    >
      {/* 桌号 + 菜名 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <div>
          <span
            style={{ fontSize: 22, fontWeight: 'bold', color: '#fff', marginRight: 8 }}
          >
            {task.table_no || '—'}
          </span>
          <span style={{ fontSize: 16, color: '#ccc' }}>{task.dish_name}</span>
        </div>
        <div
          style={{
            fontFamily: 'JetBrains Mono, monospace',
            fontSize: 28,
            fontWeight: 'bold',
            color: COLOR_OVERTIME,
          }}
        >
          {task.elapsed_min.toFixed(0)}'
        </div>
      </div>

      {/* 超时进度条 */}
      <div
        style={{
          height: 6,
          borderRadius: 3,
          background: '#440000',
          overflow: 'hidden',
          marginBottom: 6,
        }}
      >
        <div
          style={{
            width: `${overRatio * 100}%`,
            height: '100%',
            background: COLOR_OVERTIME,
            transition: 'width 0.3s',
          }}
        />
      </div>

      {/* 标准时间 */}
      <div style={{ fontSize: 13, color: '#888' }}>
        标准 {task.standard_min}分钟
        {task.overtime_min > 0 && (
          <span style={{ color: COLOR_OVERTIME, marginLeft: 8 }}>
            已超时 {task.overtime_min.toFixed(0)}分钟
          </span>
        )}
        {task.dept && (
          <span style={{ marginLeft: 8, color: '#555' }}>{task.dept}</span>
        )}
      </div>
    </div>
  );
}

function ShortageCard({ alert }: { alert: ShortageAlert }) {
  return (
    <div
      style={{
        background: '#1A0D00',
        border: `1px solid #553300`,
        borderRadius: 10,
        padding: 14,
        marginBottom: 8,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
      }}
    >
      <div>
        <div style={{ fontSize: 18, fontWeight: 'bold', color: '#fff', marginBottom: 4 }}>
          {alert.dish_name || '未知菜品'}
        </div>
        <div style={{ fontSize: 13, color: '#888' }}>
          最近：{_formatTime(alert.latest_at)}
        </div>
      </div>
      <div style={{ textAlign: 'right' }}>
        <div
          style={{
            fontSize: 32,
            fontWeight: 'bold',
            color: COLOR_SHORTAGE,
            fontFamily: 'JetBrains Mono, monospace',
          }}
        >
          {alert.shortage_count}
        </div>
        <div style={{ fontSize: 12, color: '#666' }}>今日次数</div>
      </div>
    </div>
  );
}

function RemakeCard({ task }: { task: RemakeTask }) {
  return (
    <div
      style={{
        background: '#1A1500',
        border: `1px solid #554400`,
        borderRadius: 10,
        padding: 14,
        marginBottom: 8,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <div>
          <span
            style={{ fontSize: 22, fontWeight: 'bold', color: '#fff', marginRight: 8 }}
          >
            {task.table_no || '—'}
          </span>
          <span style={{ fontSize: 16, color: '#ccc' }}>{task.dish_name}</span>
        </div>
        <div style={{ fontSize: 13, color: '#888' }}>{_formatTime(task.created_at)}</div>
      </div>

      {/* 原因标签 */}
      {task.reason && (
        <div style={{ marginTop: 6 }}>
          <span
            style={{
              display: 'inline-block',
              padding: '2px 10px',
              borderRadius: 4,
              background: '#443300',
              color: COLOR_REMAKE,
              fontSize: 13,
              fontWeight: 'bold',
            }}
          >
            {task.reason}
          </span>
        </div>
      )}
    </div>
  );
}

function EmptyState({ label, color }: { label: string; color: string }) {
  return (
    <div
      style={{
        textAlign: 'center',
        padding: '48px 16px',
        color,
        opacity: 0.4,
        fontSize: 16,
      }}
    >
      {label}
    </div>
  );
}

// ─── Main Component ───

export function KitchenMonitorDashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [error, setError] = useState<string | null>(null);

  const fetchDashboard = useCallback(async () => {
    if (!STORE_ID || !TENANT_ID) {
      // 开发模式：使用 mock 数据
      setData({
        overtime_tasks: [
          {
            task_id: 'mock-t1',
            table_no: 'A05',
            dish_name: '剁椒鱼头',
            elapsed_min: 38,
            standard_min: 20,
            overtime_min: 18,
            status: 'critical',
            dept: '热菜档口',
          },
          {
            task_id: 'mock-t2',
            table_no: 'B02',
            dish_name: '口味虾',
            elapsed_min: 22,
            standard_min: 18,
            overtime_min: 4,
            status: 'warning',
            dept: '热菜档口',
          },
        ],
        shortage_alerts: [
          {
            dish_id: 'mock-d1',
            dish_name: '三文鱼刺身',
            shortage_count: 3,
            latest_at: new Date().toISOString(),
          },
          {
            dish_id: 'mock-d2',
            dish_name: '象拔蚌',
            shortage_count: 1,
            latest_at: new Date(Date.now() - 1800_000).toISOString(),
          },
        ],
        remake_tasks: [
          {
            task_id: 'mock-r1',
            table_no: 'C01',
            dish_name: '小炒肉',
            reason: '顾客不满意',
            created_at: new Date(Date.now() - 900_000).toISOString(),
          },
        ],
        summary: {
          overtime_count: 2,
          shortage_count: 2,
          remake_count: 1,
          total_anomalies: 5,
        },
      });
      setLoading(false);
      return;
    }

    try {
      const resp = await fetch(`${API_BASE}/dashboard/${STORE_ID}`, {
        headers: {
          'X-Tenant-ID': TENANT_ID,
          'Content-Type': 'application/json',
        },
      });
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      const json = await resp.json();
      if (json.ok) {
        setData(json.data as DashboardData);
        setError(null);
      } else {
        setError(json.error?.message || '获取数据失败');
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(`网络错误：${msg}`);
    } finally {
      setLoading(false);
      setLastRefresh(new Date());
    }
  }, []);

  useEffect(() => {
    fetchDashboard();
    const timer = setInterval(fetchDashboard, REFRESH_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [fetchDashboard]);

  const summary = data?.summary ?? {
    overtime_count: 0,
    shortage_count: 0,
    remake_count: 0,
    total_anomalies: 0,
  };

  const overtime = data?.overtime_tasks ?? [];
  const shortage = data?.shortage_alerts ?? [];
  const remake = data?.remake_tasks ?? [];

  return (
    <div
      style={{
        background: '#0B0B0B',
        color: '#E0E0E0',
        minHeight: '100vh',
        fontFamily: 'Noto Sans SC, sans-serif',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* ── 顶部总览 ── */}
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
          <span style={{ fontSize: 22, fontWeight: 'bold', color: '#fff' }}>
            厨房异常监控
          </span>
          {/* 今日总异常数（大红数字） */}
          <span
            style={{
              fontSize: 40,
              fontWeight: 'bold',
              color: summary.total_anomalies > 0 ? COLOR_OVERTIME : '#52c41a',
              fontFamily: 'JetBrains Mono, monospace',
              lineHeight: 1,
            }}
          >
            {summary.total_anomalies}
          </span>
          <span style={{ fontSize: 14, color: '#666' }}>今日异常</span>
        </div>

        {/* 右上角三个数字角标 */}
        <div style={{ display: 'flex', gap: 20, alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 14, color: COLOR_OVERTIME }}>超时</span>
            <span style={_badgeStyle(COLOR_OVERTIME, 28)}>
              {summary.overtime_count}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 14, color: COLOR_SHORTAGE }}>沽清</span>
            <span style={_badgeStyle(COLOR_SHORTAGE, 28)}>
              {summary.shortage_count}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 14, color: COLOR_REMAKE }}>退菜</span>
            <span style={_badgeStyle(COLOR_REMAKE, 28)}>
              {summary.remake_count}
            </span>
          </div>
          {/* 刷新状态 */}
          <div style={{ fontSize: 12, color: '#444', marginLeft: 8 }}>
            {loading ? (
              <span style={{ color: '#888' }}>刷新中…</span>
            ) : (
              <>
                {_formatTime(lastRefresh.toISOString())} 更新
                <button
                  onClick={fetchDashboard}
                  style={{
                    marginLeft: 8,
                    padding: '2px 8px',
                    background: '#222',
                    border: '1px solid #333',
                    borderRadius: 4,
                    color: '#888',
                    cursor: 'pointer',
                    fontSize: 12,
                  }}
                >
                  刷新
                </button>
              </>
            )}
          </div>
        </div>
      </header>

      {/* 错误提示 */}
      {error && (
        <div
          style={{
            background: '#2A0000',
            border: '1px solid #ff4d4f',
            padding: '8px 16px',
            color: '#ff4d4f',
            fontSize: 14,
            flexShrink: 0,
          }}
        >
          {error}
        </div>
      )}

      {/* ── 三列主体 ── */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          gap: 2,
          overflow: 'hidden',
        }}
      >
        {/* 超时列 */}
        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            background: '#0D0000',
            overflow: 'hidden',
          }}
        >
          <ColumnHeader title="超时" count={overtime.length} color={COLOR_OVERTIME} />
          <div style={{ flex: 1, overflowY: 'auto', padding: 10 }}>
            {overtime.length === 0 ? (
              <EmptyState label="暂无超时工单" color={COLOR_OVERTIME} />
            ) : (
              overtime.map((t) => <OvertimeCard key={t.task_id} task={t} />)
            )}
          </div>
        </div>

        {/* 沽清列 */}
        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            background: '#0D0700',
            overflow: 'hidden',
          }}
        >
          <ColumnHeader title="沽清" count={shortage.length} color={COLOR_SHORTAGE} />
          <div style={{ flex: 1, overflowY: 'auto', padding: 10 }}>
            {shortage.length === 0 ? (
              <EmptyState label="今日暂无沽清" color={COLOR_SHORTAGE} />
            ) : (
              shortage.map((a) => (
                <ShortageCard key={a.dish_id || a.dish_name} alert={a} />
              ))
            )}
          </div>
        </div>

        {/* 退菜列 */}
        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            background: '#0D0D00',
            overflow: 'hidden',
          }}
        >
          <ColumnHeader title="退菜" count={remake.length} color={COLOR_REMAKE} />
          <div style={{ flex: 1, overflowY: 'auto', padding: 10 }}>
            {remake.length === 0 ? (
              <EmptyState label="今日暂无退菜" color={COLOR_REMAKE} />
            ) : (
              remake.map((r) => <RemakeCard key={r.task_id} task={r} />)
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
