/**
 * ComboSelectionSheet — 套餐N选M底部弹层
 *
 * 支持:
 *   - max_select=1: 单选（Radio样式，互斥）
 *   - max_select>1: 多选（Checkbox样式），超限时其余项 disabled
 *   - is_required=true: 必须满足 min_select，否则底部按钮 disabled
 *   - is_required=false: 0选也允许
 *   - is_default=true 且分组只有1项: 自动选中（固定项）
 *   - 加价菜品显示 +¥XX
 *   - 合计 = combo.price_fen + 所有已选 extra_price_fen 之和
 */
import { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import type { ComboDetail, ComboGroup, ComboSelection } from '../api/comboApi';

// ─── Design Tokens ───
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B35',
  accentBg: '#FF6B3522',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
  green: '#22c55e',
  danger: '#ef4444',
  disabled: '#334155',
};

// ─── 辅助函数 ───
function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

// ─── Props ───
interface ComboSelectionSheetProps {
  combo: ComboDetail;
  onConfirm: (selections: ComboSelection[], totalFen: number) => void;
  onClose: () => void;
}

// ─── 分组选择状态 ─── key: group_id, value: item_id[]
type SelectionMap = Record<string, string[]>;

function initSelections(groups: ComboGroup[]): SelectionMap {
  const map: SelectionMap = {};
  for (const group of groups) {
    // 若分组只有1个 is_default=true 的菜品（固定项），自动选中
    const defaults = group.items.filter(i => i.is_default);
    if (defaults.length > 0 && group.items.length === 1 && defaults.length === 1) {
      map[group.group_id] = [defaults[0].item_id];
    } else {
      map[group.group_id] = [];
    }
  }
  return map;
}

// ─── 单个分组 Section 组件 ───
interface GroupSectionProps {
  group: ComboGroup;
  selectedItemIds: string[];
  onToggle: (groupId: string, itemId: string) => void;
  collapsed: boolean;
  onToggleCollapse: (groupId: string) => void;
  sectionRef?: React.RefObject<HTMLDivElement>;
}

