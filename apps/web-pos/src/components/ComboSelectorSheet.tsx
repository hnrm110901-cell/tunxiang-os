/**
 * ComboSelectorSheet — 套餐N选M选择器全屏弹层
 *
 * 业务流程：
 *   1. 顶部：套餐名称、套餐价、节省金额
 *   2. 按分组展示可选菜品（每组一个卡片区域）
 *   3. 分组标题：「主菜（任选2款）」+ 已选数量提示
 *   4. 每个菜品：图片/名称/加价 + 选中态（橙色边框 + ✓角标）
 *   5. 底部进度指示：各组完成情况
 *   6. 确认按钮（disabled直到所有必选组都满足）
 *   7. 确认前调用 POST /api/v1/menu/combos/{comboId}/validate-selection
 *   8. 验证通过后回调 onConfirm
 *
 * Store 触控规范：
 *   - 所有可点击元素 ≥ 48×48px
 *   - 确认按钮 72px 高
 *   - 最小字体 16px
 *   - 弹层从底部滑出（translateY 300ms）
 *   - 按钮按下 scale(0.97) + 200ms
 *   - 禁止 Select 下拉 / hover 反馈
 */

import { useState, useEffect } from 'react';
import ReactDOM from 'react-dom';
import { getMacMiniUrl } from '../bridge/TXBridge';

// ─── Design Tokens ────────────────────────────────────────────────────────────

const T = {
  primary:    'var(--tx-primary, #FF6B35)',
  success:    'var(--tx-success, #0F6E56)',
  danger:     'var(--tx-danger, #A32D2D)',
  warning:    'var(--tx-warning, #BA7517)',
  text1:      'var(--tx-text-1, #2C2C2A)',
  text2:      'var(--tx-text-2, #5F5E5A)',
  bg1:        'var(--tx-bg-1, #FFFFFF)',
  bg2:        'var(--tx-bg-2, #F8F7F5)',
  border:     '#E8E6E1',
  radius:     '12px',
  tapMin:     48,
  tapRec:     56,
  tapLg:      72,
} as const;

// ─── 动画注入（一次性）────────────────────────────────────────────────────────

const KEYFRAMES_ID = 'tx-combo-selector-kf';
function ensureKeyframes(): void {
  if (document.getElementById(KEYFRAMES_ID)) return;
  const s = document.createElement('style');
  s.id = KEYFRAMES_ID;
  s.textContent = `
    @keyframes tx-combo-in  { from { transform: translateY(100%); } to { transform: translateY(0); } }
    @keyframes tx-combo-out { from { transform: translateY(0); }    to { transform: translateY(100%); } }
    @keyframes tx-check-in  { from { transform: scale(0); opacity:0; } to { transform: scale(1); opacity:1; } }
  `;
  document.head.appendChild(s);
}

// ─── 辅助函数 ─────────────────────────────────────────────────────────────────

const fen2yuan = (fen: number): string => `¥${(fen / 100).toFixed(0)}`;

// ─── Props 类型 ───────────────────────────────────────────────────────────────

interface ComboItem {
  id: string;
  dishId: string;
  dishName: string;
  quantity: number;
  extraPriceFen: number;
  imageUrl?: string;
}

interface ComboGroup {
  id: string;
  groupName: string;
  minSelect: number;
  maxSelect: number;
  isRequired: boolean;
  items: ComboItem[];
}

interface Combo {
  id: string;
  comboName: string;
  comboPriceFen: number;
  originalPriceFen: number;
  groups: ComboGroup[];
}

export interface ComboSelectorSheetProps {
  visible: boolean;
  combo: Combo;
  onConfirm: (selections: { groupId: string; itemIds: string[] }[]) => void;
  onClose: () => void;
}

// ─── 内联 TXButton ────────────────────────────────────────────────────────────

type TXBtnVariant = 'primary' | 'secondary' | 'ghost';

interface TXBtnProps {
  variant?: TXBtnVariant;
  large?: boolean;
  fullWidth?: boolean;
  disabled?: boolean;
  loading?: boolean;
  children: React.ReactNode;
  onPress: () => void;
  style?: React.CSSProperties;
}

