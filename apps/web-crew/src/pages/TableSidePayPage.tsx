/**
 * 桌边结账页 — 服务员端 PWA
 * 路由: /table-side-pay?order_id=xxx&table=xxx
 */
import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { formatPrice } from '@tx-ds/utils';
import DiscountPreviewSheet, { type DiscountInputItem, type DiscountCalculateResult } from './DiscountPreviewSheet';


// ─── 类型 ───

interface OrderSummary {
  order_id: string;
  total_amount: number; // 分
  item_count: number;
  duration_min: number;
}

interface MemberInfo {
  member_id: string;
  name: string;
  points: number;
  discount_rate: number; // 0.0–1.0, e.g. 0.95 = 95折
}

type PayMethod = 'wechat' | 'alipay' | 'cash' | 'credit' | 'tab';

// ─── API 工具 ───

const TENANT_ID = (): string =>
  (typeof window !== 'undefined' && (window as unknown as Record<string, string>).__TENANT_ID__) || '';

async function txFetch<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': TENANT_ID(),
      ...(options.headers || {}),
    },
  });
  const json = await res.json();
  if (!res.ok || json.ok === false) {
    throw new Error(json.error?.message || json.detail || `HTTP ${res.status}`);
  }
  return json.data ?? json;
}

// ─── 工具函数 ───

/** @deprecated Use formatPrice from @tx-ds/utils */
function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

function calcDiscountedAmount(total: number, rate: number): number {
  return Math.round(total * rate);
}

// ─── 主页面 ───

