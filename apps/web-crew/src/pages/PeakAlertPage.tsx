/**
 * 高峰提醒页 — 服务员端高峰状态 + 待催菜 + 加派响应
 * 移动端竖屏, 最小字体16px, 热区>=48px
 * API: GET /api/v1/ops/peak/stores/{storeId}/detect
 *      GET /api/v1/ops/peak/stores/{storeId}/dept-load
 * 30秒自动刷新
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { txFetch } from '../api';

/* ---------- 样式常量 ---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B2C',
  green: '#0F6E56',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
  danger: '#A32D2D',
  warning: '#BA7517',
  info: '#185FA5',
};

/* ---------- 类型 ---------- */
type PeakLevel = 'normal' | 'busy' | 'peak' | 'extreme';

interface PeakDetectData {
  level: PeakLevel;
  current_diners: number;
  waiting_count: number;
  avg_serve_time_sec: number;
}

interface DeptLoad {
  id: string;
  area: string;
  reason: string;
  urgency: 'normal' | 'urgent' | 'critical';
  accepted: boolean;
}

interface RushDish {
  id: string;
  tableNo: string;
  dishName: string;
  qty: number;
  elapsedMin: number;
  rushCount: number;
  isOvertime: boolean;
}

/* ---------- 配置 ---------- */
const PEAK_CFG: Record<PeakLevel, { label: string; color: string; icon: string }> = {
  normal:  { label: '正常', color: C.green, icon: '~' },
  busy:    { label: '繁忙', color: C.warning, icon: '!' },
  peak:    { label: '高峰', color: C.accent, icon: '!!' },
  extreme: { label: '极端高峰', color: C.danger, icon: '!!!' },
};

/* ---------- 工具 ---------- */
function getStoreId(): string {
  return localStorage.getItem('tx_store_id') || '';
}

