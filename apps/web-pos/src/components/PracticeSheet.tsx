/**
 * PracticeSheet — 菜品口味做法选择底部弹层
 *
 * 对接后端：tx-trade dish_practice_service（4大分类 × 8种做法）
 *   - GET /api/v1/dishes/{dishId}/practices  → 菜品专属做法
 *   - GET /api/v1/practices/templates         → 通用模板（fallback）
 *
 * 分类选择规则：
 *   - spicy（辣度）：单选（radio）
 *   - sweetness（甜度）：单选（radio）
 *   - avoid（忌口）：多选（checkbox）
 *   - extra（加料）：多选（checkbox），显示加价
 *
 * POS 触控规范：
 *   - 所有可点击元素 ≥ 48px 高度
 *   - 确认按钮 72px 高
 *   - 最小字体 16px
 *   - 弹层从底部滑出（translateY 300ms）
 *   - 按钮按下 scale(0.97) + 200ms
 */

import { useState, useEffect, useCallback } from 'react';
import ReactDOM from 'react-dom';
import { getMacMiniUrl } from '../bridge/TXBridge';

// ─── Types ───────────────────────────────────────────────────────────────────

/** 单个做法选项（与后端 DishPracticeStore 结构对齐） */
export interface PracticeItem {
  practice_id?: string;
  template_id?: string;
  name: string;
  category: string;
  category_label: string;
  additional_price_fen: number;
  materials: { name: string; amount: string }[];
}

/** 选中的做法结果（传给父组件） */
export interface PracticeSelection {
  practices: {
    practice_id: string;
    name: string;
    additional_price_fen: number;
    materials: { name: string; amount: string }[];
  }[];
  total_extra_price_fen: number;
}

export interface PracticeSheetProps {
  visible: boolean;
  dishId: string;
  dishName: string;
  onConfirm: (selection: PracticeSelection) => void;
  onClose: () => void;
}

// ─── Constants ───────────────────────────────────────────────────────────────

const ACCENT = '#FF6B2C';
const BG_OVERLAY = 'rgba(0,0,0,0.55)';
const BG_SHEET = '#0F1D24';
const BG_CHIP = '#1A2A33';
const BG_CHIP_ACTIVE = 'rgba(255,107,44,0.15)';
const BORDER_CHIP = '#2A3A44';
const BORDER_ACTIVE = ACCENT;
const TEXT_PRIMARY = '#FFFFFF';
const TEXT_SECONDARY = '#8A9AA4';
const TEXT_PRICE = ACCENT;

/** 单选分类（辣度、甜度） */
const SINGLE_SELECT_CATEGORIES = new Set(['spicy', 'sweetness']);

/** 分类展示顺序 */
const CATEGORY_ORDER: string[] = ['spicy', 'sweetness', 'avoid', 'extra'];

// ─── Keyframes injection (once) ──────────────────────────────────────────────

const KEYFRAMES_ID = 'tx-practice-sheet-kf';
function ensureKeyframes(): void {
  if (document.getElementById(KEYFRAMES_ID)) return;
  const s = document.createElement('style');
  s.id = KEYFRAMES_ID;
  s.textContent = `
    @keyframes tx-practice-in  { from { transform: translateY(100%); } to { transform: translateY(0); } }
    @keyframes tx-practice-out { from { transform: translateY(0); }    to { transform: translateY(100%); } }
  `;
  document.head.appendChild(s);
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const fen2yuan = (fen: number): string => `¥${(fen / 100).toFixed(2)}`;

function getItemId(item: PracticeItem): string {
  return item.practice_id || item.template_id || `${item.category}-${item.name}`;
}

function groupByCategory(items: PracticeItem[]): Map<string, PracticeItem[]> {
  const grouped = new Map<string, PracticeItem[]>();
  for (const item of items) {
    const cat = item.category;
    if (!grouped.has(cat)) grouped.set(cat, []);
    grouped.get(cat)!.push(item);
  }
  // Sort by defined order, unknown categories go to end
  const sorted = new Map<string, PracticeItem[]>();
  for (const cat of CATEGORY_ORDER) {
    if (grouped.has(cat)) {
      sorted.set(cat, grouped.get(cat)!);
      grouped.delete(cat);
    }
  }
  // Append any remaining categories
  for (const [cat, items] of grouped) {
    sorted.set(cat, items);
  }
  return sorted;
}

// ─── Chip Component ──────────────────────────────────────────────────────────

interface ChipProps {
  label: string;
  priceFen: number;
  selected: boolean;
  onPress: () => void;
}

function Chip({ label, priceFen, selected, onPress }: ChipProps) {
  const [pressing, setPressing] = useState(false);

  return (
    <button
      type="button"
      role={undefined}
      onPointerDown={() => setPressing(true)}
      onPointerUp={() => { setPressing(false); onPress(); }}
      onPointerLeave={() => setPressing(false)}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 6,
        minHeight: 48,
        padding: '8px 18px',
        borderRadius: 10,
        border: `1.5px solid ${selected ? BORDER_ACTIVE : BORDER_CHIP}`,
        background: selected ? BG_CHIP_ACTIVE : BG_CHIP,
        color: selected ? TEXT_PRIMARY : TEXT_SECONDARY,
        fontSize: 17,
        fontWeight: selected ? 600 : 400,
        fontFamily: 'inherit',
        cursor: 'pointer',
        transform: pressing ? 'scale(0.97)' : 'scale(1)',
        transition: 'transform 200ms ease, border-color 150ms ease, background 150ms ease',
        userSelect: 'none',
        WebkitUserSelect: 'none',
        whiteSpace: 'nowrap',
      }}
    >
      <span>{label}</span>
      {priceFen > 0 && (
        <span style={{ fontSize: 15, color: TEXT_PRICE, fontWeight: 600 }}>
          +{fen2yuan(priceFen)}
        </span>
      )}
    </button>
  );
}

