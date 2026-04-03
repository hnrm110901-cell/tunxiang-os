/**
 * 企业挂账结账页面
 * 搜索企业客户 → 显示额度信息 → 签单人输入 → 确认挂账
 */
import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useOrderStore } from '../store/orderStore';
import { createPayment, settleOrder, printReceipt as apiPrintReceipt } from '../api/tradeApi';
import { printReceipt as bridgePrint } from '../bridge/TXBridge';

const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

/* ---------- Mock 企业客户数据（后续对接 tx-member API） ---------- */
interface CreditCustomer {
  id: string;
  name: string;
  contactPerson: string;
  creditLimitFen: number;
  usedFen: number;
  status: 'active' | 'frozen';
}

const MOCK_CUSTOMERS: CreditCustomer[] = [
  { id: 'ent001', name: '湖南广电集团', contactPerson: '张主任', creditLimitFen: 5000000, usedFen: 1230000, status: 'active' },
  { id: 'ent002', name: '中建五局第三公司', contactPerson: '李经理', creditLimitFen: 3000000, usedFen: 2850000, status: 'active' },
  { id: 'ent003', name: '长沙银行总部', contactPerson: '王总', creditLimitFen: 8000000, usedFen: 600000, status: 'active' },
  { id: 'ent004', name: '湖南大学后勤处', contactPerson: '陈老师', creditLimitFen: 2000000, usedFen: 2000000, status: 'frozen' },
];