function TXButton({ variant = 'primary', large = false, fullWidth = false, disabled = false, loading = false, children, onPress, style }: TXBtnProps) {
  const [pressing, setPressing] = useState(false);

  const bg: Record<TXBtnVariant, string> = { primary: T.primary, secondary: T.bg2, ghost: 'transparent' };
  const fg: Record<TXBtnVariant, string> = { primary: '#fff', secondary: T.text1, ghost: T.primary };
  const bd: Record<TXBtnVariant, string> = { primary: 'none', secondary: `1.5px solid ${T.border}`, ghost: `1.5px solid ${T.primary}` };

  return (
    <button
      type="button"
      disabled={disabled || loading}
      onPointerDown={() => setPressing(true)}
      onPointerUp={() => { setPressing(false); if (!disabled && !loading) onPress(); }}
      onPointerLeave={() => setPressing(false)}
      style={{
        height: large ? T.tapLg : T.tapRec,
        width: fullWidth ? '100%' : undefined,
        minWidth: T.tapMin,
        padding: '0 24px',
        background: disabled ? '#E8E6E1' : bg[variant],
        color: disabled ? T.text2 : fg[variant],
        border: disabled ? 'none' : bd[variant],
        borderRadius: T.radius,
        fontSize: 18,
        fontWeight: 600,
        fontFamily: 'inherit',
        cursor: disabled ? 'not-allowed' : 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        transform: pressing && !disabled ? 'scale(0.97)' : 'scale(1)',
        transition: 'transform 200ms ease',
        userSelect: 'none',
        WebkitUserSelect: 'none',
        opacity: disabled ? 0.5 : 1,
        boxShadow: variant === 'primary' && !disabled ? '0 4px 12px rgba(255,107,53,0.3)' : undefined,
        ...style,
      }}
    >
      {loading ? '验证中...' : children}
    </button>
  );
}

// ─── 菜品卡片 ─────────────────────────────────────────────────────────────────

interface DishCardProps {
  item: ComboItem;
  selected: boolean;
  selectable: boolean;
  onToggle: () => void;
}

function DishCard({ item, selected, selectable, onToggle }: DishCardProps) {
  const [pressing, setPressing] = useState(false);

  return (
    <div
      role="checkbox"
      aria-checked={selected}
      aria-label={item.dishName}
      onPointerDown={() => setPressing(true)}
      onPointerUp={() => { setPressing(false); if (selected || selectable) onToggle(); }}
      onPointerLeave={() => setPressing(false)}
      style={{
        position: 'relative',
        border: selected
          ? `2px solid ${T.primary}`
          : `1.5px solid ${T.border}`,
        borderRadius: T.radius,
        background: selected ? 'rgba(255,107,53,0.05)' : T.bg1,
        cursor: selected || selectable ? 'pointer' : 'not-allowed',
        opacity: !selected && !selectable ? 0.45 : 1,
        transform: pressing && (selected || selectable) ? 'scale(0.97)' : 'scale(1)',
        transition: 'transform 200ms ease, border-color 150ms ease, background 150ms ease',
        userSelect: 'none',
        WebkitUserSelect: 'none',
        overflow: 'hidden',
        minHeight: T.tapMin,
      }}
    >
      {/* 菜品图片 */}
      {item.imageUrl ? (
        <div style={{ height: 96, overflow: 'hidden' }}>
          <img
            src={item.imageUrl}
            alt={item.dishName}
            style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
            loading="lazy"
          />
        </div>
      ) : (
        <div style={{
          height: 72,
          background: T.bg2,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 28,
          color: '#B4B2A9',
        }}>
          🍽
        </div>
      )}

      {/* 菜品信息 */}
      <div style={{ padding: '8px 10px 10px' }}>
        <div style={{ fontSize: 17, fontWeight: 600, color: T.text1, lineHeight: 1.3 }}>
          {item.dishName}
        </div>
        {item.extraPriceFen > 0 && (
          <div style={{ fontSize: 16, color: T.warning, marginTop: 4 }}>
            +{fen2yuan(item.extraPriceFen)}
          </div>
        )}
        {item.extraPriceFen === 0 && (
          <div style={{ fontSize: 16, color: T.success, marginTop: 4 }}>包含</div>
        )}
      </div>

      {/* 选中角标 */}
      {selected && (
        <div
          aria-hidden="true"
          style={{
            position: 'absolute',
            top: 0,
            right: 0,
            width: 28,
            height: 28,
            background: T.primary,
            borderRadius: '0 10px 0 12px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            animation: 'tx-check-in 200ms ease-out both',
          }}
        >
          <span style={{ color: '#fff', fontSize: 14, fontWeight: 700, lineHeight: 1 }}>✓</span>
        </div>
      )}
    </div>
  );
}

// ─── 主组件 ───────────────────────────────────────────────────────────────────