// ─── Main Component ──────────────────────────────────────────────────────────

export function PracticeSheet({
  visible,
  dishId,
  dishName,
  onConfirm,
  onClose,
}: PracticeSheetProps) {
  ensureKeyframes();

  const [practices, setPractices] = useState<PracticeItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [closing, setClosing] = useState(false);
  // category -> Set of selected item IDs
  const [selections, setSelections] = useState<Record<string, Set<string>>>({});

  const apiBase = import.meta.env.VITE_API_BASE_URL as string || getMacMiniUrl();
  const tenantId = import.meta.env.VITE_TENANT_ID as string || '';

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(tenantId ? { 'X-Tenant-ID': tenantId } : {}),
  };

  // ── Load practices on open ─────────────────────────────────────────────────

  const loadPractices = useCallback(async () => {
    setLoading(true);
    try {
      // Try dish-specific practices first
      const resp = await fetch(
        `${apiBase}/api/v1/dishes/${dishId}/practices`,
        { headers },
      );
      const json: { ok: boolean; data: PracticeItem[] } = await resp.json();

      if (json.ok && json.data && json.data.length > 0) {
        setPractices(json.data);
        return;
      }

      // Fallback: load templates
      const tplResp = await fetch(
        `${apiBase}/api/v1/practices/templates`,
        { headers },
      );
      const tplJson: { ok: boolean; data: PracticeItem[] } = await tplResp.json();

      if (tplJson.ok && tplJson.data) {
        setPractices(tplJson.data);
      }
    } catch (_networkErr: unknown) {
      // Offline: use empty — the sheet will show "暂无可选做法"
      setPractices([]);
    } finally {
      setLoading(false);
    }
  }, [apiBase, dishId, tenantId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (visible) {
      setSelections({});
      loadPractices();
    }
  }, [visible, loadPractices]);

  // ── Selection logic ────────────────────────────────────────────────────────

  const toggleItem = (category: string, itemId: string) => {
    setSelections((prev) => {
      const current = new Set(prev[category] ?? []);
      const isSingle = SINGLE_SELECT_CATEGORIES.has(category);

      if (current.has(itemId)) {
        // Deselect
        current.delete(itemId);
      } else if (isSingle) {
        // Single-select: replace
        return { ...prev, [category]: new Set([itemId]) };
      } else {
        // Multi-select: add
        current.add(itemId);
      }

      return { ...prev, [category]: new Set(current) };
    });
  };

  // ── Compute totals ─────────────────────────────────────────────────────────

  const selectedPractices: PracticeItem[] = [];
  for (const item of practices) {
    const id = getItemId(item);
    const catSelections = selections[item.category];
    if (catSelections && catSelections.has(id)) {
      selectedPractices.push(item);
    }
  }

  const totalExtraFen = selectedPractices.reduce(
    (sum, p) => sum + p.additional_price_fen,
    0,
  );

  // ── Confirm ────────────────────────────────────────────────────────────────

  const handleConfirm = () => {
    const result: PracticeSelection = {
      practices: selectedPractices.map((p) => ({
        practice_id: p.practice_id || p.template_id || '',
        name: p.name,
        additional_price_fen: p.additional_price_fen,
        materials: p.materials,
      })),
      total_extra_price_fen: totalExtraFen,
    };
    onConfirm(result);
    handleClose();
  };

  // ── Close animation ────────────────────────────────────────────────────────

  const handleClose = () => {
    setClosing(true);
    setTimeout(() => {
      setClosing(false);
      onClose();
    }, 300);
  };

  if (!visible && !closing) return null;

  // ── Group practices by category ────────────────────────────────────────────

  const grouped = groupByCategory(practices);

  // ── Render ─────────────────────────────────────────────────────────────────

  return ReactDOM.createPortal(
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'flex-end',
      }}
    >
      {/* Backdrop */}
      <div
        role="presentation"
        onClick={handleClose}
        style={{
          position: 'absolute',
          inset: 0,
          background: BG_OVERLAY,
          backdropFilter: 'blur(2px)',
          WebkitBackdropFilter: 'blur(2px)',
        }}
      />

      {/* Sheet */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${dishName} 口味做法选择`}
        style={{
          position: 'relative',
          maxHeight: '80vh',
          background: BG_SHEET,
          borderRadius: '20px 20px 0 0',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 -8px 32px rgba(0,0,0,0.3)',
          animation: `${closing ? 'tx-practice-out' : 'tx-practice-in'} 300ms ease-out both`,
          fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
          overflow: 'hidden',
          paddingBottom: 'env(safe-area-inset-bottom, 0px)',
        }}
      >
        {/* ─ Header ─ */}
        <div style={{ flexShrink: 0, padding: '16px 20px 12px' }}>
          {/* Drag handle */}
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 12 }}>
            <div style={{ width: 40, height: 4, borderRadius: 2, background: '#2A3A44' }} />
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ fontSize: 22, fontWeight: 700, color: TEXT_PRIMARY, lineHeight: 1.3 }}>
              {dishName}
            </div>
            <button
              type="button"
              onClick={handleClose}
              aria-label="关闭"
              style={{
                width: 36,
                height: 36,
                border: 'none',
                borderRadius: 8,
                background: BG_CHIP,
                color: TEXT_SECONDARY,
                fontSize: 18,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontFamily: 'inherit',
              }}
            >
              ✕
            </button>
          </div>
        </div>

        {/* ─ Scrollable content ─ */}
        <div style={{
          flex: 1,
          overflowY: 'auto',
          WebkitOverflowScrolling: 'touch',
          padding: '0 20px',
        }}>
          {loading && (
            <div style={{ textAlign: 'center', padding: '32px 0', color: TEXT_SECONDARY, fontSize: 17 }}>
              加载做法中...
            </div>
          )}

          {!loading && practices.length === 0 && (
            <div style={{ textAlign: 'center', padding: '32px 0', color: TEXT_SECONDARY, fontSize: 17 }}>
              暂无可选做法
            </div>
          )}

          {!loading && Array.from(grouped.entries()).map(([category, items]) => {
            const label = items[0]?.category_label || category;
            const isSingle = SINGLE_SELECT_CATEGORIES.has(category);
            const catSelections = selections[category] ?? new Set();

            return (
              <div key={category} style={{ marginBottom: 20 }}>
                {/* Category label */}
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  marginBottom: 10,
                }}>
                  <span style={{ fontSize: 18, fontWeight: 600, color: TEXT_PRIMARY }}>
                    {label}
                  </span>
                  <span style={{ fontSize: 14, color: TEXT_SECONDARY }}>
                    {isSingle ? '单选' : '可多选'}
                  </span>
                </div>

                {/* Chips */}
                <div style={{
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: 10,
                }}>
                  {items.map((item) => {
                    const id = getItemId(item);
                    return (
                      <Chip
                        key={id}
                        label={item.name}
                        priceFen={item.additional_price_fen}
                        selected={catSelections.has(id)}
                        onPress={() => toggleItem(category, id)}
                      />
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>

        {/* ─ Footer ─ */}
        <div style={{
          flexShrink: 0,
          padding: '12px 20px 16px',
          borderTop: '1px solid #1A2A33',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 16,
        }}>
          {/* Extra price summary */}
          <div style={{ minWidth: 0 }}>
            {totalExtraFen > 0 ? (
              <div style={{ fontSize: 17, color: TEXT_PRICE, fontWeight: 600 }}>
                加料 +{fen2yuan(totalExtraFen)}
              </div>
            ) : (
              <div style={{ fontSize: 17, color: TEXT_SECONDARY }}>
                {selectedPractices.length > 0
                  ? `已选 ${selectedPractices.length} 项`
                  : '未选择做法'}
              </div>
            )}
          </div>

          {/* Confirm button */}
          <ConfirmButton
            label="确认"
            onPress={handleConfirm}
          />
        </div>
      </div>
    </div>,
    document.body,
  );
}

// ─── Confirm Button ──────────────────────────────────────────────────────────

interface ConfirmButtonProps {
  label: string;
  onPress: () => void;
}

function ConfirmButton({ label, onPress }: ConfirmButtonProps) {
  const [pressing, setPressing] = useState(false);

  return (
    <button
      type="button"
      onPointerDown={() => setPressing(true)}
      onPointerUp={() => { setPressing(false); onPress(); }}
      onPointerLeave={() => setPressing(false)}
      style={{
        height: 72,
        minWidth: 140,
        padding: '0 32px',
        border: 'none',
        borderRadius: 12,
        background: ACCENT,
        color: '#fff',
        fontSize: 20,
        fontWeight: 700,
        fontFamily: 'inherit',
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        transform: pressing ? 'scale(0.97)' : 'scale(1)',
        transition: 'transform 200ms ease',
        userSelect: 'none',
        WebkitUserSelect: 'none',
        boxShadow: '0 4px 16px rgba(255,107,44,0.35)',
        flexShrink: 0,
      }}
    >
      {label}
    </button>
  );
}
