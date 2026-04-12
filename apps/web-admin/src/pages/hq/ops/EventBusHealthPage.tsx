/**
 * 事件总线健康监控仪表板 — Event Bus Health
 * 实时监控各业务域 Redis Stream 的消息积压量和消费状态
 */
import { useEffect, useState, useCallback } from 'react';
import { txFetchData } from '../../../api';

// ─── 类型定义 ───

interface ConsumerGroup {
  name: string;
  pending: number;
  consumers: number;
}

interface StreamInfo {
  length: number;
  exists?: boolean;
  consumer_groups?: ConsumerGroup[];
}

interface EventHealthData {
  ok: boolean;
  streams: Record<string, StreamInfo>;
}

interface SystemHealthData {
  ok: boolean;
  status: 'healthy' | 'degraded';
  checks: {
    redis: { ok: boolean; error?: string };
    event_streams: { ok: boolean; error?: string; streams?: Record<string, StreamInfo> };
    model_router: { ok: boolean; error?: string; key_prefix?: string };
  };
}

// ─── 常量 ───

const STREAM_LABELS: Record<string, { name: string; emoji: string; domain: string }> = {
  trade_events:   { name: '交易域', emoji: '🛒', domain: '订单/支付/桌台/班次' },
  supply_events:  { name: '供应链域', emoji: '📦', domain: '库存/收货/调拨/食材' },
  finance_events: { name: '财务域', emoji: '💰', domain: 'P&L/成本率/月结' },
  org_events:     { name: '人事域', emoji: '👥', domain: '考勤/审批/薪资' },
  menu_events:    { name: '菜单域', emoji: '🍜', domain: '发布/改价/售罄' },
  ops_events:     { name: '运营域', emoji: '📋', domain: '日清E1-E8/巡店' },
  member_events:  { name: '会员域', emoji: '🎁', domain: '注册/储值/积分' },
  agent_events:   { name: 'Agent域', emoji: '🤖', domain: 'Orchestrator/Skill Agent' },
};

const REFRESH_INTERVAL = 30_000; // 30秒

// ─── 工具函数 ───

function getStreamStatus(length: number): { label: string; color: string; bg: string } {
  if (length >= 5000) return { label: '积压严重', color: '#FF4D4D', bg: '#FF4D4D22' };
  if (length >= 1000) return { label: '积压警告', color: '#BA7517', bg: '#BA751722' };
  return { label: '正常', color: '#0F6E56', bg: '#0F6E5622' };
}