export function ComboSelectorSheet({
  visible,
  combo,
  onConfirm,
  onClose,
}: ComboSelectorSheetProps) {
  ensureKeyframes();

  // 每个 groupId → 已选 itemId 数组
  const [selections, setSelections] = useState<Record<string, string[]>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [closing, setClosing] = useState(false);

  // 弹层关闭时重置
  useEffect(() => {
    if (!visible) {
      setSelections({});
      setError(null);
      setSubmitting(false);
      setClosing(false);
    }
  }, [visible]);

  // ── 选中逻辑 ─────────────────────────────────────────────────────────────────

  const toggleItem = (group: ComboGroup, itemId: string) => {
    setSelections((prev) => {
      const current = prev[group.id] ?? [];
      const isSelected = current.includes(itemId);

      if (isSelected) {
        // 取消选中
        return { ...prev, [group.id]: current.filter((id) => id !== itemId) };
      }

      if (current.length >= group.maxSelect) {
        // 已达上限：如果是单选（maxSelect=1），替换；否则忽略
        if (group.maxSelect === 1) {
          return { ...prev, [group.id]: [itemId] };
        }
        return prev; // 已满，不允许继续选
      }

      return { ...prev, [group.id]: [...current, itemId] };
    });
  };

  // ── 进度计算 ──────────────────────────────────────────────────────────────────

  const groupProgress = combo.groups.map((g) => {
    const selected = selections[g.id]?.length ?? 0;
    const done = selected >= g.minSelect;
    return { groupId: g.id, groupName: g.groupName, selected, min: g.minSelect, max: g.maxSelect, required: g.isRequired, done };
  });

  const allRequiredDone = groupProgress
    .filter((p) => p.required)
    .every((p) => p.done);

  const savingFen = combo.originalPriceFen - combo.comboPriceFen;

  // ── 提交 ─────────────────────────────────────────────────────────────────────

  const handleConfirm = async () => {
    if (!allRequiredDone || submitting) return;
    setSubmitting(true);
    setError(null);

    const payload = combo.groups.map((g) => ({
      groupId: g.id,
      itemIds: selections[g.id] ?? [],
    }));

    try {
      const apiBase = getMacMiniUrl();
      const tenantId = import.meta.env.VITE_TENANT_ID as string || '';

      const resp = await fetch(`${apiBase}/api/v1/menu/combos/${combo.id}/validate-selection`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(tenantId ? { 'X-Tenant-ID': tenantId } : {}),
        },
        body: JSON.stringify({ selections: payload }),
      });

      const json: { ok: boolean; error?: { message: string } } = await resp.json();

      if (!json.ok) {
        throw new Error(json.error?.message ?? '套餐验证失败，请重新选择');
      }

      onConfirm(payload);
      handleClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : '网络错误，请重试');
    } finally {
      setSubmitting(false);
    }
  };

  // ── 关闭动画 ──────────────────────────────────────────────────────────────────

  const handleClose = () => {
    setClosing(true);
    setTimeout(() => {
      setClosing(false);
      onClose();
    }, 300);
  };

  if (!visible && !closing) return null;

  // ── 渲染 ──────────────────────────────────────────────────────────────────────

  return ReactDOM.createPortal(
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* 遮罩 */}
      <div
        role="presentation"
        onClick={handleClose}
        style={{
          position: 'absolute',
          inset: 0,
          background: 'rgba(44,44,42,0.55)',
          backdropFilter: 'blur(2px)',
          WebkitBackdropFilter: 'blur(2px)',
        }}
      />

      {/* 全屏弹层主体 */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${combo.comboName} 套餐选择`}
        style={{
          position: 'relative',
          marginTop: 'env(safe-area-inset-top, 0px)',
          flex: 1,
          background: T.bg1,
          borderRadius: '20px 20px 0 0',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 -8px 32px rgba(0,0,0,0.18)',
          animation: `${closing ? 'tx-combo-out' : 'tx-combo-in'} 300ms ease-out both`,
          fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
          overflow: 'hidden',
        }}
      >
        {/* ─ 顶部信息 ─ */}
        <div style={{
          flexShrink: 0,
          padding: '16px 20px',
          borderBottom: `1px solid ${T.border}`,
          background: T.bg1,
        }}>
          {/* 拖拽指示条 */}
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 12 }}>
            <div style={{ width: 40, height: 4, borderRadius: 2, background: T.border }} />
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <div style={{ fontSize: 22, fontWeight: 700, color: T.text1, lineHeight: 1.3 }}>
                {combo.comboName}
              </div>
              {savingFen > 0 && (
                <div style={{ fontSize: 16, color: T.success, marginTop: 4 }}>
                  比单点节省 {fen2yuan(savingFen)}
                </div>
              )}
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 26, fontWeight: 700, color: T.primary }}>
                {fen2yuan(combo.comboPriceFen)}
              </div>
              {savingFen > 0 && (
                <div style={{ fontSize: 16, color: '#B4B2A9', textDecoration: 'line-through', marginTop: 2 }}>
                  {fen2yuan(combo.originalPriceFen)}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ─ 分组选择区（可滚动）─ */}
        <div style={{
          flex: 1,
          overflowY: 'auto',
          WebkitOverflowScrolling: 'touch',
          padding: '0 20px',
        }}>
          {combo.groups.map((group) => {
            const selectedIds = selections[group.id] ?? [];
            const progress = groupProgress.find((p) => p.groupId === group.id)!;

            return (
              <div key={group.id} style={{ marginTop: 20 }}>
                {/* 分组标题 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 18, fontWeight: 700, color: T.text1 }}>
                      {group.groupName}
                      <span style={{ fontSize: 16, fontWeight: 400, color: T.text2, marginLeft: 6 }}>
                        （任选{group.maxSelect === group.minSelect
                          ? `${group.minSelect}款`
                          : `${group.minSelect}-${group.maxSelect}款`}）
                      </span>
                    </div>
                  </div>
                  {/* 已选计数 */}
                  <div style={{
                    padding: '4px 12px',
                    borderRadius: 20,
                    background: progress.done
                      ? 'rgba(15,110,86,0.1)'
                      : selectedIds.length > 0
                        ? 'rgba(255,107,53,0.1)'
                        : T.bg2,
                    border: `1px solid ${progress.done ? T.success : selectedIds.length > 0 ? T.primary : T.border}`,
                    fontSize: 16,
                    fontWeight: 600,
                    color: progress.done ? T.success : selectedIds.length > 0 ? T.primary : T.text2,
                    whiteSpace: 'nowrap',
                  }}>
                    {selectedIds.length}/{group.minSelect}
                    {progress.done && ' ✓'}
                  </div>
                </div>

                {/* 菜品网格 */}
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
                  gap: 10,
                  marginBottom: 4,
                }}>
                  {group.items.map((item) => {
                    const isSelected = selectedIds.includes(item.id);
                    const canSelect = !isSelected && selectedIds.length < group.maxSelect;
                    return (
                      <DishCard
                        key={item.id}
                        item={item}
                        selected={isSelected}
                        selectable={canSelect}
                        onToggle={() => toggleItem(group, item.id)}
                      />
                    );
                  })}
                </div>

                {/* 已满提示 */}
                {selectedIds.length >= group.maxSelect && (
                  <div style={{ fontSize: 16, color: T.text2, marginTop: 6, textAlign: 'center' }}>
                    已选满 {group.maxSelect} 款
                  </div>
                )}
              </div>
            );
          })}

          {/* 底部安全间距 */}
          <div style={{ height: 16 }} />
        </div>

        {/* ─ 底部进度条 + 确认按钮 ─ */}
        <div style={{
          flexShrink: 0,
          borderTop: `1px solid ${T.border}`,
          padding: '12px 20px 16px',
          paddingBottom: `calc(16px + env(safe-area-inset-bottom, 0px))`,
          background: T.bg1,
        }}>
          {/* 分组完成进度 */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
            {groupProgress.map((p) => (
              <div key={p.groupId} style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '6px 14px',
                borderRadius: 20,
                background: p.done ? 'rgba(15,110,86,0.1)' : T.bg2,
                border: `1px solid ${p.done ? T.success : T.border}`,
                fontSize: 16,
                color: p.done ? T.success : T.text2,
                minHeight: T.tapMin,
              }}>
                <span style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: p.done ? T.success : T.border,
                  flexShrink: 0,
                }} />
                {p.groupName}
                <span style={{ fontWeight: 600 }}>
                  {p.selected}/{p.min}
                </span>
                {!p.required && (
                  <span style={{ fontSize: 14, color: '#B4B2A9' }}>可选</span>
                )}
              </div>
            ))}
          </div>

          {/* 错误提示 */}
          {error && (
            <div style={{
              padding: '10px 16px',
              borderRadius: 10,
              background: 'rgba(163,45,45,0.08)',
              border: `1px solid ${T.danger}`,
              fontSize: 16,
              color: T.danger,
              marginBottom: 12,
            }}>
              {error}
            </div>
          )}

          {/* 操作按钮 */}
          <div style={{ display: 'flex', gap: 12 }}>
            <TXButton
              variant="ghost"
              onPress={handleClose}
              style={{ minWidth: 100 }}
            >
              取消
            </TXButton>
            <TXButton
              variant="primary"
              large={true}
              fullWidth={true}
              disabled={!allRequiredDone}
              loading={submitting}
              onPress={handleConfirm}
            >
              {allRequiredDone
                ? `确认套餐 ${fen2yuan(combo.comboPriceFen)}`
                : `还需选择 ${groupProgress.filter((p) => p.required && !p.done).length} 组`}
            </TXButton>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
