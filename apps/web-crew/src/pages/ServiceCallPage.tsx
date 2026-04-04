/**
 * ServiceCallPage - 呼叫服务页
 * 实时呼叫列表（10s刷新）+ 处理 + 今日统计
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

/* ---------- 类型 ---------- */
interface ServiceCall {
  id: string;
  table: string;
  type: '加水' | '要纸巾' | '结账' | '其他';
  createdAt: number;
  handled: boolean;
  handledAt: number | null;
}

interface DailyCallStats {
  total: number;
  handled: number;
  avgResponseSec: number;
}

/* ---------- 常量 ---------- */
const REFRESH_MS = 10_000;

const TYPE_COLORS: Record<ServiceCall['type'], string> = {
  '加水':   '#3B82F6',
  '要纸巾': '#F59E0B',
  '结账':   '#22C55E',
  '其他':   '#8B5CF6',
};

/* ---------- mock 数据 ---------- */
let callIdCounter = 0;

function mockCalls(): ServiceCall[] {
  const types: ServiceCall['type'][] = ['加水', '要纸巾', '结账', '其他'];
  const tables = ['A1', 'A3', 'B2', 'B5', 'C1', 'C3', 'D2', 'D4'];
  const now = Date.now();
  return Array.from({ length: 5 + Math.floor(Math.random() * 4) }, (_, i) => {
    callIdCounter += 1;
    const handled = i >= 4;
    return {
      id: `call-${callIdCounter}`,
      table: tables[i % tables.length],
      type: types[i % types.length],
      createdAt: now - (i * 90_000 + Math.floor(Math.random() * 60_000)),
      handled,
      handledAt: handled ? now - i * 30_000 : null,
    };
  });
}

function mockStats(calls: ServiceCall[]): DailyCallStats {
  const handled = calls.filter(c => c.handled);
  const avgSec = handled.length > 0
    ? Math.round(handled.reduce((s, c) => s + ((c.handledAt ?? c.createdAt) - c.createdAt) / 1000, 0) / handled.length)
    : 0;
  return {
    total: calls.length,
    handled: handled.length,
    avgResponseSec: avgSec || 45,
  };
}

function formatWait(createdAt: number): string {
  const sec = Math.floor((Date.now() - createdAt) / 1000);
  if (sec < 60) return `${sec}秒`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}分${sec % 60}秒`;
  return `${Math.floor(min / 60)}时${min % 60}分`;
}

/* ---------- 组件 ---------- */
export function ServiceCallPage() {
  const nav = useNavigate();
  const [calls, setCalls] = useState<ServiceCall[]>([]);
  const [stats, setStats] = useState<DailyCallStats>({ total: 0, handled: 0, avgResponseSec: 0 });
  const [, setTick] = useState(0); // 强制刷新等待时长

  const refresh = useCallback(() => {
    const data = mockCalls();
    setCalls(data);
    setStats(mockStats(data));
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, REFRESH_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  // 每秒更新等待时长显示
  useEffect(() => {
    const t = setInterval(() => setTick(n => n + 1), 1000);
    return () => clearInterval(t);
  }, []);

  const vibrate = () => { try { navigator.vibrate(50); } catch (_e) { /* noop */ } };

  const handleProcess = (callId: string) => {
    vibrate();
    setCalls(prev => {
      const next = prev.map(c =>
        c.id === callId ? { ...c, handled: true, handledAt: Date.now() } : c,
      );
      setStats(mockStats(next));
      return next;
    });
  };

  const pending = calls.filter(c => !c.handled);
  const handled = calls.filter(c => c.handled);

  return (
    <div style={{ padding: '0 0 80px', maxWidth: 480, margin: '0 auto' }}>
      {/* 顶部栏 */}
      <div style={{
        background: '#112228', padding: '12px 14px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <button
          onClick={() => { vibrate(); nav(-1); }}
          style={{
            background: 'none', border: 'none', color: '#94a3b8', fontSize: 16,
            cursor: 'pointer', minWidth: 48, minHeight: 48,
            display: 'flex', alignItems: 'center',
          }}
        >
          &lt; 返回
        </button>
        <span style={{ fontSize: 20, fontWeight: 700 }}>呼叫服务</span>
        <div style={{ width: 48 }} />
      </div>

      {/* 今日统计 */}
      <div style={{
        background: '#112228', borderRadius: 12, margin: '12px 12px 0',
        padding: 16, display: 'flex', justifyContent: 'space-around',
      }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 24, fontWeight: 700, color: '#FF6B35' }}>{stats.total}</div>
          <div style={{ fontSize: 14, color: '#64748b', marginTop: 2 }}>总呼叫</div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 24, fontWeight: 700, color: '#22C55E' }}>{stats.handled}</div>
          <div style={{ fontSize: 14, color: '#64748b', marginTop: 2 }}>已处理</div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 24, fontWeight: 700, color: '#3B82F6' }}>{stats.avgResponseSec}s</div>
          <div style={{ fontSize: 14, color: '#64748b', marginTop: 2 }}>平均响应</div>
        </div>
      </div>

      {/* 待处理列表 */}
      <div style={{ padding: '12px 12px 0' }}>
        <div style={{ fontSize: 16, fontWeight: 600, color: '#e2e8f0', marginBottom: 8 }}>
          待处理
          {pending.length > 0 && (
            <span style={{
              fontSize: 14, background: '#EF444433', color: '#EF4444',
              borderRadius: 8, padding: '2px 8px', marginLeft: 8,
            }}>
              {pending.length}
            </span>
          )}
        </div>
        {pending.length === 0 && (
          <div style={{
            background: '#112228', borderRadius: 12, padding: 24,
            textAlign: 'center', color: '#475569', fontSize: 16,
          }}>
            暂无待处理呼叫
          </div>
        )}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {pending.map(call => (
            <div key={call.id} style={{
              background: '#112228', borderRadius: 12, padding: '14px 16px',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                  <span style={{ fontSize: 28, fontWeight: 700 }}>{call.table}</span>
                  <span style={{
                    fontSize: 14, fontWeight: 600, borderRadius: 6,
                    padding: '4px 10px',
                    background: `${TYPE_COLORS[call.type]}22`,
                    color: TYPE_COLORS[call.type],
                  }}>
                    {call.type}
                  </span>
                </div>
                <div style={{ fontSize: 16, color: '#F59E0B' }}>
                  等待 {formatWait(call.createdAt)}
                </div>
              </div>
              <button
                onClick={() => handleProcess(call.id)}
                style={{
                  background: '#FF6B35', border: 'none', borderRadius: 10,
                  color: '#fff', fontSize: 16, fontWeight: 700,
                  padding: '12px 20px', cursor: 'pointer',
                  minWidth: 48, minHeight: 48,
                }}
              >
                处理
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* 已处理列表 */}
      {handled.length > 0 && (
        <div style={{ padding: '16px 12px 0' }}>
          <div style={{ fontSize: 16, fontWeight: 600, color: '#64748b', marginBottom: 8 }}>
            已处理
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {handled.map(call => (
              <div key={call.id} style={{
                background: '#0d1f26', borderRadius: 12, padding: '12px 16px',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                opacity: 0.6,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: 22, fontWeight: 700, color: '#475569' }}>{call.table}</span>
                  <span style={{
                    fontSize: 14, borderRadius: 6, padding: '3px 8px',
                    background: '#1a2a33', color: '#64748b',
                  }}>
                    {call.type}
                  </span>
                </div>
                <span style={{ fontSize: 14, color: '#475569' }}>已处理</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
