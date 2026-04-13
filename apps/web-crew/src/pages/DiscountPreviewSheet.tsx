/**
 * 结账折扣预览 Sheet — 服务员端 PWA
 *
 * 功能：
 *   - 底部弹出 Sheet（translateY 动画，移动端友好）
 *   - 展示多优惠叠加步骤（before → after → 节省）
 *   - 绿色高亮最终节省总额
 *   - 有互斥冲突时展示"已自动为您选择最优组合"提示
 *   - 确认按钮触发 checkout-with-discounts 接口
 *
 * 设计规范（Store-Crew 深色主题）：
 *   bg        = #0B1A20
 *   card      = #112228
 *   accent    = #FF6B35
 *   success   = #0F6E56 / 亮绿 #27AE7A
 *   min font  = 16px
 *   热区      ≥ 48px
 */
import { useState, useEffect, useCallback } from 'react';
import { formatPrice } from '@tx-ds/utils';

// ─── 类型 ───────────────────────────────────────────────────────────────────

export interface DiscountInputItem {
  type: 'member_discount' | 'platform_coupon' | 'manual_discount' | 'full_reduction';
  member_id?: string;
  rate?: number;
  coupon_id?: string;
  deduct_fen?: number;
  condition_fen?: number;
  description?: string;
}

export interface DiscountStep {
  type: string;
  before: number;
  after: number;
  saved: number;
  description: string;
}

export interface ConflictInfo {
  type_a?: string;
  type_b?: string;
  reason?: string;
  excluded_types?: string[];
  message?: string;
}

export interface DiscountCalculateResult {
  base_amount_fen: number;
  applied_steps: DiscountStep[];
  total_saved_fen: number;
  final_amount_fen: number;
  conflicts: ConflictInfo[];
  log_id: string | null;
}

export interface DiscountPreviewSheetProps {
  visible: boolean;
  orderId: string;
  baseAmountFen: number;
  discounts: DiscountInputItem[];
  storeId?: string;
  payMethod: string;
  idempotencyKey?: string;
  onClose: () => void;
  onPaySuccess: (result: { discount: DiscountCalculateResult; payment: unknown }) => void;
}

// ─── 工具函数 ────────────────────────────────────────────────────────────────

/** @deprecated Use formatPrice from @tx-ds/utils */
function fenToYuan(fen: number): string {
  return formatPrice(fen).replace('¥', '');
}

function typeLabel(type: string): string {
  const map: Record<string, string> = {
    member_discount: '会员折扣',
    platform_coupon: '平台券',
    manual_discount: '手动折扣',
    full_reduction: '满减优惠',
  };
  return map[type] ?? type;
}

function typeIcon(type: string): string {
  const map: Record<string, string> = {
    member_discount: '★',
    platform_coupon: '◈',
    manual_discount: '✎',
    full_reduction: '◑',
  };
  return map[type] ?? '●';
}

function getTenantId(): string {
  return (window as unknown as Record<string, string>).__TENANT_ID__ ?? '';
}

// ─── 子组件：单行折扣步骤 ────────────────────────────────────────────────────