export function CreditPayPage() {
  const { orderId } = useParams();
  const navigate = useNavigate();
  const { items, totalFen, discountFen, tableNo, clear } = useOrderStore();
  const finalFen = totalFen - discountFen;

  const [searchText, setSearchText] = useState('');
  const [selectedCustomer, setSelectedCustomer] = useState<CreditCustomer | null>(null);
  const [signerName, setSignerName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [step, setStep] = useState<'search' | 'confirm'>('search');

  // 搜索过滤
  const filtered = searchText.trim()
    ? MOCK_CUSTOMERS.filter(
        (c) => c.name.includes(searchText) || c.id.includes(searchText),
      )
    : MOCK_CUSTOMERS;

  const handleSelectCustomer = (customer: CreditCustomer) => {
    setSelectedCustomer(customer);
    setStep('confirm');
  };

  const availableFen = selectedCustomer
    ? selectedCustomer.creditLimitFen - selectedCustomer.usedFen
    : 0;
  const canPay = selectedCustomer && selectedCustomer.status === 'active' && availableFen >= finalFen && signerName.trim().length > 0;

  const handleConfirm = async () => {
    if (!canPay || submitting) return;
    setSubmitting(true);
    try {
      if (orderId) {
        await createPayment(orderId, 'credit_account', finalFen, selectedCustomer!.id);
        await settleOrder(orderId);
        // 打印小票
        try {
          const { content_base64 } = await apiPrintReceipt(orderId);
          await bridgePrint(content_base64);
        } catch {
          // 打印失败不阻断
        }
      }
      clear();
      navigate('/tables');
    } catch (e) {
      alert(`挂账失败: ${e instanceof Error ? e.message : '未知错误'}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ display: 'flex', height: '100vh', background: '#0B1A20', color: '#fff' }}>
      {/* 左侧 — 订单摘要 */}
      <div style={{ width: 360, background: '#112228', padding: 24, display: 'flex', flexDirection: 'column' }}>
        <h2 style={{ margin: '0 0 16px', fontSize: 20 }}>企业挂账 · 桌号 {tableNo}</h2>
        <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
          {items.map((item) => (
            <div key={item.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 0', borderBottom: '1px solid #1a2a33', fontSize: 16 }}>
              <span>{item.name} x{item.quantity}</span>
              <span>{fen2yuan(item.priceFen * item.quantity)}</span>
            </div>
          ))}
        </div>
        <div style={{ borderTop: '1px solid #333', paddingTop: 16, marginTop: 12 }}>
          {discountFen > 0 && (
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 16, color: '#999', marginBottom: 8 }}>
              <span>优惠</span><span>-{fen2yuan(discountFen)}</span>
            </div>
          )}
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 24, fontWeight: 'bold', color: '#FF6B2C' }}>
            <span>应付</span><span>{fen2yuan(finalFen)}</span>
          </div>
        </div>
      </div>

      {/* 右侧 — 企业搜索 / 确认 */}
      <div style={{ flex: 1, padding: 24, display: 'flex', flexDirection: 'column' }}>
        {step === 'search' && (
          <>
            <h3 style={{ margin: '0 0 16px', fontSize: 20 }}>选择挂账企业</h3>
            {/* 搜索框 */}
            <input
              type="text"
              placeholder="输入企业名称或ID搜索..."
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              style={{
                width: '100%', padding: 16, fontSize: 18, border: '2px solid #333',
                borderRadius: 12, background: '#112228', color: '#fff', marginBottom: 16,
                boxSizing: 'border-box', outline: 'none',
              }}
              onFocus={(e) => { e.currentTarget.style.borderColor = '#FF6B2C'; }}
              onBlur={(e) => { e.currentTarget.style.borderColor = '#333'; }}
            />
            {/* 企业列表 */}
            <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>
              {filtered.length === 0 && (
                <div style={{ textAlign: 'center', color: '#666', padding: 40, fontSize: 18 }}>
                  未找到匹配的企业客户
                </div>
              )}
              {filtered.map((c) => {
                const avail = c.creditLimitFen - c.usedFen;
                const usagePercent = Math.round((c.usedFen / c.creditLimitFen) * 100);
                const isInsufficient = avail < finalFen;
                const isFrozen = c.status === 'frozen';
                return (
                  <button
                    key={c.id}
                    onClick={() => !isFrozen && !isInsufficient && handleSelectCustomer(c)}
                    disabled={isFrozen || isInsufficient}
                    style={{
                      width: '100%', padding: 20, marginBottom: 12, borderRadius: 12,
                      background: '#112B36', border: '2px solid transparent',
                      color: '#fff', textAlign: 'left', cursor: isFrozen || isInsufficient ? 'not-allowed' : 'pointer',
                      opacity: isFrozen || isInsufficient ? 0.5 : 1,
                      transition: 'transform 200ms ease, border-color 200ms ease',
                    }}
                    onPointerDown={(e) => { if (!isFrozen && !isInsufficient) e.currentTarget.style.transform = 'scale(0.97)'; }}
                    onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                    onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                      <span style={{ fontSize: 18, fontWeight: 'bold' }}>{c.name}</span>
                      {isFrozen && <span style={{ fontSize: 16, color: '#A32D2D', fontWeight: 'bold' }}>已冻结</span>}
                      {!isFrozen && isInsufficient && <span style={{ fontSize: 16, color: '#BA7517' }}>额度不足</span>}
                    </div>
                    <div style={{ fontSize: 16, color: '#8899A6', marginBottom: 8 }}>
                      联系人: {c.contactPerson} &nbsp;|&nbsp; ID: {c.id}
                    </div>
                    {/* 额度条 */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 16, marginBottom: 6 }}>
                      <span>额度 {fen2yuan(c.creditLimitFen)}</span>
                      <span style={{ color: avail > 0 ? '#0F6E56' : '#A32D2D' }}>可用 {fen2yuan(avail)}</span>
                    </div>
                    <div style={{ height: 8, background: '#1A3A48', borderRadius: 4, overflow: 'hidden' }}>
                      <div style={{
                        width: `${usagePercent}%`, height: '100%', borderRadius: 4,
                        background: usagePercent > 90 ? '#A32D2D' : usagePercent > 70 ? '#BA7517' : '#0F6E56',
                        transition: 'width 300ms ease',
                      }} />
                    </div>
                  </button>
                );
              })}
            </div>
            <button
              onClick={() => navigate(-1)}
              style={{ ...navBtn, background: '#333', marginTop: 12 }}
            >
              返回
            </button>
          </>
        )}

        {step === 'confirm' && selectedCustomer && (
          <>
            <h3 style={{ margin: '0 0 20px', fontSize: 20 }}>确认挂账信息</h3>

            {/* 企业信息卡片 */}
            <div style={{ background: '#112B36', borderRadius: 12, padding: 20, marginBottom: 20, borderLeft: '4px solid #FF6B2C' }}>
              <div style={{ fontSize: 20, fontWeight: 'bold', marginBottom: 8 }}>{selectedCustomer.name}</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, fontSize: 16 }}>
                <div>
                  <div style={{ color: '#8899A6', marginBottom: 4 }}>信用额度</div>
                  <div style={{ fontWeight: 'bold' }}>{fen2yuan(selectedCustomer.creditLimitFen)}</div>
                </div>
                <div>
                  <div style={{ color: '#8899A6', marginBottom: 4 }}>已使用</div>
                  <div style={{ fontWeight: 'bold', color: '#BA7517' }}>{fen2yuan(selectedCustomer.usedFen)}</div>
                </div>
                <div>
                  <div style={{ color: '#8899A6', marginBottom: 4 }}>可用余额</div>
                  <div style={{ fontWeight: 'bold', color: '#0F6E56' }}>{fen2yuan(availableFen)}</div>
                </div>
              </div>
            </div>

            {/* 挂账金额 */}
            <div style={{ background: '#112B36', borderRadius: 12, padding: 20, marginBottom: 20, textAlign: 'center' }}>
              <div style={{ color: '#8899A6', fontSize: 16, marginBottom: 8 }}>本次挂账金额</div>
              <div style={{ fontSize: 36, fontWeight: 'bold', color: '#FF6B2C' }}>{fen2yuan(finalFen)}</div>
              <div style={{ color: '#8899A6', fontSize: 16, marginTop: 8 }}>
                挂账后可用额度: <span style={{ color: '#0F6E56', fontWeight: 'bold' }}>{fen2yuan(availableFen - finalFen)}</span>
              </div>
            </div>

            {/* 签单人 */}
            <div style={{ marginBottom: 20 }}>
              <label style={{ display: 'block', fontSize: 18, marginBottom: 8, fontWeight: 'bold' }}>
                签单人姓名 <span style={{ color: '#A32D2D' }}>*</span>
              </label>
              <input
                type="text"
                placeholder="请输入签单人姓名（必填）"
                value={signerName}
                onChange={(e) => setSignerName(e.target.value)}
                style={{
                  width: '100%', padding: 16, fontSize: 18, border: '2px solid #333',
                  borderRadius: 12, background: '#112228', color: '#fff',
                  boxSizing: 'border-box', outline: 'none',
                }}
                onFocus={(e) => { e.currentTarget.style.borderColor = '#FF6B2C'; }}
                onBlur={(e) => { e.currentTarget.style.borderColor = '#333'; }}
              />
              {signerName.trim().length === 0 && (
                <div style={{ color: '#BA7517', fontSize: 16, marginTop: 6 }}>签单人姓名为必填项</div>
              )}
            </div>

            {/* 操作按钮 */}
            <div style={{ display: 'flex', gap: 12, marginTop: 'auto' }}>
              <button
                onClick={() => { setStep('search'); setSelectedCustomer(null); setSignerName(''); }}
                style={{ ...navBtn, flex: 1, background: '#333' }}
              >
                重新选择
              </button>
              <button
                onClick={handleConfirm}
                disabled={!canPay || submitting}
                style={{
                  ...navBtn, flex: 2,
                  background: canPay && !submitting ? '#FF6B2C' : '#444',
                  cursor: canPay && !submitting ? 'pointer' : 'not-allowed',
                  fontSize: 20, fontWeight: 'bold',
                }}
                onPointerDown={(e) => { if (canPay && !submitting) e.currentTarget.style.transform = 'scale(0.97)'; }}
                onPointerUp={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
                onPointerLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
              >
                {submitting ? '处理中...' : '确认挂账'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const navBtn: React.CSSProperties = {
  padding: 16, border: 'none', borderRadius: 12, color: '#fff',
  fontSize: 18, cursor: 'pointer', transition: 'transform 200ms ease',
  minHeight: 56,
};