/* ---------- 组件 ---------- */
export function PeakAlertPage() {
  const [peakData, setPeakData] = useState<PeakDetectData | null>(null);
  const [deptLoads, setDeptLoads] = useState<DeptLoad[]>([]);
  const [rushDishes, setRushDishes] = useState<RushDish[]>([]);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const storeId = getStoreId();

  const loadData = useCallback(async () => {
    if (!storeId) return;
    setLoading(true);
    try {
      const [detect, deptRes] = await Promise.allSettled([
        txFetch<PeakDetectData>(`/api/v1/ops/peak/stores/${encodeURIComponent(storeId)}/detect`),
        txFetch<{ items: DeptLoad[] }>(`/api/v1/ops/peak/stores/${encodeURIComponent(storeId)}/dept-load`),
      ]);

      if (detect.status === 'fulfilled') {
        setPeakData(detect.value);
      }
      if (deptRes.status === 'fulfilled') {
        setDeptLoads(deptRes.value?.items ?? []);
      }

      // 催菜数据来自已有 rushDishes API
      try {
        const rushRes = await txFetch<{ items: RushDish[] }>(
          `/api/v1/ops/peak/stores/${encodeURIComponent(storeId)}/rush-dishes`
        );
        setRushDishes(rushRes?.items ?? []);
      } catch {
        // 静默失败，保留旧数据
      }
    } catch {
      // 全局失败，不崩溃
    } finally {
      setLoading(false);
    }
  }, [storeId]);

  useEffect(() => {
    loadData();
    timerRef.current = setInterval(loadData, 30_000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [loadData]);

  const level: PeakLevel = peakData?.level ?? 'normal';
  const cfg = PEAK_CFG[level];
  const overtimeCount = rushDishes.filter(d => d.isOvertime).length;

  const handleRush = async (id: string) => {
    setRushDishes(prev => prev.map(d =>
      d.id === id ? { ...d, rushCount: d.rushCount + 1 } : d
    ));
    try {
      await txFetch(`/api/v1/ops/rush-items/${encodeURIComponent(id)}`, { method: 'POST' });
    } catch {
      // 静默失败，计数已乐观更新
    }
  };

  const handleAcceptDispatch = async (id: string) => {
    setDeptLoads(prev => prev.map(d =>
      d.id === id ? { ...d, accepted: true } : d
    ));
    try {
      await txFetch(`/api/v1/ops/peak/dispatches/${encodeURIComponent(id)}/accept`, { method: 'POST' });
    } catch {
      // 静默失败，状态已乐观更新
    }
  };

  if (!storeId && !loading) {
    return (
      <div style={{ padding: '40px 16px', background: C.bg, minHeight: '100vh', textAlign: 'center', color: C.muted, fontSize: 16 }}>
        未找到门店信息，请重新登录
      </div>
    );
  }

  return (
    <div style={{ padding: '16px 12px 80px', background: C.bg, minHeight: '100vh' }}>
      {/* 刷新状态指示 */}
      {loading && (
        <div style={{ textAlign: 'right', fontSize: 12, color: C.muted, marginBottom: 8 }}>刷新中...</div>
      )}

      {/* 高峰状态提示 */}
      <div style={{
        background: `${cfg.color}20`,
        border: `2px solid ${cfg.color}`,
        borderRadius: 12,
        padding: 16,
        marginBottom: 16,
        textAlign: 'center',
      }}>
        <div style={{
          fontSize: 32, fontWeight: 800, color: cfg.color,
          marginBottom: 4,
          ...(level === 'extreme' ? { animation: 'pulse 1.5s infinite' } : {}),
        }}>
          {cfg.icon} {cfg.label}
        </div>
        <div style={{ fontSize: 16, color: C.text }}>
          {level === 'normal' && '客流平稳，正常服务'}
          {level === 'busy' && '客流上升，注意出餐速度'}
          {level === 'peak' && '高峰时段，留意催菜和等位'}
          {level === 'extreme' && '极端高峰，全员加速！'}
        </div>
        {peakData && (
          <div style={{ fontSize: 13, color: C.muted, marginTop: 6 }}>
            在场 {peakData.current_diners} 人 · 候位 {peakData.waiting_count} 组 · 均出餐 {Math.round(peakData.avg_serve_time_sec / 60)} 分钟
          </div>
        )}
      </div>

      {/* 快速统计 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 16 }}>
        {[
          { label: '待催菜', value: rushDishes.length, color: rushDishes.length > 4 ? C.danger : C.warning },
          { label: '已超时', value: overtimeCount, color: overtimeCount > 0 ? C.danger : C.green },
          { label: '待加派', value: deptLoads.filter(d => !d.accepted).length, color: C.info },
        ].map(stat => (
          <div key={stat.label} style={{
            background: C.card, borderRadius: 8, padding: 12, textAlign: 'center',
            border: `1px solid ${C.border}`,
          }}>
            <div style={{ fontSize: 28, fontWeight: 'bold', color: stat.color }}>{stat.value}</div>
            <div style={{ fontSize: 16, color: C.muted }}>{stat.label}</div>
          </div>
        ))}
      </div>

      {/* 加派区域提示 */}
      {deptLoads.some(d => !d.accepted) && (
        <div style={{ marginBottom: 16 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: C.white, margin: '0 0 8px' }}>
            需要加派
          </h2>
          {deptLoads.filter(d => !d.accepted).map(dp => (
            <div key={dp.id} style={{
              background: C.card, borderRadius: 12, padding: 16, marginBottom: 8,
              border: `1px solid ${dp.urgency === 'critical' ? C.danger : C.border}`,
              borderLeft: `4px solid ${dp.urgency === 'critical' ? C.danger : dp.urgency === 'urgent' ? C.warning : C.info}`,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <div>
                  <span style={{
                    fontSize: 16, padding: '2px 8px', borderRadius: 4,
                    background: dp.urgency === 'critical' ? `${C.danger}30` : `${C.warning}30`,
                    color: dp.urgency === 'critical' ? C.danger : C.warning,
                    fontWeight: 600,
                  }}>
                    {dp.urgency === 'critical' ? '紧急' : dp.urgency === 'urgent' ? '较急' : '一般'}
                  </span>
                  <span style={{ fontSize: 18, fontWeight: 700, color: C.white, marginLeft: 8 }}>{dp.area}</span>
                </div>
              </div>
              <div style={{ fontSize: 16, color: C.text, marginBottom: 12 }}>{dp.reason}</div>
              <button
                onClick={() => handleAcceptDispatch(dp.id)}
                style={{
                  width: '100%', minHeight: 48, borderRadius: 12,
                  background: C.accent, border: 'none',
                  color: C.white, fontSize: 18, fontWeight: 700, cursor: 'pointer',
                }}
              >
                接受加派
              </button>
            </div>
          ))}
          {/* 已接受的加派 */}
          {deptLoads.filter(d => d.accepted).map(dp => (
            <div key={dp.id} style={{
              background: C.card, borderRadius: 12, padding: 16, marginBottom: 8,
              border: `1px solid ${C.green}40`,
              borderLeft: `4px solid ${C.green}`,
              opacity: 0.7,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: 16, color: C.green, fontWeight: 600 }}>{dp.area} - 已接受</span>
                <span style={{
                  fontSize: 16, padding: '2px 8px', borderRadius: 4,
                  background: `${C.green}30`, color: C.green,
                }}>
                  已响应
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 待催菜列表 */}
      <h2 style={{ fontSize: 18, fontWeight: 700, color: C.white, margin: '0 0 8px' }}>
        待催菜 ({rushDishes.length})
      </h2>
      <p style={{ fontSize: 16, color: C.muted, margin: '0 0 12px' }}>
        超时菜品已标红，点击催菜按钮通知后厨
      </p>

      {rushDishes.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 40, color: C.muted, fontSize: 16 }}>
          暂无待催菜品
        </div>
      ) : (
        rushDishes.map(dish => (
          <div key={dish.id} style={{
            background: dish.isOvertime ? `${C.danger}15` : C.card,
            borderRadius: 12, padding: 16, marginBottom: 8,
            border: `1px solid ${dish.isOvertime ? `${C.danger}60` : C.border}`,
            borderLeft: `4px solid ${dish.isOvertime ? C.danger : C.warning}`,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <span style={{
                    fontSize: 16, fontWeight: 700,
                    color: dish.isOvertime ? C.danger : C.accent,
                    padding: '2px 8px', borderRadius: 4,
                    background: dish.isOvertime ? `${C.danger}25` : `${C.accent}25`,
                  }}>
                    {dish.tableNo}
                  </span>
                  <span style={{ fontSize: 18, fontWeight: 600, color: C.white }}>
                    {dish.dishName} x{dish.qty}
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 12, marginTop: 4 }}>
                  <span style={{
                    fontSize: 16,
                    color: dish.isOvertime ? C.danger : C.muted,
                    fontWeight: dish.isOvertime ? 700 : 400,
                  }}>
                    {dish.elapsedMin}分钟
                    {dish.isOvertime && ' 超时!'}
                  </span>
                  {dish.rushCount > 0 && (
                    <span style={{ fontSize: 16, color: C.warning }}>
                      已催{dish.rushCount}次
                    </span>
                  )}
                </div>
              </div>
              <button
                onClick={() => handleRush(dish.id)}
                style={{
                  minWidth: 72, minHeight: 48, padding: '8px 16px',
                  borderRadius: 8,
                  background: dish.isOvertime ? C.danger : `${C.accent}22`,
                  border: dish.isOvertime ? 'none' : `1px solid ${C.accent}`,
                  color: dish.isOvertime ? C.white : C.accent,
                  fontSize: 16, fontWeight: 700, cursor: 'pointer',
                }}
              >
                催菜
              </button>
            </div>
          </div>
        ))
      )}

      {/* 脉冲动画 */}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.6; }
        }
      `}</style>
    </div>
  );
}