function DiscountStepRow({
  step,
  isLast,
}: {
  step: DiscountStep;
  isLast: boolean;
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 12,
        paddingBottom: isLast ? 0 : 20,
        position: 'relative',
      }}
    >
      {/* 竖线连接器 */}
      {!isLast && (
        <div
          style={{
            position: 'absolute',
            left: 19,
            top: 40,
            bottom: 0,
            width: 2,
            background: '#1E3040',
          }}
        />
      )}

      {/* 图标圆圈 */}
      <div
        style={{
          width: 40,
          height: 40,
          borderRadius: '50%',
          background: '#1E3040',
          border: '2px solid #FF6B35',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 16,
          color: '#FF6B35',
          flexShrink: 0,
          fontWeight: 700,
        }}
      >
        {typeIcon(step.type)}
      </div>

      {/* 内容 */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {/* 类型标签 + 描述 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
          <span
            style={{
              background: '#1E3040',
              borderRadius: 6,
              padding: '2px 10px',
              fontSize: 13,
              color: '#9DB4B2',
              fontWeight: 600,
              flexShrink: 0,
            }}
          >
            {typeLabel(step.type)}
          </span>
          <span
            style={{
              fontSize: 16,
              color: '#E0EEF0',
              fontWeight: 600,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {step.description}
          </span>
        </div>

        {/* 金额变化行 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 16, color: '#9DB4B2', textDecoration: 'line-through' }}>
            ¥{fenToYuan(step.before)}
          </span>
          <span style={{ fontSize: 18, color: '#FF6B35' }}>→</span>
          <span style={{ fontSize: 20, color: '#FFFFFF', fontWeight: 700 }}>
            ¥{fenToYuan(step.after)}
          </span>
          <span
            style={{
              marginLeft: 'auto',
              fontSize: 16,
              color: '#27AE7A',
              fontWeight: 700,
              background: 'rgba(15,110,86,0.18)',
              borderRadius: 8,
              padding: '2px 10px',
            }}
          >
            省¥{fenToYuan(step.saved)}
          </span>
        </div>
      </div>
    </div>
  );
}

// ─── 子组件：互斥冲突提示条 ──────────────────────────────────────────────────

function ConflictBanner({ conflicts }: { conflicts: ConflictInfo[] }) {
  if (!conflicts.length) return null;

  // 取出最有意义的一条提示
  const mainMsg =
    conflicts.find((c) => c.message)?.message ??
    conflicts.find((c) => c.reason)?.reason ??
    '已自动为您选择最优优惠组合';

  return (
    <div
      style={{
        background: 'rgba(186,117,23,0.15)',
        border: '1px solid rgba(186,117,23,0.4)',
        borderRadius: 10,
        padding: '12px 16px',
        marginBottom: 20,
        display: 'flex',
        alignItems: 'flex-start',
        gap: 10,
      }}
    >
      <span style={{ fontSize: 20, flexShrink: 0 }}>⚡</span>
      <div>
        <div style={{ fontSize: 16, color: '#F0C060', fontWeight: 700, marginBottom: 4 }}>
          优惠冲突，智能裁决
        </div>
        <div style={{ fontSize: 16, color: '#D4A840', lineHeight: 1.5 }}>{mainMsg}</div>
        {conflicts
          .filter((c) => c.excluded_types && c.excluded_types.length > 0)
          .map((c, i) => (
            <div key={i} style={{ fontSize: 14, color: '#9DB4B2', marginTop: 4 }}>
              已排除：{c.excluded_types!.map(typeLabel).join('、')}
            </div>
          ))}
      </div>
    </div>
  );
}

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export default function DiscountPreviewSheet({
  visible,
  orderId,
  baseAmountFen,
  discounts,
  storeId,
  payMethod,
  idempotencyKey,
  onClose,
  onPaySuccess,
}: DiscountPreviewSheetProps) {
  const [calcResult, setCalcResult] = useState<DiscountCalculateResult | null>(null);
  const [calcLoading, setCalcLoading] = useState(false);
  const [calcError, setCalcError] = useState('');

  const [paying, setPaying] = useState(false);
  const [payError, setPayError] = useState('');

  // 动画控制：先让 DOM 出现，再 transition 到 0%
  const [mounted, setMounted] = useState(false);
  const [slideIn, setSlideIn] = useState(false);

  // ── 打开/关闭动画 ──
  useEffect(() => {
    if (visible) {
      setMounted(true);
      // 下一帧触发 transition
      requestAnimationFrame(() => {
        requestAnimationFrame(() => setSlideIn(true));
      });
    } else {
      setSlideIn(false);
      const t = setTimeout(() => setMounted(false), 320);
      return () => clearTimeout(t);
    }
  }, [visible]);

  // ── 打开时调用折扣计算接口 ──
  const fetchCalcResult = useCallback(async () => {
    if (!visible || !discounts.length) {
      // 无优惠，用默认值
      setCalcResult({
        base_amount_fen: baseAmountFen,
        applied_steps: [],
        total_saved_fen: 0,
        final_amount_fen: baseAmountFen,
        conflicts: [],
        log_id: null,
      });
      return;
    }
    setCalcLoading(true);
    setCalcError('');
    try {
      const res = await fetch('/api/v1/discount/calculate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Tenant-ID': getTenantId(),
        },
        body: JSON.stringify({
          order_id: orderId,
          base_amount_fen: baseAmountFen,
          discounts,
          store_id: storeId,
        }),
      });
      const json = await res.json();
      if (json.ok && json.data) {
        setCalcResult(json.data);
      } else {
        setCalcError(json.error?.message ?? '优惠计算失败');
      }
    } catch {
      setCalcError('网络异常，无法计算优惠');
    } finally {
      setCalcLoading(false);
    }
  }, [visible, orderId, baseAmountFen, discounts, storeId]);

  useEffect(() => {
    if (visible) {
      fetchCalcResult();
    }
  }, [visible, fetchCalcResult]);

  // ── 确认支付 ──
  async function handleConfirmPay() {
    if (paying) return;
    setPaying(true);
    setPayError('');
    try {
      const res = await fetch(`/api/v1/orders/${orderId}/checkout-with-discounts`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Tenant-ID': getTenantId(),
        },
        body: JSON.stringify({
          method: payMethod,
          base_amount_fen: baseAmountFen,
          discounts,
          store_id: storeId,
          idempotency_key: idempotencyKey,
        }),
      });
      const json = await res.json();
      if (json.ok && json.data) {
        onPaySuccess(json.data);
      } else {
        setPayError(json.error?.message ?? '支付失败，请重试');
      }
    } catch {
      setPayError('网络异常，请重试');
    } finally {
      setPaying(false);
    }
  }

  if (!mounted) return null;

  const result = calcResult;
  const hasConflicts = (result?.conflicts ?? []).length > 0;
  const hasSteps = (result?.applied_steps ?? []).length > 0;
  const finalFen = result?.final_amount_fen ?? baseAmountFen;
  const totalSaved = result?.total_saved_fen ?? 0;

  return (
    <>
      {/* ── 遮罩 ── */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(0,0,0,0.65)',
          zIndex: 900,
          opacity: slideIn ? 1 : 0,
          transition: 'opacity 300ms ease',
        }}
      />

      {/* ── Sheet 主体 ── */}
      <div
        style={{
          position: 'fixed',
          left: 0,
          right: 0,
          bottom: 0,
          zIndex: 901,
          background: '#0B1A20',
          borderRadius: '20px 20px 0 0',
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
          transform: slideIn ? 'translateY(0)' : 'translateY(100%)',
          transition: 'transform 300ms ease-out',
          boxShadow: '0 -8px 32px rgba(0,0,0,0.5)',
        }}
      >
        {/* ── 拖动手柄 ── */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'center',
            paddingTop: 14,
            paddingBottom: 6,
            flexShrink: 0,
          }}
        >
          <div
            style={{
              width: 48,
              height: 4,
              background: '#2A3E4A',
              borderRadius: 2,
            }}
          />
        </div>

        {/* ── 顶部标题行 ── */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            padding: '8px 20px 16px',
            flexShrink: 0,
            borderBottom: '1px solid #1A2E3A',
          }}
        >
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: '#FFFFFF' }}>
              优惠明细
            </div>
            <div style={{ fontSize: 16, color: '#9DB4B2', marginTop: 4 }}>
              原价 ¥{fenToYuan(baseAmountFen)}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              minWidth: 48,
              minHeight: 48,
              background: '#1A2E3A',
              border: 'none',
              borderRadius: 12,
              color: '#9DB4B2',
              fontSize: 20,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            ✕
          </button>
        </div>

        {/* ── 可滚动内容区 ── */}
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            WebkitOverflowScrolling: 'touch' as React.CSSProperties['WebkitOverflowScrolling'],
            padding: '20px 20px 0',
          }}
        >
          {calcLoading ? (
            // 加载态
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 16,
                padding: '40px 0',
                color: '#9DB4B2',
                fontSize: 16,
              }}
            >
              <div
                style={{
                  width: 40,
                  height: 40,
                  border: '3px solid #1A2E3A',
                  borderTopColor: '#FF6B35',
                  borderRadius: '50%',
                  animation: 'spin 0.8s linear infinite',
                }}
              />
              正在计算最优优惠组合…
            </div>
          ) : calcError ? (
            // 错误态
            <div
              style={{
                background: 'rgba(163,45,45,0.15)',
                border: '1px solid rgba(163,45,45,0.4)',
                borderRadius: 12,
                padding: '16px 20px',
                fontSize: 16,
                color: '#FF8080',
                textAlign: 'center',
              }}
            >
              {calcError}
              <br />
              <button
                onClick={fetchCalcResult}
                style={{
                  marginTop: 12,
                  minHeight: 48,
                  padding: '0 24px',
                  background: '#FF6B35',
                  border: 'none',
                  borderRadius: 10,
                  color: '#fff',
                  fontSize: 16,
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
              >
                重试
              </button>
            </div>
          ) : (
            <>
              {/* 冲突提示 */}
              {hasConflicts && <ConflictBanner conflicts={result!.conflicts} />}

              {/* 无优惠空态 */}
              {!hasSteps && !calcLoading && (
                <div
                  style={{
                    textAlign: 'center',
                    padding: '32px 0',
                    color: '#5F7A85',
                    fontSize: 16,
                  }}
                >
                  暂无可用优惠
                </div>
              )}

              {/* 折扣步骤列表 */}
              {hasSteps && (
                <div style={{ marginBottom: 24 }}>
                  {result!.applied_steps.map((step, i) => (
                    <DiscountStepRow
                      key={`${step.type}-${i}`}
                      step={step}
                      isLast={i === result!.applied_steps.length - 1}
                    />
                  ))}
                </div>
              )}

              {/* 节省总额高亮区 */}
              {totalSaved > 0 && (
                <div
                  style={{
                    background: 'rgba(15,110,86,0.15)',
                    border: '1px solid rgba(39,174,122,0.4)',
                    borderRadius: 14,
                    padding: '16px 20px',
                    marginBottom: 24,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                  }}
                >
                  <div>
                    <div style={{ fontSize: 16, color: '#27AE7A', fontWeight: 700 }}>
                      为您节省
                    </div>
                    <div style={{ fontSize: 13, color: '#6BA890', marginTop: 2 }}>
                      共 {result!.applied_steps.length} 项优惠叠加
                    </div>
                  </div>
                  <div
                    style={{
                      fontSize: 32,
                      fontWeight: 800,
                      color: '#27AE7A',
                      fontVariantNumeric: 'tabular-nums',
                    }}
                  >
                    ¥{fenToYuan(totalSaved)}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* ── 底部：最终金额 + 确认按钮 ── */}
        <div
          style={{
            flexShrink: 0,
            padding: '16px 20px',
            borderTop: '1px solid #1A2E3A',
            background: '#0B1A20',
            paddingBottom: 'calc(16px + env(safe-area-inset-bottom, 0px))',
          }}
        >
          {/* 金额汇总行 */}
          <div
            style={{
              display: 'flex',
              alignItems: 'flex-end',
              justifyContent: 'space-between',
              marginBottom: 16,
            }}
          >
            <div>
              <div style={{ fontSize: 16, color: '#9DB4B2' }}>应收金额</div>
              {totalSaved > 0 && (
                <div style={{ fontSize: 14, color: '#27AE7A', marginTop: 2 }}>
                  已优惠 ¥{fenToYuan(totalSaved)}
                </div>
              )}
            </div>
            <div
              style={{
                fontSize: 40,
                fontWeight: 800,
                color: '#FF6B35',
                lineHeight: 1,
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              ¥{fenToYuan(finalFen)}
            </div>
          </div>

          {/* 支付错误提示 */}
          {payError && (
            <div
              style={{
                background: 'rgba(163,45,45,0.15)',
                borderRadius: 8,
                padding: '10px 14px',
                fontSize: 16,
                color: '#FF8080',
                marginBottom: 12,
                textAlign: 'center',
              }}
            >
              {payError}
            </div>
          )}

          {/* 确认收款按钮 */}
          <button
            disabled={paying || calcLoading}
            onClick={handleConfirmPay}
            style={{
              width: '100%',
              minHeight: 56,
              background: paying || calcLoading ? '#2A3E4A' : '#FF6B35',
              border: 'none',
              borderRadius: 14,
              color: '#FFFFFF',
              fontSize: 20,
              fontWeight: 700,
              cursor: paying || calcLoading ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 10,
              transition: 'transform 200ms ease, background 200ms ease',
              transform: paying ? 'scale(0.97)' : 'scale(1)',
            }}
          >
            {paying ? (
              <>
                <div
                  style={{
                    width: 22,
                    height: 22,
                    border: '3px solid rgba(255,255,255,0.3)',
                    borderTopColor: '#fff',
                    borderRadius: '50%',
                    animation: 'spin 0.8s linear infinite',
                  }}
                />
                处理中…
              </>
            ) : (
              `确认收款 ¥${fenToYuan(finalFen)}`
            )}
          </button>
        </div>
      </div>

      {/* ── 内联 keyframes ── */}
      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
      `}</style>
    </>
  );
}
