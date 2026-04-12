/**
 * TimeoutAlert — 超时预警组件
 *
 * 超时任务高亮闪烁
 * 分级：normal(白) / warning(黄) / critical(红)
 * 超时时间倒计时
 * 深色背景，触控优化（最小48x48按钮，最小16px字体）
 */
import { useState, useEffect } from 'react';

// ─── Types ───

type AlertLevel = 'normal' | 'warning' | 'critical';

interface TimeoutTicket {
  id: string;
  orderNo: string;
  tableNo: string;
  items: string[];
  dept: string;
  createdAt: number;     // timestamp ms
  timeLimitMin: number;  // 出餐时限（分钟）
  priority: 'normal' | 'rush' | 'vip';
  resolved: boolean;
  resolvedAt?: number;
}

// ─── Mock Data ───

const now = Date.now();
const min = (m: number) => m * 60 * 1000;

const MOCK_ALERTS: TimeoutTicket[] = [
  { id: 'a1', orderNo: '005', tableNo: 'A05', items: ['剁椒鱼头', '口味虾'], dept: '炒炉', createdAt: now - min(42), timeLimitMin: 25, priority: 'rush', resolved: false },
  { id: 'a2', orderNo: '008', tableNo: 'B01', items: ['外婆鸡', '红烧肉'], dept: '蒸菜', createdAt: now - min(35), timeLimitMin: 25, priority: 'vip', resolved: false },
  { id: 'a3', orderNo: '012', tableNo: 'A02', items: ['酸菜鱼'], dept: '炒炉', createdAt: now - min(28), timeLimitMin: 25, priority: 'normal', resolved: false },
  { id: 'a4', orderNo: '015', tableNo: 'C01', items: ['蒜蓉虾', '清蒸鱼'], dept: '蒸菜', createdAt: now - min(26), timeLimitMin: 25, priority: 'normal', resolved: false },
  { id: 'a5', orderNo: '003', tableNo: 'A01', items: ['小炒肉', '米饭x3'], dept: '炒炉', createdAt: now - min(50), timeLimitMin: 25, priority: 'normal', resolved: true, resolvedAt: now - min(10) },
  { id: 'a6', orderNo: '006', tableNo: 'B02', items: ['蒸鲈鱼'], dept: '蒸菜', createdAt: now - min(45), timeLimitMin: 25, priority: 'normal', resolved: true, resolvedAt: now - min(5) },
];

// ─── Helpers ───

function getAlertLevel(createdAt: number, timeLimitMin: number): AlertLevel {
  const elapsed = (Date.now() - createdAt) / 60000;
  const overtime = elapsed - timeLimitMin;
  if (overtime >= 10) return 'critical';
  if (overtime >= 0) return 'warning';
  return 'normal';
}

const LEVEL_STYLES: Record<AlertLevel, { bg: string; border: string; timeColor: string; label: string }> = {
  normal: { bg: '#111', border: '#333', timeColor: '#E0E0E0', label: '即将超时' },
  warning: { bg: '#1a1500', border: '#BA7517', timeColor: '#BA7517', label: '已超时' },
  critical: { bg: '#1a0505', border: '#A32D2D', timeColor: '#ff4d4f', label: '严重超时' },
};

function formatOvertime(createdAt: number, timeLimitMin: number): string {
  const elapsedSec = Math.floor((Date.now() - createdAt) / 1000);
  const limitSec = timeLimitMin * 60;
  const overtimeSec = elapsedSec - limitSec;
  if (overtimeSec <= 0) {
    const remain = -overtimeSec;
    const m = Math.floor(remain / 60);
    const s = remain % 60;
    return `-${m}:${String(s).padStart(2, '0')}`;
  }
  const m = Math.floor(overtimeSec / 60);
  const s = overtimeSec % 60;
  return `+${m}:${String(s).padStart(2, '0')}`;
}

function formatElapsed(createdAt: number): string {
  const m = Math.floor((Date.now() - createdAt) / 60000);
  return `${m}分钟`;
}

// ─── Component ───

