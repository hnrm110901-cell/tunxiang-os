/**
 * 高峰值守监控页 — 店长/总部实时监控门店高峰状态
 * 功能: 状态指示 + 档口负载 + 等位拥堵 + 服务加派建议 + 临时操作
 * 调用 GET /api/v1/ops/peak/*
 */
import { useState, useEffect, useRef } from 'react';
import { apiGet } from '../../../api/client';

// ---------- 类型 ----------
type PeakLevel = 'normal' | 'busy' | 'peak' | 'extreme';

interface StallLoad {
  id: string;
  name: string;
  currentOrders: number;
  capacity: number;
  avgWaitMin: number;
}

interface WaitingInfo {
  type: string;
  count: number;
  estimateMin: number;
}

interface DispatchSuggestion {
  id: string;
  area: string;
  reason: string;
  suggestedStaff: string;
  urgency: 'normal' | 'urgent' | 'critical';
}

interface KpiItem {
  label: string;
  value: string;
  sub: string;
}

interface PeakDetectData {
  level: PeakLevel;
  kpi: KpiItem[];
  waiting: WaitingInfo[];
  suggestions: DispatchSuggestion[];
}

interface DeptLoadData {
  stalls: StallLoad[];
}

// ---------- 高峰等级配置 ----------
const PEAK_CONFIG: Record<PeakLevel, { label: string; color: string; bg: string; desc: string }> = {
  normal:  { label: '正常',    color: '#0F6E56', bg: '#0F6E5630', desc: '客流平稳，各档口运转正常' },
  busy:    { label: '繁忙',    color: '#BA7517', bg: '#BA751730', desc: '客流上升，部分档口压力较大' },
  peak:    { label: '高峰',    color: '#FF6B2C', bg: '#FF6B2C30', desc: '高峰时段，需要加派人手' },
  extreme: { label: '极端高峰', color: '#A32D2D', bg: '#A32D2D30', desc: '客流爆满，启动应急预案' },
};

// ---------- 工具函数 ----------
const loadPercent = (s: StallLoad) => Math.round((s.currentOrders / s.capacity) * 100);
const loadColor = (pct: number) => pct >= 90 ? '#A32D2D' : pct >= 70 ? '#BA7517' : '#0F6E56';
const urgencyColor = (u: string) => u === 'critical' ? '#A32D2D' : u === 'urgent' ? '#BA7517' : '#185FA5';
const urgencyLabel = (u: string) => u === 'critical' ? '紧急' : u === 'urgent' ? '较急' : '建议';

// ---------- 默认空状态 ----------
const DEFAULT_PEAK: PeakDetectData = {
  level: 'normal',
  kpi: [],
  waiting: [],
  suggestions: [],
};

