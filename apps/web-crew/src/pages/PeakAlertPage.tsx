/**
 * 高峰提醒页 — 服务员端高峰状态 + 待催菜 + 加派响应
 * 移动端竖屏, 最小字体16px, 热区>=48px
 * 调用 GET /api/v1/peak-monitor/crew/*
 */
import { useState } from 'react';

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

interface RushDish {
  id: string;
  tableNo: string;
  dishName: string;
  qty: number;
  elapsedMin: number;
  rushCount: number;
  isOvertime: boolean;
}

interface DispatchRequest {
  id: string;
  area: string;
  reason: string;
  urgency: 'normal' | 'urgent' | 'critical';
  accepted: boolean;
}

/* ---------- Mock 数据 ---------- */
const MOCK_LEVEL: PeakLevel = 'peak';

const PEAK_CFG: Record<PeakLevel, { label: string; color: string; icon: string }> = {
  normal:  { label: '正常', color: C.green, icon: '~' },
  busy:    { label: '繁忙', color: C.warning, icon: '!' },
  peak:    { label: '高峰', color: C.accent, icon: '!!' },
  extreme: { label: '极端高峰', color: C.danger, icon: '!!!' },
};

const MOCK_RUSH_DISHES: RushDish[] = [
  { id: 'r1', tableNo: 'A03', dishName: '剁椒鱼头', qty: 1, elapsedMin: 28, rushCount: 2, isOvertime: true },
  { id: 'r2', tableNo: 'B01', dishName: '波士顿龙虾', qty: 1, elapsedMin: 32, rushCount: 1, isOvertime: true },
  { id: 'r3', tableNo: 'A05', dishName: '红烧肉', qty: 1, elapsedMin: 22, rushCount: 1, isOvertime: true },
  { id: 'r4', tableNo: 'C02', dishName: '蒜蓉蒸虾', qty: 2, elapsedMin: 18, rushCount: 0, isOvertime: false },
  { id: 'r5', tableNo: 'A01', dishName: '酸菜鱼', qty: 1, elapsedMin: 15, rushCount: 0, isOvertime: false },
  { id: 'r6', tableNo: 'B03', dishName: '清蒸鲈鱼', qty: 1, elapsedMin: 12, rushCount: 0, isOvertime: false },
];

const MOCK_DISPATCHES: DispatchRequest[] = [
  { id: 'dp1', area: 'A区 (大厅南)', reason: '3桌同时催菜，服务压力大', urgency: 'critical', accepted: false },
  { id: 'dp2', area: 'B区 (大厅北)', reason: '2桌新到客人需引导', urgency: 'normal', accepted: false },
];

/* ---------- 组件 ---------- */
export function PeakAlertPage() {
  const [level] = useState<PeakLevel>(MOCK_LEVEL);
  const cfg = PEAK_CFG[level];

  const [rushDishes, setRushDishes] = useState(MOCK_RUSH_DISHES);
  const [dispatches, setDispatches] = useState(MOCK_DISPATCHES);

  const overtimeCount = rushDishes.filter(d => d.isOvertime).length;

  const handleRush = (id: string) => {
    setRushDishes(prev => prev.map(d =>
      d.id === id ? { ...d, rushCount: d.rushCount + 1 } : d
    ));
    // TODO: POST /api/v1/orders/{orderId}/rush
  };

  const handleAcceptDispatch = (id: string) => {
    setDispatches(prev => prev.map(d =>
      d.id === id ? { ...d, accepted: true } : d
    ));
    // TODO: POST /api/v1/peak-monitor/dispatch/{id}/accept
  };

  return (
    <div style={{ padding: '16px 12px 80px', background: C.bg, minHeight: '100vh' }}>
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
      </div>

      {/* 快速统计 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 16 }}>
        {[
          { label: '待催菜', value: rushDishes.length, color: rushDishes.length > 4 ? C.danger : C.warning },
          { label: '已超时', value: overtimeCount, color: overtimeCount > 0 ? C.danger : C.green },
          { label: '待加派', value: dispatches.filter(d => !d.accepted).length, color: C.info },
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
      {dispatches.some(d => !d.accepted) && (
        <div style={{ marginBottom: 16 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: C.white, margin: '0 0 8px' }}>
            需要加派
          </h2>
          {dispatches.filter(d => !d.accepted).map(dp => (
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
          {dispatches.filter(d => d.accepted).map(dp => (
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