export function TimeoutAlert() {
  const [alerts, setAlerts] = useState<TimeoutTicket[]>(MOCK_ALERTS);
  const [_tick, setTick] = useState(0);
  const [tab, setTab] = useState<'active' | 'history'>('active');

  // 每秒刷新
  useEffect(() => {
    const timer = setInterval(() => setTick(t => t + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  const activeAlerts = alerts.filter(a => !a.resolved).sort((a, b) => a.createdAt - b.createdAt);
  const historyAlerts = alerts.filter(a => a.resolved).sort((a, b) => (b.resolvedAt || 0) - (a.resolvedAt || 0));

  const handleResolve = (id: string) => {
    setAlerts(prev => prev.map(a =>
      a.id === id ? { ...a, resolved: true, resolvedAt: Date.now() } : a
    ));
  };

  const tabStyle = (active: boolean, color: string): React.CSSProperties => ({
    padding: '12px 32px',
    minHeight: 48,
    cursor: 'pointer',
    fontSize: 18,
    fontWeight: 'bold',
    background: active ? color : '#1a1a1a',
    color: active ? '#fff' : '#888',
    border: 'none',
    borderRadius: 8,
    transition: 'transform 200ms ease',
  });

  return (
    <div style={{
      background: '#0A0A0A', minHeight: '100vh', color: '#E0E0E0',
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
      padding: 20,
    }}>
      {/* 顶栏 */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 20,
      }}>
        <h1 style={{ margin: 0, fontSize: 28, color: '#FF6B35' }}>
          超时预警
          {activeAlerts.length > 0 && (
            <span style={{
              display: 'inline-block', marginLeft: 12, fontSize: 20,
              padding: '4px 14px', borderRadius: 12,
              background: '#A32D2D', color: '#fff',
              animation: 'timeout-pulse 1.5s infinite',
            }}>
              {activeAlerts.length}
            </span>
          )}
        </h1>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 20 }}>
        <button
          onClick={() => setTab('active')}
          style={tabStyle(tab === 'active', '#A32D2D')}
          onTouchStart={e => (e.currentTarget.style.transform = 'scale(0.97)')}
          onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
        >
          实时告警 ({activeAlerts.length})
        </button>
        <button
          onClick={() => setTab('history')}
          style={tabStyle(tab === 'history', '#1890ff')}
          onTouchStart={e => (e.currentTarget.style.transform = 'scale(0.97)')}
          onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
        >
          历史记录 ({historyAlerts.length})
        </button>
      </div>

      {/* 实时告警 */}
      {tab === 'active' && (
        <div>
          {activeAlerts.length === 0 && (
            <div style={{ textAlign: 'center', padding: 80, color: '#0F6E56', fontSize: 24 }}>
              当前无超时订单
            </div>
          )}
          {activeAlerts.map(alert => {
            const level = getAlertLevel(alert.createdAt, alert.timeLimitMin);
            const style = LEVEL_STYLES[level];
            const overtime = formatOvertime(alert.createdAt, alert.timeLimitMin);
            const isCritical = level === 'critical';

            return (
              <div key={alert.id} style={{
                background: style.bg,
                border: `2px solid ${style.border}`,
                borderRadius: 12, padding: 18, marginBottom: 12,
                animation: isCritical ? 'timeout-flash 1.5s infinite' : undefined,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <span style={{ fontSize: 32, fontWeight: 'bold', color: '#fff' }}>{alert.tableNo}</span>
                    <span style={{ fontSize: 16, color: '#666' }}>#{alert.orderNo}</span>
                    {alert.priority === 'rush' && (
                      <span style={{ fontSize: 16, padding: '2px 10px', borderRadius: 6, background: '#A32D2D', color: '#fff', fontWeight: 'bold' }}>催</span>
                    )}
                    {alert.priority === 'vip' && (
                      <span style={{ fontSize: 16, padding: '2px 10px', borderRadius: 6, background: 'linear-gradient(135deg, #C5A347, #E8D48B)', color: '#1a1a00', fontWeight: 'bold' }}>VIP</span>
                    )}
                    <span style={{
                      fontSize: 16, padding: '4px 12px', borderRadius: 6,
                      background: '#1a1a1a', color: '#888',
                    }}>
                      {alert.dept}
                    </span>
                  </div>

                  {/* 超时计时器 */}
                  <div style={{ textAlign: 'right' }}>
                    <div style={{
                      fontSize: 36, fontWeight: 'bold',
                      color: style.timeColor,
                      fontFamily: 'JetBrains Mono, monospace',
                    }}>
                      {overtime}
                    </div>
                    <div style={{
                      fontSize: 16, fontWeight: 'bold',
                      color: style.timeColor,
                    }}>
                      {style.label}
                    </div>
                  </div>
                </div>

                {/* 菜品 */}
                <div style={{ fontSize: 20, fontWeight: 'bold', marginBottom: 12 }}>
                  {alert.items.join(' / ')}
                </div>

                {/* 底部：总耗时 + 操作 */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 16, color: '#888' }}>
                    已等待 {formatElapsed(alert.createdAt)} | 时限 {alert.timeLimitMin}分钟
                  </span>
                  <button
                    onClick={() => handleResolve(alert.id)}
                    style={{
                      padding: '12px 32px', background: '#0F6E56', color: '#fff',
                      border: 'none', borderRadius: 8, cursor: 'pointer',
                      fontSize: 18, fontWeight: 'bold', minHeight: 48,
                      transition: 'transform 200ms ease',
                    }}
                    onTouchStart={e => (e.currentTarget.style.transform = 'scale(0.97)')}
                    onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
                  >
                    已处理
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* 历史 */}
      {tab === 'history' && (
        <div>
          {historyAlerts.map(alert => (
            <div key={alert.id} style={{
              background: '#111', borderRadius: 10, padding: 16, marginBottom: 8,
              opacity: 0.7, borderLeft: '4px solid #555',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: 22, fontWeight: 'bold', color: '#aaa' }}>{alert.tableNo}</span>
                  <span style={{ fontSize: 18 }}>{alert.items.join(' / ')}</span>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{
                    fontSize: 20, fontWeight: 'bold', color: '#BA7517',
                    fontFamily: 'JetBrains Mono, monospace',
                  }}>
                    {Math.floor((alert.resolvedAt! - alert.createdAt) / 60000)}'
                  </div>
                  <div style={{ fontSize: 16, color: '#666' }}>
                    {alert.dept}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 动画 */}
      <style>{`
        @keyframes timeout-pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.7; }
        }
        @keyframes timeout-flash {
          0%, 100% { border-color: #A32D2D; background-color: #1a0505; }
          50% { border-color: #ff4d4f; background-color: #2a0a0a; }
        }
      `}</style>
    </div>
  );
}
