/**
 * 结算页面 — 对接 tx-trade 支付 API + 打印
 *
 * 2026-04-02 新增：折扣 AI 分析抽屉（DiscountPreviewSheet）
 *   - 点击"折扣"按钮 → 打开底部抽屉 → 调用 tx-brain 折扣分析 API
 *   - allow/warn 决策后收银员可确认，reject 时禁止执行
 *   - API 失败时降级处理，不阻断正常操作
 *
 * 2026-04-12 新增：账单规则引擎（最低消费/服务费，v238）
 *   - 支付前调用 /api/v1/orders/{id}/apply-billing-rules
 *   - 若有服务费：在账单上显示服务费明细行
 *   - 若未达最低消费：弹出 Toast 提示差额
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useOrderStore } from '../store/orderStore';
import {
  printReceipt as apiPrintReceipt,
  settleOrderOffline,
  createPaymentOffline,
} from '../api/tradeApi';
import { showToast } from '../hooks/useToast';
import { printReceipt as bridgePrint, openCashBox } from '../bridge/TXBridge';
import { DiscountPreviewSheet, type DiscountParams } from '../components/DiscountPreviewSheet';
import CustomerBrainPanel from '../components/CustomerBrainPanel';
import { CouponEligibleSheet } from '../components/CouponEligibleSheet';
import { useCouponEligibility } from '../hooks/useCouponEligibility';
import { formatPrice } from '@tx-ds/utils';
import { useKeyboardShortcuts, POS_SHORTCUTS } from '../hooks/useKeyboardShortcuts';

// ── 账单规则类型 ──────────────────────────────────────────────────────────────

interface ServiceFeeItem {
  rule_id: string;
  calc_method: string;
  fee_fen: number;
  description: string;
}

interface BillingRulesResult {
  service_fee_items: ServiceFeeItem[];
  service_fee_fen: number;
  min_spend_shortfall_fen: number;
  min_spend_required_fen: number;
  total_extra_fen: number;
  exempted: boolean;
  exemption_reason: string | null;
  message: string;
}

/** 调用账单规则引擎 API */
async function applyBillingRules(
  orderId: string,
  storeId: string,
  orderAmountFen: number,
  guestCount: number,
  memberTier?: string,
): Promise<BillingRulesResult | null> {
  try {
    const res = await fetch(`/api/v1/orders/${orderId}/apply-billing-rules`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Tenant-ID': import.meta.env.VITE_TENANT_ID || '',
      },
      body: JSON.stringify({
        store_id: storeId,
        order_amount_fen: orderAmountFen,
        guest_count: guestCount,
        member_tier: memberTier || null,
      }),
    });
    if (!res.ok) return null;
    const json = await res.json();
    return json.ok ? (json.data as BillingRulesResult) : null;
  } catch {
    // 网络失败时降级，不阻断结账
    return null;
  }
}

/** @deprecated Use formatPrice from @tx-ds/utils */
const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

const PAYMENT_METHODS = [
  { key: 'wechat', label: '微信支付', color: '#07C160' },
  { key: 'alipay', label: '支付宝', color: '#1677FF' },
  { key: 'cash', label: '现金', color: '#faad14' },
  { key: 'unionpay', label: '银联刷卡', color: '#e6002d' },
  { key: 'credit_account', label: '挂账', color: '#722ed1' },
  { key: 'member_balance', label: '会员余额', color: '#13c2c2' },
];

// 默认用于演示的折扣档位（收银员手动选择，实际可扩展为输入框）
const DISCOUNT_PRESETS: { label: string; type: DiscountParams['discountType']; value: number }[] = [
  { label: '九折', type: 'percentage', value: 0.9 },
  { label: '八折', type: 'percentage', value: 0.8 },
  { label: '七折', type: 'percentage', value: 0.7 },
  { label: '减50元', type: 'fixed', value: 5000 },
  { label: '免单', type: 'free_item', value: 1 },
];

// 估算毛利率（实际应从菜品成本数据中获取，此处使用保守估算值）
const ESTIMATED_MARGIN_RATE = 0.45;