function formatNumber(n: number): string {
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万`;
  return n.toLocaleString('zh-CN');
}

// ─── 子组件：系统检查卡片 ───

function CheckCard({ title, ok, detail }: { title: string; ok: boolean; detail?: string }) {
  return (
    <div style={{
      background: '#1a2a33', borderRadius: 8, padding: '12px 16px',
      border: `1px solid ${ok ? '#0F6E5644' : '#A32D2D44'}`,
      display: 'flex', alignItems: 'center', gap: 12,
    }}>
      <span style={{ fontSize: 20 }}>{ok ? '✅' : '❌'}</span>
      <div>
        <div style={{ color: '#fff', fontSize: 14, fontWeight: 600 }}>{title}</div>
        {detail && <div style={{ color: ok ? '#0F6E56' : '#A32D2D', fontSize: 12, marginTop: 2 }}>{detail}</div>}
      </div>
    </div>
  );
}

// ─── 主页面 ───

export function EventBusHealthPage() {
  const [systemHealth, setSystemHealth] = useState<SystemHealthData | null>(null);
  const [eventHealth, setEventHealth] = useState<EventHealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [countdown, setCountdown] = useState(REFRESH_INTERVAL / 1000);

  const fetchData = useCallback(async () => {
    try {
      const [sys, events] = await Promise.all([
        txFetchData<SystemHealthData>('/api/v1/health'),
        txFetchData<EventHealthData>('/api/v1/health/events'),
      ]);
      setSystemHealth(sys);
      setEventHealth(events);
      setLastRefresh(new Date());
      setCountdown(REFRESH_INTERVAL / 1000);
    } catch {
      /* 保留旧数据 */
    } finally {
      setLoading(false);
    }
  }, []);

  // 自动刷新
  useEffect(() => {
    fetchData();
    const refreshTimer = setInterval(fetchData, REFRESH_INTERVAL);
    return () => clearInterval(refreshTimer);
  }, [fetchData]);

  // 倒计时显示
  useEffect(() => {
    const timer = setInterval(() => setCountdown(c => Math.max(0, c - 1)), 1000);
    return () => clearInterval(timer);
  }, [lastRefresh]);

  const isHealthy = systemHealth?.status === 'healthy';
  const streams = eventHealth?.streams || {};
  const totalMessages = Object.values(streams).reduce((s, v) => s + (v.length || 0), 0);
  const warningStreams = Object.values(streams).filter(v => (v.length || 0) >= 1000).length;
  const criticalStreams = Object.values(streams).filter(v => (v.length || 0) >= 5000).length;

  return (
    <div style={{ padding: 24, minHeight: '100vh', background: '#0d1e28', color: '#fff' }}>
      {/* 页头 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>🔄 事件总线监控</h2>
          <p style={{ color: '#888', margin: '4px 0 0', fontSize: 13 }}>
            Redis Streams 实时状态 · 8个业务域
          </p>
        </div>
        <div style={{ textAlign: 'right' }}>
          <button onClick={fetchData} style={{
            padding: '6px 14px', borderRadius: 6, border: '1px solid #2a3a44',
            background: 'transparent', color: '#888', cursor: 'pointer', fontSize: 13, marginBottom: 4,
          }}>
            ↻ 立即刷新
          </button>
          <div style={{ color: '#888', fontSize: 12 }}>
            {countdown}s 后自动刷新 · 上次 {lastRefresh.toLocaleTimeString('zh-CN')}
          </div>
        </div>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 60, color: '#888' }}>加载中...</div>
      ) : (
        <>
          {/* 整体健康状态 */}
          <div style={{
            background: isHealthy ? '#0F6E5622' : '#A32D2D22',
            border: `2px solid ${isHealthy ? '#0F6E56' : '#A32D2D'}`,
            borderRadius: 12, padding: '20px 24px', marginBottom: 24,
            display: 'flex', alignItems: 'center', gap: 20,
          }}>
            <div style={{ fontSize: 48 }}>{isHealthy ? '✅' : '⚠️'}</div>
            <div style={{ flex: 1 }}>
              <div style={{
                fontSize: 22, fontWeight: 700,
                color: isHealthy ? '#0F6E56' : '#BA7517',
              }}>
                系统状态：{isHealthy ? 'HEALTHY' : 'DEGRADED'}
              </div>
              <div style={{ color: '#888', fontSize: 13, marginTop: 4 }}>
                总消息量 {formatNumber(totalMessages)} 条
                {warningStreams > 0 && ` · ${warningStreams} 个 Stream 积压警告`}
                {criticalStreams > 0 && ` · ${criticalStreams} 个 Stream 积压严重`}
              </div>
            </div>
          </div>

          {/* 子系统检查 */}
          {systemHealth?.checks && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12, marginBottom: 24 }}>
              <CheckCard
                title="Redis 连接"
                ok={systemHealth.checks.redis.ok}
                detail={systemHealth.checks.redis.ok ? '连接正常' : systemHealth.checks.redis.error}
              />
              <CheckCard
                title="事件流"
                ok={systemHealth.checks.event_streams.ok}
                detail={systemHealth.checks.event_streams.ok ? '读写正常' : systemHealth.checks.event_streams.error}
              />
              <CheckCard
                title="AI 模型路由"
                ok={systemHealth.checks.model_router.ok}
                detail={systemHealth.checks.model_router.ok
                  ? `API Key: ${systemHealth.checks.model_router.key_prefix}`
                  : systemHealth.checks.model_router.error}
              />
            </div>
          )}

          {/* Stream 详情表格 */}
          <div style={{ background: '#1a2a33', borderRadius: 12, overflow: 'hidden' }}>
            <div style={{ padding: '14px 20px', borderBottom: '1px solid #2a3a44', fontSize: 14, color: '#888' }}>
              各业务域 Stream 状态
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: '#0d1e28' }}>
                  {['业务域', '消息积压量', '消费状态', '积压进度', '状态'].map(h => (
                    <th key={h} style={{
                      padding: '10px 16px', textAlign: 'left',
                      color: '#888', fontSize: 12, fontWeight: 500,
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(STREAM_LABELS).map(([key, info]) => {
                  const stream = streams[key] || { length: 0, exists: false };
                  const status = getStreamStatus(stream.length);
                  const maxForBar = 5000;
                  const barPct = Math.min(100, (stream.length / maxForBar) * 100);
                  const totalPending = (stream.consumer_groups || []).reduce((s, g) => s + g.pending, 0);

                  return (
                    <tr key={key} style={{ borderBottom: '1px solid #2a3a4440' }}>
                      <td style={{ padding: '14px 16px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <span style={{ fontSize: 20 }}>{info.emoji}</span>
                          <div>
                            <div style={{ color: '#fff', fontWeight: 600, fontSize: 14 }}>{info.name}</div>
                            <div style={{ color: '#888', fontSize: 11 }}>{info.domain}</div>
                          </div>
                        </div>
                      </td>
                      <td style={{ padding: '14px 16px' }}>
                        <span style={{ fontSize: 20, fontWeight: 700, color: status.color }}>
                          {formatNumber(stream.length)}
                        </span>
                        <span style={{ color: '#888', fontSize: 12, marginLeft: 4 }}>条</span>
                      </td>
                      <td style={{ padding: '14px 16px' }}>
                        {totalPending > 0 ? (
                          <span style={{ color: '#BA7517', fontSize: 13 }}>
                            {totalPending} 条待确认
                          </span>
                        ) : (
                          <span style={{ color: '#0F6E56', fontSize: 13 }}>✓ 无积压</span>
                        )}
                      </td>
                      <td style={{ padding: '14px 16px', width: 160 }}>
                        <div style={{ height: 6, background: '#0d1e28', borderRadius: 3, overflow: 'hidden' }}>
                          <div style={{
                            width: `${barPct}%`, height: '100%', borderRadius: 3,
                            background: barPct >= 100 ? '#FF4D4D' : barPct >= 20 ? '#BA7517' : '#0F6E56',
                            transition: 'width 0.4s ease',
                          }} />
                        </div>
                        <div style={{ color: '#888', fontSize: 11, marginTop: 3 }}>
                          {barPct.toFixed(0)}% / 5k阈值
                        </div>
                      </td>
                      <td style={{ padding: '14px 16px' }}>
                        <span style={{
                          padding: '3px 10px', borderRadius: 12, fontSize: 12,
                          background: status.bg, color: status.color,
                        }}>
                          {status.label}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* 积压说明 */}
          <div style={{ display: 'flex', gap: 20, marginTop: 16, color: '#888', fontSize: 12 }}>
            <span>● <span style={{ color: '#0F6E56' }}>正常</span>：&lt; 1,000 条</span>
            <span>● <span style={{ color: '#BA7517' }}>积压警告</span>：1,000 – 4,999 条</span>
            <span>● <span style={{ color: '#FF4D4D' }}>积压严重</span>：≥ 5,000 条（需排查消费者）</span>
          </div>
        </>
      )}
    </div>
  );
}