export default function TableSidePayPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const orderId = searchParams.get('order_id') || '';
  const tableNo = searchParams.get('table') || '--';

  const [order, setOrder] = useState<OrderSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const [memberPhone, setMemberPhone] = useState('');
  const [memberInfo, setMemberInfo] = useState<MemberInfo | null>(null);
  const [memberLookupLoading, setMemberLookupLoading] = useState(false);
  const [memberError, setMemberError] = useState('');

  const [selectedMethod, setSelectedMethod] = useState<PayMethod | null>(null);
  const [tabUnit, setTabUnit] = useState('');
  const [showTabModal, setShowTabModal] = useState(false);

  const [settling, setSettling] = useState(false);
  const [settled, setSettled] = useState(false);
  const [settleError, setSettleError] = useState('');

  // ─── 折扣 Sheet 状态 ───
  const [showDiscountSheet, setShowDiscountSheet] = useState(false);
  const [discountResult, setDiscountResult] = useState<DiscountCalculateResult | null>(null);

  // ─── 加载订单 ───
  useEffect(() => {
    if (!orderId) {
      setOrder(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    txFetch<Record<string, unknown>>(`/api/v1/trade/orders/${encodeURIComponent(orderId)}`)
      .then((d) => {
        setOrder({
          order_id: (d.id ?? d.order_id ?? orderId) as string,
          total_amount: (d.final_amount_fen ?? d.total_amount_fen ?? 0) as number,
          item_count: (d.item_count ?? 0) as number,
          duration_min: (d.dining_duration_min ?? 0) as number,
        });
      })
      .catch(() => {
        setOrder(null);
      })
      .finally(() => setLoading(false));
  }, [orderId]);

  // ─── 会员查询 ───
  async function lookupMember() {
    if (!memberPhone.trim()) return;
    setMemberLookupLoading(true);
    setMemberError('');
    setMemberInfo(null);
    try {
      const res = await fetch(
        `/api/v1/members/lookup?phone=${encodeURIComponent(memberPhone.trim())}`,
        { headers: { 'X-Tenant-ID': (window as any).__TENANT_ID__ || '' } },
      );
      const json = await res.json();
      if (json.ok && json.data) {
        setMemberInfo({
          member_id: json.data.id,
          name: json.data.name || '会员',
          points: json.data.points ?? 0,
          discount_rate: json.data.discount_rate ?? 1.0,
        });
      } else {
        setMemberError('未找到该会员');
      }
    } catch {
      setMemberError('查询失败，请重试');
    } finally {
      setMemberLookupLoading(false);
    }
  }

  // ─── 支付确认 ───
  async function handleConfirmPayment() {
    if (!selectedMethod || !order) return;

    // 挂账模式需要先填单位
    if (selectedMethod === 'tab' && !tabUnit.trim()) {
      setShowTabModal(true);
      return;
    }

    setSettling(true);
    setSettleError('');
    try {
      const amount_fen = memberInfo && memberInfo.discount_rate < 1
        ? calcDiscountedAmount(order.total_amount, memberInfo.discount_rate)
        : order.total_amount;
      await txFetch(`/api/v1/trade/orders/${encodeURIComponent(order.order_id)}/settle`, {
        method: 'POST',
        body: JSON.stringify({
          method: selectedMethod,
          amount_fen,
          member_id: memberInfo?.member_id ?? null,
          remark: selectedMethod === 'tab' ? tabUnit.trim() : null,
        }),
      });
      setSettled(true);
      setTimeout(() => navigate('/tables'), 3000);
    } catch (err: unknown) {
      setSettleError(err instanceof Error ? err.message : '结账失败，请重试');
    } finally {
      setSettling(false);
    }
  }

  // 折后实付金额：优先使用 DiscountPreviewSheet 确认的结果，其次会员折扣率
  const actualAmount =
    order
      ? discountResult !== null
        ? discountResult.final_amount_fen
        : memberInfo && memberInfo.discount_rate < 1
          ? calcDiscountedAmount(order.total_amount, memberInfo.discount_rate)
          : order.total_amount
      : 0;

  // 构建传给 DiscountPreviewSheet 的折扣列表（根据已查询的会员信息）
  const discountItems: DiscountInputItem[] = memberInfo && memberInfo.discount_rate < 1
    ? [{ type: 'member_discount', member_id: memberInfo.member_id, rate: memberInfo.discount_rate }]
    : [];

  // ─── 加载失败空状态 ───
  if (!loading && !order) {
    return (
      <div
        style={{
          minHeight: '100vh',
          background: '#0B1A20',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 16,
          color: '#9DB4B2',
          fontSize: 16,
        }}
      >
        <div style={{ fontSize: 40 }}>📋</div>
        <div>暂无订单数据</div>
        <button
          onClick={() => navigate(-1)}
          style={{
            minHeight: 48,
            padding: '0 24px',
            background: '#FF6B35',
            color: '#fff',
            border: 'none',
            borderRadius: 10,
            fontSize: 16,
            cursor: 'pointer',
          }}
        >
          返回
        </button>
      </div>
    );
  }

  // ─── 成功全屏 ───
  if (settled) {
    return (
      <div
        style={{
          position: 'fixed',
          inset: 0,
          background: '#0D2B1F',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 24,
        }}
      >
        <div
          style={{
            width: 96,
            height: 96,
            borderRadius: '50%',
            background: '#07C160',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 48,
          }}
        >
          ✓
        </div>
        <div style={{ fontSize: 28, fontWeight: 700, color: '#07C160' }}>收款成功</div>
        <div style={{ fontSize: 18, color: '#9DB4B2' }}>3秒后返回桌台列表…</div>
      </div>
    );
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        background: '#0B1A20',
        color: '#fff',
        fontFamily: 'system-ui, -apple-system, sans-serif',
        paddingBottom: 32,
      }}
    >
      {/* ─── 顶部导航 ─── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '16px 16px 12px',
          background: '#112228',
          borderBottom: '1px solid #1a2a33',
          position: 'sticky',
          top: 0,
          zIndex: 10,
        }}
      >
        <button
          onClick={() => navigate(-1)}
          style={{
            minWidth: 48,
            minHeight: 48,
            background: 'transparent',
            border: 'none',
            color: '#FF6B35',
            fontSize: 24,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 0,
          }}
        >
          ←
        </button>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 20, fontWeight: 700 }}>桌边结账</div>
        </div>
        <div
          style={{
            background: '#1a2a33',
            borderRadius: 8,
            padding: '6px 14px',
            fontSize: 16,
            color: '#FF6B35',
            fontWeight: 600,
          }}
        >
          {tableNo} 桌
        </div>
      </div>

      <div style={{ padding: '16px 16px 0' }}>
        {/* ─── 订单概要卡片 ─── */}
        {loading ? (
          <div
            style={{
              background: '#112228',
              borderRadius: 12,
              padding: 20,
              marginBottom: 16,
              fontSize: 16,
              color: '#64748b',
            }}
          >
            加载中…
          </div>
        ) : order ? (
          <div
            style={{
              background: '#112228',
              borderRadius: 12,
              padding: 20,
              marginBottom: 16,
              border: '1px solid #1a2a33',
            }}
          >
            <div style={{ fontSize: 14, color: '#9DB4B2', marginBottom: 12 }}>消费详情</div>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'flex-end',
              }}
            >
              <div>
                <div style={{ fontSize: 36, fontWeight: 700, color: '#FF6B35', lineHeight: 1 }}>
                  ¥{fenToYuan(order.total_amount)}
                </div>
                <div style={{ fontSize: 16, color: '#9DB4B2', marginTop: 8 }}>消费金额</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 18, fontWeight: 600, color: '#E2EAE8' }}>
                  {order.item_count} 道菜
                </div>
                <div style={{ fontSize: 16, color: '#9DB4B2', marginTop: 4 }}>
                  用餐 {order.duration_min} 分钟
                </div>
              </div>
            </div>
          </div>
        ) : null}

        {/* ─── 会员优惠区 ─── */}
        <div
          style={{
            background: '#112228',
            borderRadius: 12,
            padding: 16,
            marginBottom: 16,
            border: '1px solid #1a2a33',
          }}
        >
          <div style={{ fontSize: 14, color: '#9DB4B2', marginBottom: 12 }}>会员优惠（可选）</div>
          <div style={{ display: 'flex', gap: 10 }}>
            <input
              type="tel"
              value={memberPhone}
              onChange={(e) => setMemberPhone(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && lookupMember()}
              placeholder="输入手机号查询会员"
              style={{
                flex: 1,
                minHeight: 48,
                background: '#0B1A20',
                border: '1px solid #1a2a33',
                borderRadius: 8,
                color: '#fff',
                fontSize: 16,
                padding: '0 14px',
                outline: 'none',
              }}
            />
            <button
              onClick={lookupMember}
              disabled={memberLookupLoading || !memberPhone.trim()}
              style={{
                minWidth: 80,
                minHeight: 48,
                background: memberPhone.trim() ? '#FF6B35' : '#1a2a33',
                border: 'none',
                borderRadius: 8,
                color: '#fff',
                fontSize: 16,
                fontWeight: 600,
                cursor: memberPhone.trim() ? 'pointer' : 'not-allowed',
              }}
            >
              {memberLookupLoading ? '…' : '查询'}
            </button>
          </div>

          {memberError && (
            <div style={{ fontSize: 14, color: '#FF4D4F', marginTop: 8 }}>{memberError}</div>
          )}

          {memberInfo && (
            <div
              style={{
                marginTop: 12,
                background: '#0B2A1A',
                borderRadius: 8,
                padding: 12,
                border: '1px solid #07C16040',
              }}
            >
              <div style={{ fontSize: 16, fontWeight: 600, color: '#07C160' }}>
                {memberInfo.name}
              </div>
              <div
                style={{
                  display: 'flex',
                  gap: 16,
                  marginTop: 6,
                  fontSize: 14,
                  color: '#9DB4B2',
                }}
              >
                <span>积分：{memberInfo.points}</span>
                {memberInfo.discount_rate < 1 && (
                  <span style={{ color: '#FF6B35' }}>
                    折扣：{(memberInfo.discount_rate * 10).toFixed(1)}折 →
                    ¥{fenToYuan(calcDiscountedAmount(order?.total_amount ?? 0, memberInfo.discount_rate))}
                  </span>
                )}
              </div>
            </div>
          )}
        </div>

        {/* ─── 折扣入口卡片 ─── */}
        {order && (
          <button
            onClick={() => setShowDiscountSheet(true)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 14,
              width: '100%',
              minHeight: 64,
              background: discountResult && discountResult.total_saved_fen > 0
                ? 'rgba(255,107,53,0.12)'
                : '#112228',
              border: discountResult && discountResult.total_saved_fen > 0
                ? '1px solid rgba(255,107,53,0.5)'
                : '1px solid #1a2a33',
              borderRadius: 12,
              padding: '0 16px',
              marginBottom: 16,
              cursor: 'pointer',
              textAlign: 'left',
            }}
          >
            {/* 标签图标 */}
            <span style={{ fontSize: 22, flexShrink: 0 }}>🏷️</span>

            {/* 文字区 */}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 16, fontWeight: 600, color: '#E0EEF0' }}>
                可用优惠
              </div>
              {discountResult && discountResult.total_saved_fen > 0 ? (
                <div
                  style={{
                    fontSize: 14,
                    color: '#FF6B35',
                    marginTop: 2,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {discountResult.applied_steps.map((s) => s.description).join(' · ')}
                </div>
              ) : discountResult !== null ? (
                <div style={{ fontSize: 14, color: '#5F7A85', marginTop: 2 }}>
                  暂无可用优惠
                </div>
              ) : (
                <div style={{ fontSize: 14, color: '#9DB4B2', marginTop: 2 }}>
                  点击查看可叠加优惠
                </div>
              )}
            </div>

            {/* 右侧：已优惠金额 或 箭头 */}
            {discountResult && discountResult.total_saved_fen > 0 ? (
              <div style={{ flexShrink: 0, textAlign: 'right' }}>
                <div style={{ fontSize: 13, color: '#9DB4B2' }}>已优惠</div>
                <div style={{ fontSize: 18, fontWeight: 700, color: '#FF6B35' }}>
                  ¥{(discountResult.total_saved_fen / 100).toFixed(2)}
                </div>
              </div>
            ) : (
              <span style={{ fontSize: 20, color: '#9DB4B2', flexShrink: 0 }}>›</span>
            )}
          </button>
        )}

        {/* ─── 支付方式选择 ─── */}
        <div
          style={{
            background: '#112228',
            borderRadius: 12,
            padding: 16,
            marginBottom: 16,
            border: '1px solid #1a2a33',
          }}
        >
          <div style={{ fontSize: 14, color: '#9DB4B2', marginBottom: 12 }}>选择支付方式</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {(
              [
                { key: 'wechat', label: '微信扫码', color: '#07C160', icon: '微' },
                { key: 'alipay', label: '支付宝扫码', color: '#1677FF', icon: '支' },
                { key: 'cash', label: '现金收款', color: '#52c41a', icon: '现' },
                { key: 'credit', label: '刷卡', color: '#722ED1', icon: '卡' },
                { key: 'tab', label: '挂账', color: '#FAAD14', icon: '挂' },
              ] as { key: PayMethod; label: string; color: string; icon: string }[]
            ).map(({ key, label, color, icon }) => {
              const isSelected = selectedMethod === key;
              return (
                <button
                  key={key}
                  onClick={() => {
                    setSelectedMethod(key);
                    if (key === 'tab') setShowTabModal(true);
                  }}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 14,
                    minHeight: 72,
                    background: isSelected ? `${color}22` : '#0B1A20',
                    border: isSelected ? `2px solid ${color}` : '2px solid #1a2a33',
                    borderRadius: 10,
                    color: '#fff',
                    fontSize: 18,
                    fontWeight: 600,
                    cursor: 'pointer',
                    padding: '0 18px',
                    transition: 'all 0.15s',
                    textAlign: 'left',
                  }}
                >
                  <span
                    style={{
                      width: 40,
                      height: 40,
                      borderRadius: 10,
                      background: color,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 16,
                      fontWeight: 700,
                      flexShrink: 0,
                    }}
                  >
                    {icon}
                  </span>
                  <span style={{ flex: 1 }}>{label}</span>
                  {isSelected && (
                    <span style={{ color, fontSize: 20 }}>✓</span>
                  )}
                  {key === 'tab' && tabUnit && isSelected && (
                    <span style={{ fontSize: 14, color: '#FAAD14', maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {tabUnit}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {/* ─── 扫码收款快捷入口 ─── */}
          <button
            onClick={() => {
              const params = new URLSearchParams({
                order_id: order?.order_id || orderId,
                amount_fen: String(actualAmount),
                table: tableNo,
              });
              navigate(`/scan-pay?${params.toString()}`);
            }}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 14,
              minHeight: 72,
              background: '#1a0800',
              border: '2px dashed #FF6B35',
              borderRadius: 10,
              color: '#FF6B35',
              fontSize: 18,
              fontWeight: 700,
              cursor: 'pointer',
              padding: '0 18px',
              marginTop: 4,
              width: '100%',
              textAlign: 'left',
            }}
          >
            <span
              style={{
                width: 40,
                height: 40,
                borderRadius: 10,
                background: '#FF6B35',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 20,
                flexShrink: 0,
              }}
            >
              📱
            </span>
            <span style={{ flex: 1 }}>扫码收款（付款码）</span>
            <span style={{ fontSize: 14, color: '#9DB4B2', fontWeight: 400 }}>微信/支付宝/银联</span>
          </button>
        </div>

        {/* ─── 错误提示 ─── */}
        {settleError && (
          <div
            style={{
              background: '#2D0B0B',
              border: '1px solid #FF4D4F',
              borderRadius: 8,
              padding: 12,
              fontSize: 16,
              color: '#FF4D4F',
              marginBottom: 16,
            }}
          >
            {settleError}
          </div>
        )}

        {/* ─── 金额汇总（有折扣时显示原价划线 + 折后价） ─── */}
        {selectedMethod && order && discountResult && discountResult.total_saved_fen > 0 && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'flex-end',
              gap: 12,
              marginBottom: 12,
              padding: '10px 16px',
              background: 'rgba(255,107,53,0.08)',
              borderRadius: 10,
              border: '1px solid rgba(255,107,53,0.2)',
            }}
          >
            <div style={{ fontSize: 14, color: '#9DB4B2' }}>
              原价{' '}
              <span style={{ textDecoration: 'line-through', color: '#5F7A85' }}>
                ¥{fenToYuan(order.total_amount)}
              </span>
            </div>
            <div style={{ fontSize: 14, color: '#27AE7A', fontWeight: 600 }}>
              优惠 ¥{fenToYuan(discountResult.total_saved_fen)}
            </div>
            <div style={{ fontSize: 22, fontWeight: 800, color: '#FF6B35' }}>
              ¥{fenToYuan(actualAmount)}
            </div>
          </div>
        )}

        {/* ─── 确认收款按钮 ─── */}
        {selectedMethod && (
          <button
            onClick={handleConfirmPayment}
            disabled={settling}
            style={{
              display: 'block',
              width: '100%',
              minHeight: 64,
              background: settling ? '#8B4A24' : '#FF6B35',
              border: 'none',
              borderRadius: 12,
              color: '#fff',
              fontSize: 22,
              fontWeight: 700,
              cursor: settling ? 'not-allowed' : 'pointer',
              letterSpacing: 1,
            }}
          >
            {settling ? '处理中…' : `确认收款 ¥${fenToYuan(actualAmount)}`}
          </button>
        )}
      </div>

      {/* ─── 挂账弹窗 ─── */}
      {showTabModal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.7)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 100,
            padding: 24,
          }}
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowTabModal(false);
          }}
        >
          <div
            style={{
              background: '#112228',
              borderRadius: 16,
              padding: 24,
              width: '100%',
              maxWidth: 400,
              border: '1px solid #FAAD14',
            }}
          >
            <div style={{ fontSize: 20, fontWeight: 700, marginBottom: 16, color: '#FAAD14' }}>
              挂账信息
            </div>
            <div style={{ fontSize: 16, color: '#9DB4B2', marginBottom: 10 }}>
              请填写挂账单位或姓名
            </div>
            <input
              autoFocus
              type="text"
              value={tabUnit}
              onChange={(e) => setTabUnit(e.target.value)}
              placeholder="如：屯象科技、张总"
              style={{
                display: 'block',
                width: '100%',
                minHeight: 52,
                background: '#0B1A20',
                border: '1px solid #FAAD14',
                borderRadius: 8,
                color: '#fff',
                fontSize: 18,
                padding: '0 14px',
                outline: 'none',
                boxSizing: 'border-box',
              }}
            />
            <div style={{ display: 'flex', gap: 12, marginTop: 20 }}>
              <button
                onClick={() => {
                  setSelectedMethod(null);
                  setTabUnit('');
                  setShowTabModal(false);
                }}
                style={{
                  flex: 1,
                  minHeight: 52,
                  background: '#1a2a33',
                  border: 'none',
                  borderRadius: 8,
                  color: '#9DB4B2',
                  fontSize: 18,
                  cursor: 'pointer',
                }}
              >
                取消
              </button>
              <button
                onClick={() => {
                  if (tabUnit.trim()) setShowTabModal(false);
                }}
                disabled={!tabUnit.trim()}
                style={{
                  flex: 2,
                  minHeight: 52,
                  background: tabUnit.trim() ? '#FAAD14' : '#3a3a00',
                  border: 'none',
                  borderRadius: 8,
                  color: tabUnit.trim() ? '#000' : '#666',
                  fontSize: 18,
                  fontWeight: 700,
                  cursor: tabUnit.trim() ? 'pointer' : 'not-allowed',
                }}
              >
                确认挂账
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ─── 折扣预览 Sheet ─── */}
      {order && (
        <DiscountPreviewSheet
          visible={showDiscountSheet}
          orderId={order.order_id}
          baseAmountFen={order.total_amount}
          discounts={discountItems}
          payMethod={selectedMethod ?? 'wechat'}
          onClose={() => setShowDiscountSheet(false)}
          onPaySuccess={(result) => {
            // 保存折扣计算结果，并标记支付成功
            setDiscountResult(result.discount);
            setShowDiscountSheet(false);
            setSettled(true);
            setTimeout(() => navigate('/tables'), 3000);
          }}
        />
      )}
    </div>
  );
}