export function SettlePage() {
  const navigate = useNavigate();
  const { items, totalFen, discountFen, tableNo, orderId, applyDiscount, clear } = useOrderStore();
  const finalFen = totalFen - discountFen;
  const [paying, setPaying] = useState(false);

  // 折扣 AI 分析抽屉状态
  const [discountSheetVisible, setDiscountSheetVisible] = useState(false);
  const [discountParams, setDiscountParams] = useState<DiscountParams | null>(null);
  // 暂存待确认的折扣金额，AI 批准后才真正写入 store
  const [pendingDiscountFen, setPendingDiscountFen] = useState<number>(0);

  // 账单规则状态（服务费/最低消费）
  const [billingRules, setBillingRules] = useState<BillingRulesResult | null>(null);
  // 最低消费 Toast 提示
  const [minSpendToast, setMinSpendToast] = useState<string | null>(null);

  // campaign.checkout_eligible 可用券检查
  // customerId 从 URL search params 中取（会员到店绑定后由收银台写入）
  const customerId = new URLSearchParams(window.location.search).get('customer_id') ?? '';
  const coupon = useCouponEligibility({
    orderId: orderId ?? '',
    storeId: import.meta.env.VITE_STORE_ID || '',
    customerId,
    orderAmountFen: finalFen,
    tenantId: import.meta.env.VITE_TENANT_ID || '',
    operatorId: import.meta.env.VITE_OPERATOR_ID || '',
    onApplied: (discountFenAmount) => applyDiscount(discountFenAmount),
  });

  /** 点击某个折扣档位 → 计算折扣金额 → 打开 AI 分析抽屉 */
  const handleDiscountPress = (preset: typeof DISCOUNT_PRESETS[0]) => {
    if (totalFen <= 0) return;

    let discountAmount = 0;
    if (preset.type === 'percentage') {
      discountAmount = totalFen - Math.round(totalFen * preset.value);
    } else if (preset.type === 'fixed') {
      discountAmount = Math.min(preset.value, totalFen);
    } else if (preset.type === 'free_item') {
      discountAmount = totalFen;
    }

    setPendingDiscountFen(discountAmount);

    setDiscountParams({
      orderId: orderId ?? 'temp',
      discountType: preset.type,
      discountValue: preset.value,
      orderAmountFen: totalFen,
      employeeId: localStorage.getItem('employeeId') ?? 'unknown',
      currentMarginRate: ESTIMATED_MARGIN_RATE,
    });

    setDiscountSheetVisible(true);
  };

  /** AI 分析通过后，收银员点击确认 → 真正写入折扣 */
  const handleDiscountConfirm = () => {
    applyDiscount(pendingDiscountFen);
  };

  const handlePay = async (method: string) => {
    if (paying) return;
    setPaying(true);

    try {
      // 0. 应用账单规则（服务费/最低消费）
      if (orderId) {
        const storeId = import.meta.env.VITE_STORE_ID || '';
        const rules = await applyBillingRules(orderId, storeId, finalFen, 1, undefined);
        setBillingRules(rules);

        if (rules && rules.min_spend_shortfall_fen > 0) {
          // 未达最低消费 → 显示 Toast 提示（不阻断，允许收银员继续）
          const actualYuan = (finalFen / 100).toFixed(2);
          const requiredYuan = (rules.min_spend_required_fen / 100).toFixed(2);
          const gapYuan = (rules.min_spend_shortfall_fen / 100).toFixed(2);
          setMinSpendToast(`本桌消费¥${actualYuan}，最低消费¥${requiredYuan}，差额¥${gapYuan}`);
          // Toast 自动消失（3秒）
          setTimeout(() => setMinSpendToast(null), 3000);
        }
      }

      // 1. 创建支付记录（含服务费）
      const totalWithFees = billingRules ? finalFen + billingRules.service_fee_fen : finalFen;
      if (orderId) {
        // P0-1：离线友好。断网时自动入本地队列返回 queued:true，不抛"支付失败"
        const payRes = await createPaymentOffline(orderId, method, totalWithFees);
        if (payRes.ok && payRes.data && (payRes.data as { queued?: boolean }).queued) {
          showToast('已加入离线队列，网络恢复后自动上传', 'offline');
          clear();
          navigate('/tables');
          return;
        }
        if (!payRes.ok) {
          // 业务拒绝（如订单已支付）→ 红色 Toast，收银员明确感知而不是 alert 阻塞
          showToast(`支付未完成: ${payRes.error?.message ?? '未知错误'}`, 'error');
          return;
        }
        // 在线成功：继续走结算
        // 兼容同步调用点：payRes.data 是 {payment_id, payment_no}，本分支不依赖
        // 仅当非 queued 才触达这里
        // （无需额外操作）
        void payRes;
      }

      // 2. 结算订单
      if (orderId) {
        const settleRes = await settleOrderOffline(orderId);
        if (settleRes.ok && settleRes.data && (settleRes.data as { queued?: boolean }).queued) {
          showToast('结算已加入离线队列，网络恢复后自动上传', 'offline');
          clear();
          navigate('/tables');
          return;
        }
        if (!settleRes.ok) {
          showToast(`结算失败: ${settleRes.error?.message ?? '未知错误'}`, 'error');
          return;
        }
      }

      // 3. 打印小票
      if (orderId) {
        try {
          const { content_base64 } = await apiPrintReceipt(orderId);
          await bridgePrint(content_base64);
        } catch {
          // 打印失败不阻断结算
        }
      }

      // 4. 现金弹钱箱
      if (method === 'cash') {
        try { await openCashBox(); } catch { /* ignore */ }
      }

      showToast('支付成功', 'success');
      clear();
      navigate('/tables');
    } catch (e) {
      // 未预期异常：保留 Toast 兜底，不再用 alert 阻塞（P0-1）
      showToast(`支付异常: ${e instanceof Error ? e.message : '未知错误'}`, 'error');
    } finally {
      setPaying(false);
    }
  };

  /* ── 键盘快捷键（结账页）── */
  useKeyboardShortcuts([
    {
      key: POS_SHORTCUTS.ESCAPE.key,        // Escape — 返回点餐
      label: '返回点餐页面',
      handler: () => navigate(-1),
      disabled: paying,
    },
    {
      key: POS_SHORTCUTS.QUICK_CASH.key,    // Ctrl+Enter — 快速现金结账
      label: POS_SHORTCUTS.QUICK_CASH.description,
      handler: () => { if (!paying && finalFen > 0) { void handlePay('cash'); } },
      disabled: paying || finalFen <= 0,
    },
    {
      key: POS_SHORTCUTS.PRINT.key,         // F8 — 打印账单
      label: POS_SHORTCUTS.PRINT.description,
      handler: () => {
        if (orderId) {
          apiPrintReceipt(orderId)
            .then(({ content_base64 }) => bridgePrint(content_base64))
            .catch(() => {});
        }
      },
      disabled: !orderId,
    },
  ], { activeContext: 'settle' });

  return (
    <div style={{ display: 'flex', height: '100vh', background: '#0B1A20', color: '#fff' }}>
      {/* 左侧 — 订单摘要 */}
      <div style={{ flex: 1, padding: 24, overflowY: 'auto' }}>
        {/* 客户大脑面板 - 有会员时显示 */}
        <CustomerBrainPanel />

        <h2>结算 · 桌号 {tableNo}</h2>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #333', textAlign: 'left' }}>
              <th style={{ padding: 8 }}>菜品</th>
              <th style={{ padding: 8 }}>数量</th>
              <th style={{ padding: 8, textAlign: 'right' }}>小计</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id} style={{ borderBottom: '1px solid #1a2a33' }}>
                <td style={{ padding: 8 }}>{item.name}</td>
                <td style={{ padding: 8 }}>×{item.quantity}</td>
                <td style={{ padding: 8, textAlign: 'right' }}>{fen2yuan(item.priceFen * item.quantity)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {/* 服务费明细行 */}
        {billingRules && billingRules.service_fee_items.length > 0 && (
          <div style={{ marginTop: 8 }}>
            {billingRules.service_fee_items.map((item) => (
              <div
                key={item.rule_id}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  padding: '6px 8px',
                  borderRadius: 6,
                  background: 'rgba(22,119,255,0.08)',
                  border: '1px solid rgba(22,119,255,0.2)',
                  marginBottom: 4,
                  fontSize: 15,
                  color: '#1677FF',
                }}
              >
                <span>{item.description}</span>
                <span style={{ fontWeight: 700 }}>+{fen2yuan(item.fee_fen)}</span>
              </div>
            ))}
          </div>
        )}

        <div style={{ marginTop: 16, fontSize: 24, fontWeight: 'bold', color: '#FF6B2C', textAlign: 'right' }}>
          应付: {fen2yuan(billingRules ? finalFen + billingRules.service_fee_fen : finalFen)}
          {billingRules && billingRules.service_fee_fen > 0 && (
            <span style={{ fontSize: 14, color: '#8A94A4', marginLeft: 8, fontWeight: 400 }}>
              （含服务费{fen2yuan(billingRules.service_fee_fen)}）
            </span>
          )}
        </div>

        {/* 折扣区域 */}
        {discountFen > 0 && (
          <div style={{
            marginTop: 8,
            padding: '10px 14px',
            borderRadius: 8,
            background: 'rgba(255,107,53,0.12)',
            border: '1px solid rgba(255,107,53,0.3)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            fontSize: 17,
          }}>
            <span style={{ color: '#FF6B35', fontWeight: 600 }}>已优惠</span>
            <span style={{ color: '#FF6B35', fontWeight: 700 }}>-{fen2yuan(discountFen)}</span>
          </div>
        )}

        {/* 折扣档位按钮组 */}
        <div style={{ marginTop: 20 }}>
          <div style={{ fontSize: 17, color: '#8A94A4', marginBottom: 10, fontWeight: 600 }}>
            添加折扣（AI 风险分析）
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {DISCOUNT_PRESETS.map((preset) => (
              <button
                key={preset.label}
                type="button"
                onClick={() => handleDiscountPress(preset)}
                disabled={items.length === 0}
                style={{
                  padding: '10px 16px',
                  minHeight: 48,
                  border: '1.5px solid #FF6B35',
                  borderRadius: 8,
                  background: 'rgba(255,107,53,0.12)',
                  color: items.length === 0 ? '#666' : '#FF6B35',
                  fontSize: 17,
                  fontWeight: 600,
                  cursor: items.length === 0 ? 'not-allowed' : 'pointer',
                  fontFamily: 'inherit',
                  opacity: items.length === 0 ? 0.4 : 1,
                }}
              >
                {preset.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* 右侧 — 支付方式 */}
      <div style={{ width: 320, background: '#112228', padding: 24, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <h3>选择支付方式</h3>
        {PAYMENT_METHODS.map((m) => (
          <button
            key={m.key}
            onClick={() => handlePay(m.key)}
            disabled={paying}
            style={{
              padding: 16, border: 'none', borderRadius: 8,
              background: paying ? '#444' : m.color, color: '#fff', fontSize: 18,
              cursor: paying ? 'not-allowed' : 'pointer',
            }}
          >
            {paying ? '处理中...' : m.label}
          </button>
        ))}
        {/* 高级结算入口 */}
        <div style={{ borderTop: '1px solid #333', paddingTop: 12, marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <button
            onClick={() => navigate(`/credit-pay/${orderId || 'temp'}`)}
            style={{ padding: 14, border: '1px solid #722ed1', borderRadius: 8, background: 'transparent', color: '#722ed1', cursor: 'pointer', fontSize: 16, minHeight: 48 }}
          >
            企业挂账
          </button>
          <button
            onClick={() => navigate(`/split-pay/${orderId || 'temp'}`)}
            style={{ padding: 14, border: '1px solid #1677FF', borderRadius: 8, background: 'transparent', color: '#1677FF', cursor: 'pointer', fontSize: 16, minHeight: 48 }}
          >
            拆单结账
          </button>
          <button
            onClick={() => navigate(`/tax-invoice/${orderId || 'temp'}`)}
            style={{ padding: 14, border: '1px solid #faad14', borderRadius: 8, background: 'transparent', color: '#faad14', cursor: 'pointer', fontSize: 16, minHeight: 48 }}
          >
            开具发票
          </button>
        </div>
        {/* 收益优化师建议 */}
        <div style={{
          background: 'rgba(249,115,22,.06)', border: '1px solid rgba(249,115,22,.15)',
          borderRadius: 10, padding: '10px 14px', margin: '12px 0',
        }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: '#FF6B35', marginBottom: 8 }}>
            💡 收益优化师 · 结账建议
          </div>
          {['存酒余800ml，建议推荐续存享9折', '企业客户，发票已自动准备', '五一包间有档期，可推荐预约'].map((tip, i) => (
            <div key={i} style={{ fontSize: 12, color: '#5F5E5A', marginBottom: 4, display: 'flex', gap: 6 }}>
              <span style={{ color: '#FF6B35' }}>◆</span>{tip}
            </div>
          ))}
        </div>

        <button
          onClick={() => navigate(-1)}
          style={{ padding: 12, border: '1px solid #444', borderRadius: 8, background: 'transparent', color: '#999', cursor: 'pointer', marginTop: 12 }}
        >
          返回修改
        </button>
      </div>

      {/* 折扣 AI 分析抽屉 */}
      <DiscountPreviewSheet
        visible={discountSheetVisible}
        onClose={() => setDiscountSheetVisible(false)}
        onConfirm={handleDiscountConfirm}
        discountParams={discountParams}
      />

      {/* campaign.checkout_eligible — 可用券提示底部弹层 */}
      <CouponEligibleSheet
        visible={coupon.sheetVisible}
        coupons={coupon.coupons}
        applying={coupon.applying}
        onApply={coupon.apply}
        onClose={coupon.closeSheet}
      />

      {/* 最低消费 Toast 提示 */}
      {minSpendToast && (
        <div
          style={{
            position: 'fixed',
            bottom: 80,
            left: '50%',
            transform: 'translateX(-50%)',
            background: 'rgba(250,173,20,0.95)',
            color: '#1a1a1a',
            padding: '12px 24px',
            borderRadius: 10,
            fontSize: 16,
            fontWeight: 600,
            boxShadow: '0 4px 20px rgba(0,0,0,0.4)',
            zIndex: 9999,
            maxWidth: '80vw',
            textAlign: 'center',
          }}
        >
          ⚠ {minSpendToast}
        </div>
      )}
    </div>
  );
}
