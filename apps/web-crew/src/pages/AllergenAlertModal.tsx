/**
 * AllergenAlertModal — 过敏/忌口智能提醒弹窗
 *
 * 触发场景：服务员给已识别会员的订单添加菜品时，
 * 检测到该菜品含有会员的过敏原或忌口偏好。
 *
 * 设计原则：
 *   - 食安合规功能，UI 足够醒目，不可被忽视
 *   - 默认"取消添加"为推荐操作（绿色大按钮）
 *   - "仍然添加"为次要操作（灰色小字）
 *   - danger（真性过敏）vs warning（忌口偏好）两种展示模式
 */
import { useEffect } from 'react';

// ─── 类型 ───

export interface AllergenAlert {
  allergen_code: string;
  allergen_label: string;
  severity: 'danger' | 'warning';
}

export interface AllergenAlertModalProps {
  alerts: AllergenAlert[];
  dishName: string;
  memberName: string;
  onConfirm: () => void;  // 确认仍然添加
  onCancel: () => void;   // 取消添加（推荐）
}

// ─── 样式常量 ───

const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  white: '#ffffff',
  muted: '#94a3b8',
  green: '#22c55e',
  greenBg: '#14532d',
  red: '#ef4444',
  redBg: '#7f1d1d',
  yellow: '#facc15',
  yellowBg: '#713f12',
  overlay: 'rgba(0,0,0,0.72)',
};

// 过敏原代码 → emoji 映射
const ALLERGEN_EMOJI: Record<string, string> = {
  peanut:    '🥜',
  shellfish: '🦐',
  fish:      '🐟',
  egg:       '🥚',
  milk:      '🥛',
  soy:       '🫘',
  wheat:     '🌾',
  sesame:    '🌱',
  tree_nut:  '🌰',
  pork:      '🐷',
  beef:      '🐄',
  spicy:     '🌶',
  msg:       '🧂',
  sulfite:   '⚗️',
};

// ─── 子组件：过敏原标签 ───

function AllergenTag({ alert }: { alert: AllergenAlert }) {
  const emoji = ALLERGEN_EMOJI[alert.allergen_code] || '⚠️';
  const isDanger = alert.severity === 'danger';

  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6,
      padding: '8px 14px',
      borderRadius: 10,
      fontSize: 17,
      fontWeight: 700,
      background: isDanger ? C.redBg : C.yellowBg,
      color: isDanger ? C.red : C.yellow,
      border: `1.5px solid ${isDanger ? C.red : C.yellow}`,
      margin: '4px 6px 4px 0',
    }}>
      <span style={{ fontSize: 20 }}>{emoji}</span>
      {alert.allergen_label}
    </span>
  );
}

// ─── 主组件 ───

export function AllergenAlertModal({
  alerts,
  dishName,
  memberName,
  onConfirm,
  onCancel,
}: AllergenAlertModalProps) {
  // 最严重等级决定整体展示模式
  const hasDanger = alerts.some(a => a.severity === 'danger');
  const dangerAlerts = alerts.filter(a => a.severity === 'danger');
  const warningAlerts = alerts.filter(a => a.severity === 'warning');

  // 阻止背景滚动
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, []);

  return (
    /* 遮罩层 */
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: C.overlay,
        zIndex: 9999,
        display: 'flex',
        alignItems: 'flex-end',
        justifyContent: 'center',
      }}
      onClick={onCancel}
    >
      {/* 底部抽屉卡片 */}
      <div
        style={{
          width: '100%',
          maxWidth: 480,
          background: C.card,
          borderRadius: '20px 20px 0 0',
          padding: '24px 20px 36px',
          border: `2px solid ${hasDanger ? C.red : C.yellow}`,
          borderBottom: 'none',
          boxShadow: `0 -4px 32px ${hasDanger ? 'rgba(239,68,68,0.25)' : 'rgba(250,204,21,0.2)'}`,
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* 标题行 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
          <span style={{ fontSize: 28 }}>{hasDanger ? '🚨' : 'ℹ️'}</span>
          <h2 style={{
            fontSize: 22,
            fontWeight: 800,
            color: hasDanger ? C.red : C.yellow,
            margin: 0,
            letterSpacing: 0.5,
          }}>
            {hasDanger ? '过敏预警' : '忌口提醒'}
          </h2>
        </div>

        {/* 分割线 */}
        <div style={{
          height: 1,
          background: hasDanger ? `${C.red}44` : `${C.yellow}44`,
          marginBottom: 18,
        }} />

        {/* 顾客描述 */}
        {hasDanger ? (
          <p style={{ fontSize: 17, color: C.white, margin: '0 0 14px', lineHeight: 1.6 }}>
            该顾客（<strong style={{ color: C.red }}>{memberName}</strong>）对以下成分{' '}
            <strong style={{ color: C.red }}>过敏</strong>：
          </p>
        ) : (
          <p style={{ fontSize: 17, color: C.white, margin: '0 0 14px', lineHeight: 1.6 }}>
            该顾客（<strong style={{ color: C.yellow }}>{memberName}</strong>）有以下忌口偏好：
          </p>
        )}

        {/* 过敏原标签区 */}
        <div style={{ marginBottom: 18, display: 'flex', flexWrap: 'wrap' }}>
          {dangerAlerts.map(a => (
            <AllergenTag key={a.allergen_code} alert={a} />
          ))}
          {warningAlerts.map(a => (
            <AllergenTag key={a.allergen_code} alert={a} />
          ))}
        </div>

        {/* 菜品说明 */}
        <div style={{
          background: C.bg,
          borderRadius: 10,
          padding: '12px 16px',
          marginBottom: 18,
          border: `1px solid ${C.border}`,
        }}>
          <span style={{ fontSize: 17, color: C.muted }}>您正在添加：</span>
          <span style={{ fontSize: 18, fontWeight: 700, color: C.white, marginLeft: 6 }}>
            【{dishName}】
          </span>
          <span style={{ fontSize: 16, color: C.muted, marginLeft: 4 }}>含有以上过敏原</span>
        </div>

        {/* 建议提示 */}
        <p style={{
          fontSize: 16,
          color: C.muted,
          margin: '0 0 24px',
          padding: '10px 14px',
          background: `${hasDanger ? C.redBg : C.yellowBg}55`,
          borderRadius: 8,
          borderLeft: `3px solid ${hasDanger ? C.red : C.yellow}`,
        }}>
          {hasDanger
            ? '建议：询问顾客确认，或推荐无过敏原替代菜品'
            : '建议：确认顾客是否可以接受，必要时请厨房备注'}
        </p>

        {/* 操作按钮 */}
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          {/* 取消添加 — 推荐操作，绿色大按钮 */}
          <button
            onClick={onCancel}
            style={{
              flex: 2,
              minHeight: 56,
              borderRadius: 14,
              background: C.green,
              color: C.white,
              border: 'none',
              fontSize: 18,
              fontWeight: 800,
              cursor: 'pointer',
              boxShadow: '0 2px 12px rgba(34,197,94,0.35)',
              letterSpacing: 0.5,
            }}
          >
            取消添加（推荐）
          </button>

          {/* 仍然添加 — 次要操作，灰色小字 */}
          <button
            onClick={onConfirm}
            style={{
              flex: 1,
              minHeight: 48,
              borderRadius: 12,
              background: 'transparent',
              color: C.muted,
              border: `1px solid ${C.border}`,
              fontSize: 15,
              fontWeight: 500,
              cursor: 'pointer',
            }}
          >
            仍然添加
          </button>
        </div>
      </div>
    </div>
  );
}