// ---------- 组件 ----------
export function PeakMonitorPage() {
  // 当前选中的门店 ID（实际项目中应从路由/全局状态读取）
  const storeId = 'current';

  const [peakData, setPeakData] = useState<PeakDetectData>(DEFAULT_PEAK);
  const [stalls, setStalls] = useState<StallLoad[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState('');
  const [quickMode, setQuickMode] = useState(false);

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchData = async () => {
    try {
      const [detect, deptLoad] = await Promise.all([
        apiGet<PeakDetectData>(`/api/v1/ops/peak/stores/${storeId}/detect`).catch(() => null),
        apiGet<DeptLoadData>(`/api/v1/ops/peak/stores/${storeId}/dept-load`).catch(() => null),
      ]);
      if (detect) setPeakData(detect);
      if (deptLoad) setStalls(deptLoad.stalls);
      setLastUpdated(new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }));
    } catch {
      // 静默失败，保持上次数据
    } finally {
      setLoading(false);
    }
  };

  // 首次加载 + 30s 自动刷新
  useEffect(() => {
    fetchData();
    timerRef.current = setInterval(fetchData, 30_000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [storeId]); // eslint-disable-line react-hooks/exhaustive-deps

  const level = peakData.level;
  const cfg = PEAK_CONFIG[level];

  return (
    <div>
      {/* 标题行 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>高峰值守</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {lastUpdated && (
            <span style={{ fontSize: 12, color: '#999' }}>{lastUpdated} 更新</span>
          )}
          <span style={{ fontSize: 12, color: '#999' }}>自动刷新 30s</span>
          <span style={{
            width: 8, height: 8, borderRadius: '50%', background: loading ? '#BA7517' : '#0F6E56',
            display: 'inline-block', animation: 'pulse 2s infinite',
          }} />
        </div>
      </div>

      {/* 当前状态大色块 */}
      <div style={{
        background: cfg.bg,
        border: `2px solid ${cfg.color}`,
        borderRadius: 12,
        padding: '24px 32px',
        marginBottom: 24,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
            <span style={{
              fontSize: 28, fontWeight: 800, color: cfg.color,
              padding: '4px 16px', borderRadius: 8,
              background: `${cfg.color}20`,
            }}>
              {cfg.label}
            </span>
          </div>
          <div style={{ fontSize: 14, color: '#ccc' }}>{cfg.desc}</div>
        </div>
        {level === 'extreme' && (
          <div style={{
            padding: '8px 20px', background: '#A32D2D', borderRadius: 8,
            color: '#fff', fontWeight: 700, fontSize: 14,
            animation: 'pulse 1.5s infinite',
          }}>
            应急模式已激活
          </div>
        )}
      </div>

      {/* KPI 卡片 */}
      {peakData.kpi.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 24 }}>
          {peakData.kpi.map((kpi) => (
            <div key={kpi.label} style={{
              background: '#112228', borderRadius: 8, padding: 16,
              borderLeft: '3px solid #FF6B2C',
            }}>
              <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>{kpi.label}</div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
                <span style={{ fontSize: 24, fontWeight: 'bold', color: '#fff' }}>{kpi.value}</span>
                <span style={{ fontSize: 12, color: '#999' }}>{kpi.sub}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        {/* 档口负载仪表盘 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>档口负载</h3>
          {stalls.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#666', padding: 24 }}>暂无档口数据</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {stalls.map((stall) => {
                const pct = loadPercent(stall);
                const color = loadColor(pct);
                return (
                  <div key={stall.id}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <span style={{ fontSize: 13, color: '#fff' }}>{stall.name}</span>
                      <span style={{ fontSize: 12, color }}>
                        {stall.currentOrders}/{stall.capacity} 单 | 均{stall.avgWaitMin}分钟
                      </span>
                    </div>
                    <div style={{
                      height: 12, borderRadius: 6, background: '#0B1A20',
                      overflow: 'hidden',
                    }}>
                      <div style={{
                        width: `${Math.min(pct, 100)}%`, height: '100%',
                        borderRadius: 6, background: color,
                        transition: 'width 0.6s ease',
                      }} />
                    </div>
                    <div style={{ textAlign: 'right', fontSize: 11, color, marginTop: 2 }}>
                      {pct}%
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* 等位拥堵面板 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>等位情况</h3>
          {peakData.waiting.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#666', padding: 24 }}>暂无等位数据</div>
          ) : (
            <>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {peakData.waiting.map((w) => (
                  <div key={w.type} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: 12, background: '#0B1A20', borderRadius: 8,
                    borderLeft: `3px solid ${w.estimateMin > 30 ? '#A32D2D' : w.estimateMin > 15 ? '#BA7517' : '#0F6E56'}`,
                  }}>
                    <div>
                      <div style={{ fontSize: 14, color: '#fff', fontWeight: 600 }}>{w.type}</div>
                      <div style={{ fontSize: 12, color: '#999', marginTop: 2 }}>预计等待 {w.estimateMin} 分钟</div>
                    </div>
                    <div style={{ textAlign: 'center' }}>
                      <div style={{
                        fontSize: 28, fontWeight: 'bold',
                        color: w.count >= 5 ? '#A32D2D' : w.count >= 3 ? '#BA7517' : '#fff',
                      }}>
                        {w.count}
                      </div>
                      <div style={{ fontSize: 11, color: '#999' }}>桌</div>
                    </div>
                  </div>
                ))}
              </div>
              <div style={{
                marginTop: 12, padding: 10, borderRadius: 8,
                background: '#FF6B2C15', border: '1px solid #FF6B2C40',
                fontSize: 13, color: '#FF6B2C', textAlign: 'center',
              }}>
                总等位 {peakData.waiting.reduce((s, w) => s + w.count, 0)} 桌 /
                约 {peakData.waiting.reduce((s, w) => s + w.count, 0) * 3} 人
              </div>
            </>
          )}
        </div>
      </div>

      {/* 服务加派建议 */}
      <div style={{ background: '#112228', borderRadius: 8, padding: 20, marginBottom: 16 }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>服务加派建议</h3>
        {peakData.suggestions.length === 0 ? (
          <div style={{ textAlign: 'center', color: '#666', padding: 24 }}>暂无加派建议</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {peakData.suggestions.map((s) => (
              <div key={s.id} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: 14, background: '#0B1A20', borderRadius: 8,
                borderLeft: `3px solid ${urgencyColor(s.urgency)}`,
              }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{
                      fontSize: 11, padding: '2px 8px', borderRadius: 4, fontWeight: 600,
                      background: `${urgencyColor(s.urgency)}20`,
                      color: urgencyColor(s.urgency),
                    }}>
                      {urgencyLabel(s.urgency)}
                    </span>
                    <span style={{ fontSize: 14, fontWeight: 600, color: '#fff' }}>{s.area}</span>
                  </div>
                  <div style={{ fontSize: 13, color: '#ccc' }}>{s.reason}</div>
                  <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>
                    建议加派: <span style={{ color: '#FF6B2C' }}>{s.suggestedStaff}</span>
                  </div>
                </div>
                <button style={{
                  padding: '8px 16px', borderRadius: 6, border: 'none',
                  background: `${urgencyColor(s.urgency)}20`, color: urgencyColor(s.urgency),
                  cursor: 'pointer', fontWeight: 600, fontSize: 12, whiteSpace: 'nowrap',
                }}>
                  通知加派
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 临时操作按钮 */}
      <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>快速操作</h3>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <button
            onClick={() => alert('调菜: 将低负载档口菜品临时分配到高负载档口')}
            style={{
              padding: '10px 24px', borderRadius: 8, border: '1px solid #BA7517',
              background: '#BA751720', color: '#BA7517', cursor: 'pointer',
              fontWeight: 600, fontSize: 13,
            }}
          >
            调菜分流
          </button>
          <button
            onClick={() => alert('调台: 合并/拆分桌台以提高翻台率')}
            style={{
              padding: '10px 24px', borderRadius: 8, border: '1px solid #185FA5',
              background: '#185FA520', color: '#185FA5', cursor: 'pointer',
              fontWeight: 600, fontSize: 13,
            }}
          >
            调台优化
          </button>
          <button
            onClick={() => setQuickMode(!quickMode)}
            style={{
              padding: '10px 24px', borderRadius: 8, border: 'none',
              background: quickMode ? '#A32D2D' : '#FF6B2C',
              color: '#fff', cursor: 'pointer',
              fontWeight: 600, fontSize: 13,
            }}
          >
            {quickMode ? '退出快速模式' : '启用快速模式'}
          </button>
          <button
            onClick={() => alert('一键通知: 向所有服务员发送高峰预警')}
            style={{
              padding: '10px 24px', borderRadius: 8, border: '1px solid #0F6E56',
              background: '#0F6E5620', color: '#0F6E56', cursor: 'pointer',
              fontWeight: 600, fontSize: 13,
            }}
          >
            一键通知全员
          </button>
        </div>
        {quickMode && (
          <div style={{
            marginTop: 12, padding: 10, borderRadius: 8,
            background: '#A32D2D20', border: '1px solid #A32D2D',
            fontSize: 13, color: '#A32D2D',
          }}>
            快速模式已启用: 简化点餐流程 / 自动合并小桌 / 出餐优先级自动调整
          </div>
        )}
      </div>

      {/* 脉冲动画样式 */}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.6; }
        }
      `}</style>
    </div>
  );
}