function GroupSection({
  group,
  selectedItemIds,
  onToggle,
  collapsed,
  onToggleCollapse,
  sectionRef,
}: GroupSectionProps) {
  const isFixed = group.items.length === 1 && group.items[0].is_default;
  const selectedCount = selectedItemIds.length;
  const isComplete = selectedCount >= group.min_select;

  // 超选提示：当 max_select > 0 且已选满时显示（仅在当前分组已满时提示）
  const [showOverLimitHint, setShowOverLimitHint] = useState(false);
  const hintTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const headerBadge = isFixed
    ? { text: '已含 ✓', color: C.green }
    : isComplete
      ? { text: `已选${selectedCount}/${group.max_select} ✓`, color: C.green }
      : { text: group.is_required ? '必选 ✗' : `可选`, color: group.is_required ? C.danger : C.muted };

  const handleItemClick = (itemId: string, isDisabledByLimit: boolean, isDisabled: boolean) => {
    if (isDisabled) return;
    if (isDisabledByLimit) {
      // 超选：显示红色提示 2 秒
      setShowOverLimitHint(true);
      if (hintTimerRef.current) clearTimeout(hintTimerRef.current);
      hintTimerRef.current = setTimeout(() => setShowOverLimitHint(false), 2000);
      return;
    }
    onToggle(group.group_id, itemId);
  };

  // 清理定时器
  useEffect(() => {
    return () => {
      if (hintTimerRef.current) clearTimeout(hintTimerRef.current);
    };
  }, []);

  return (
    <div ref={sectionRef} style={{ marginBottom: 4 }}>
      {/* 分组标题（可点击折叠，固定项除外） */}
      <div
        onClick={() => !isFixed && onToggleCollapse(group.group_id)}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '10px 16px', borderTop: `1px solid ${C.border}`,
          background: C.card,
          cursor: isFixed ? 'default' : 'pointer',
        }}
      >
        <span style={{ fontSize: 16, fontWeight: 700, color: C.text }}>
          {group.group_name}
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 14, color: headerBadge.color, fontWeight: 600 }}>
            {headerBadge.text}
          </span>
          {!isFixed && (
            <span style={{ fontSize: 12, color: C.muted }}>
              {collapsed ? '▶' : '▼'}
            </span>
          )}
        </div>
      </div>

      {/* 超选提示（分组标题下方，短暂显示） */}
      {showOverLimitHint && (
        <div style={{
          padding: '6px 16px',
          background: '#ef444422',
          color: C.danger,
          fontSize: 13,
          fontWeight: 500,
        }}>
          最多选 {group.max_select} 项
        </div>
      )}

      {/* 菜品列表（可折叠） */}
      {!collapsed && (
        <div>
          {group.items.map(item => {
            const isSelected = selectedItemIds.includes(item.item_id);
            const isAtMax = selectedCount >= group.max_select && !isSelected;
            const isDisabledByLimit = !isFixed && isAtMax && !item.sold_out;
            const isDisabled = item.sold_out || isFixed;

            return (
              <button
                key={item.item_id}
                onClick={() => handleItemClick(item.item_id, isDisabledByLimit, isDisabled)}
                disabled={isDisabled && !isFixed}
                style={{
                  display: 'flex', alignItems: 'center', width: '100%',
                  padding: '14px 16px', minHeight: 52,
                  background: isSelected ? C.accentBg : 'transparent',
                  border: 'none',
                  borderLeft: isSelected ? `3px solid ${C.accent}` : '3px solid transparent',
                  borderBottom: `1px solid ${C.border}`,
                  cursor: isFixed || item.sold_out ? 'default' : 'pointer',
                  opacity: item.sold_out ? 0.4 : isDisabledByLimit ? 0.5 : 1,
                  textAlign: 'left',
                }}
              >
                {/* 选中指示器（固定项显示勾） */}
                <div style={{
                  width: 22, height: 22, borderRadius: group.max_select === 1 ? 11 : 4,
                  border: `2px solid ${isSelected ? C.accent : isDisabledByLimit ? C.disabled : C.muted}`,
                  background: isSelected ? C.accent : 'transparent',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  flexShrink: 0, marginRight: 12,
                  fontSize: 13, color: C.white, fontWeight: 700,
                }}>
                  {isSelected && (group.max_select === 1 ? '●' : '✓')}
                </div>

                {/* 菜品名 */}
                <span style={{
                  flex: 1, fontSize: 16, color: C.text,
                  fontWeight: isSelected ? 600 : 400,
                }}>
                  {item.dish_name}
                  {item.sold_out && (
                    <span style={{ fontSize: 14, color: C.danger, marginLeft: 6 }}>已沽清</span>
                  )}
                </span>

                {/* 加价或免费 */}
                <span style={{
                  fontSize: 15,
                  color: item.extra_price_fen > 0 ? C.accent : C.muted,
                  fontWeight: item.extra_price_fen > 0 ? 600 : 400,
                  marginLeft: 8,
                }}>
                  {item.extra_price_fen > 0
                    ? `+¥${fenToYuan(item.extra_price_fen)}`
                    : '¥0'}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── 主组件 ───
export function ComboSelectionSheet({ combo, onConfirm, onClose }: ComboSelectionSheetProps) {
  const [selections, setSelections] = useState<SelectionMap>(() =>
    initSelections(combo.groups)
  );

  // 折叠状态：group_id -> collapsed
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(() => {
    const map: Record<string, boolean> = {};
    for (const group of combo.groups) {
      map[group.group_id] = false; // 默认全部展开
    }
    return map;
  });

  // 各分组的 DOM ref（用于 scroll-to-next）
  const groupRefs = useRef<Record<string, React.RefObject<HTMLDivElement>>>({});
  for (const group of combo.groups) {
    if (!groupRefs.current[group.group_id]) {
      // eslint-disable-next-line react-hooks/exhaustive-deps
      groupRefs.current[group.group_id] = { current: null } as React.RefObject<HTMLDivElement>;
    }
  }

  const handleToggleCollapse = useCallback((groupId: string) => {
    setCollapsed(prev => ({ ...prev, [groupId]: !prev[groupId] }));
  }, []);

  // 切换选中项
  const handleToggle = useCallback((groupId: string, itemId: string) => {
    const group = combo.groups.find(g => g.group_id === groupId);
    if (!group) return;

    setSelections(prev => {
      const current = prev[groupId] ?? [];

      if (group.max_select === 1) {
        // 单选：切换（已选则取消，否则替换）
        const newSelected = current.includes(itemId) ? [] : [itemId];

        // 自动折叠：max_select=1 的分组，选中后 300ms 折叠并 scroll 到下一分组
        if (newSelected.length === 1) {
          setTimeout(() => {
            setCollapsed(c => ({ ...c, [groupId]: true }));
            // scroll 到下一个分组
            const groupIndex = combo.groups.findIndex(g => g.group_id === groupId);
            const nextGroup = combo.groups[groupIndex + 1];
            if (nextGroup) {
              const nextRef = groupRefs.current[nextGroup.group_id];
              nextRef?.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
          }, 300);
        }

        return { ...prev, [groupId]: newSelected };
      } else {
        // 多选
        if (current.includes(itemId)) {
          // 取消选中
          return { ...prev, [groupId]: current.filter(id => id !== itemId) };
        } else if (current.length < group.max_select) {
          // 加入
          return { ...prev, [groupId]: [...current, itemId] };
        }
        // 已达上限，忽略（GroupSection 内的 handleItemClick 会显示提示）
        return prev;
      }
    });
  }, [combo.groups]);

  // 验证：所有 is_required=true 的分组需满足 min_select
  const validation = useMemo(() => {
    for (const group of combo.groups) {
      if (!group.is_required) continue;
      const count = (selections[group.group_id] ?? []).length;
      if (count < group.min_select) {
        return { valid: false, message: `请完成「${group.group_name}」选择` };
      }
    }
    return { valid: true, message: '' };
  }, [combo.groups, selections]);

  // 计算额外加价总和
  const extraFen = useMemo(() => {
    let total = 0;
    for (const group of combo.groups) {
      const selectedIds = selections[group.group_id] ?? [];
      for (const item of group.items) {
        if (selectedIds.includes(item.item_id)) {
          total += item.extra_price_fen;
        }
      }
    }
    return total;
  }, [combo.groups, selections]);

  const totalFen = combo.price_fen + extraFen;

  // 构建确认数据
  const handleConfirm = useCallback(() => {
    if (!validation.valid) return;

    const result: ComboSelection[] = combo.groups
      .filter(group => {
        const ids = selections[group.group_id] ?? [];
        return ids.length > 0;
      })
      .map(group => {
        const selectedIds = selections[group.group_id] ?? [];
        const selectedItems = group.items
          .filter(item => selectedIds.includes(item.item_id))
          .map(item => ({
            dish_id: item.dish_id,
            dish_name: item.dish_name,
            extra_price_fen: item.extra_price_fen,
          }));
        return {
          group_id: group.group_id,
          group_name: group.group_name,
          selected_items: selectedItems,
        };
      });

    onConfirm(result, totalFen);
  }, [combo.groups, selections, validation.valid, totalFen, onConfirm]);

  return (
    <>
      {/* 遮罩 */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.6)', zIndex: 300,
        }}
      />

      {/* 弹层主体 */}
      <div
        style={{
          position: 'fixed', left: 0, right: 0, bottom: 0,
          height: '75vh', zIndex: 301,
          background: C.bg, borderRadius: '16px 16px 0 0',
          display: 'flex', flexDirection: 'column',
          overflow: 'hidden',
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* ── 顶部固定头部 ── */}
        <div style={{
          flexShrink: 0,
          padding: '16px 16px 12px',
          background: C.card,
          borderBottom: `1px solid ${C.border}`,
        }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
            <div>
              <div style={{ fontSize: 20, fontWeight: 700, color: C.white, marginBottom: 4 }}>
                {combo.combo_name}
              </div>
              <div style={{ fontSize: 16, color: C.muted }}>
                基础价 <span style={{ color: C.accent, fontWeight: 700 }}>
                  ¥{fenToYuan(combo.price_fen)}
                </span>
              </div>
              {combo.description && (
                <div style={{ fontSize: 14, color: C.muted, marginTop: 4 }}>
                  {combo.description}
                </div>
              )}
            </div>
            <button
              onClick={onClose}
              style={{
                width: 48, height: 48, borderRadius: 24,
                background: 'transparent', border: 'none',
                color: C.muted, fontSize: 24, cursor: 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                flexShrink: 0,
              }}
              aria-label="关闭"
            >
              ×
            </button>
          </div>
        </div>

        {/* ── 中间可滚动内容区 ── */}
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            WebkitOverflowScrolling: 'touch' as React.CSSProperties['WebkitOverflowScrolling'],
          }}
        >
          {combo.groups.map((group) => (
            <GroupSection
              key={group.group_id}
              group={group}
              selectedItemIds={selections[group.group_id] ?? []}
              onToggle={handleToggle}
              collapsed={collapsed[group.group_id] ?? false}
              onToggleCollapse={handleToggleCollapse}
              sectionRef={groupRefs.current[group.group_id]}
            />
          ))}
          {/* 底部安全间距 */}
          <div style={{ height: 16 }} />
        </div>

        {/* ── 底部固定操作栏 ── */}
        <div style={{
          flexShrink: 0,
          padding: '12px 16px',
          background: C.card,
          borderTop: `1px solid ${C.border}`,
        }}>
          {/* 价格摘要 */}
          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            marginBottom: 10,
          }}>
            <span style={{ fontSize: 15, color: C.muted }}>
              {extraFen > 0
                ? `已加价: +¥${fenToYuan(extraFen)}`
                : '无加价'}
            </span>
            <span style={{ fontSize: 17, fontWeight: 700, color: C.white }}>
              合计: <span style={{ color: C.accent }}>¥{fenToYuan(totalFen)}</span>
            </span>
          </div>

          {/* 确认按钮 */}
          <button
            onClick={handleConfirm}
            disabled={!validation.valid}
            style={{
              width: '100%', minHeight: 56,
              borderRadius: 14, border: 'none',
              background: validation.valid ? C.accent : C.disabled,
              color: C.white, fontSize: 18, fontWeight: 700,
              cursor: validation.valid ? 'pointer' : 'not-allowed',
              transition: 'background 0.2s',
            }}
          >
            {validation.valid
              ? (extraFen > 0
                  ? `确认 +¥${fenToYuan(extraFen)}`
                  : `确认加入 ¥${fenToYuan(totalFen)}`)
              : '请完成必选项'}
          </button>
        </div>
      </div>
    </>
  );
}
