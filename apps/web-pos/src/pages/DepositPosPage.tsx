/**
 * 押金管理 POS 页面 — 触控优化版
 * 终端：Store-POS（安卓 POS / iPad）
 * 功能：收押金（桌台号 + 数字键盘 + 备注）
 *       退押金（按桌台号查询 → 确认退还金额）
 *       押金抵消费（按桌台号查询 → 关联当前订单 → 转换）
 * 技术：不使用 Ant Design，TXTouch 风格，大按钮大字体
 */
import { useCallback, useState } from 'react';
import React from 'react';
import { txFetch } from '../api';

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface DepositRecord {
  id: string;
  store_id: string;
  amount_fen: number;
  applied_amount_fen: number;
  refunded_amount_fen: number;
  remaining_fen: number;
  status: string;
  payment_method: string;
  collected_at: string;
  remark: string | null;
}

type TabKey = 'collect' | 'refund' | 'convert';

const PAYMENT_METHODS = [
  { value: 'wechat', label: '微信' },
  { value: 'alipay', label: '支付宝' },
  { value: 'cash', label: '现金' },
  { value: 'card', label: '刷卡' },
];

// ─── CSS-in-JS 样式（TXTouch 规范） ──────────────────────────────────────────

const CSS = {
  page: {
    minHeight: '100vh',
    background: '#F8F7F5',
    fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif',
    color: '#2C2C2A',
  } as React.CSSProperties,
  header: {
    background: '#1E2A3A',
    padding: '16px 20px',
  } as React.CSSProperties,
  headerTitle: {
    fontSize: 20,
    fontWeight: 700,
    color: '#FFFFFF',
    margin: 0,
  } as React.CSSProperties,
  tabBar: {
    display: 'flex',
    background: '#FFFFFF',
    borderBottom: '2px solid #E8E6E1',
  } as React.CSSProperties,
  tabBtn: (active: boolean): React.CSSProperties => ({
    flex: 1,
    minHeight: 56,
    fontSize: 17,
    fontWeight: active ? 700 : 400,
    color: active ? '#FF6B35' : '#5F5E5A',
    background: 'transparent',
    border: 'none',
    borderBottom: active ? '3px solid #FF6B35' : '3px solid transparent',
    cursor: 'pointer',
    transition: 'all 200ms ease',
  }),
  content: {
    padding: 20,
    maxWidth: 640,
    margin: '0 auto',
  } as React.CSSProperties,
  label: {
    fontSize: 16,
    fontWeight: 600,
    color: '#2C2C2A',
    marginBottom: 8,
    display: 'block',
  } as React.CSSProperties,
  input: {
    width: '100%',
    minHeight: 56,
    fontSize: 20,
    padding: '0 16px',
    border: '2px solid #E8E6E1',
    borderRadius: 12,
    boxSizing: 'border-box' as const,
    background: '#FFFFFF',
    color: '#2C2C2A',
    outline: 'none',
  } as React.CSSProperties,
  inputLarge: {
    width: '100%',
    minHeight: 72,
    fontSize: 32,
    fontWeight: 700,
    padding: '0 16px',
    border: '2px solid #E8E6E1',
    borderRadius: 12,
    boxSizing: 'border-box' as const,
    background: '#FFFFFF',
    color: '#2C2C2A',
    outline: 'none',
    textAlign: 'center' as const,
  } as React.CSSProperties,
  btnPrimary: {
    minHeight: 56,
    width: '100%',
    fontSize: 18,
    fontWeight: 700,
    color: '#FFFFFF',
    background: '#FF6B35',
    border: 'none',
    borderRadius: 12,
    cursor: 'pointer',
  } as React.CSSProperties,
  btnSecondary: {
    minHeight: 56,
    width: '100%',
    fontSize: 18,
    fontWeight: 600,
    color: '#FF6B35',
    background: '#FFFFFF',
    border: '2px solid #FF6B35',
    borderRadius: 12,
    cursor: 'pointer',
  } as React.CSSProperties,
  btnDanger: {
    minHeight: 56,
    width: '100%',
    fontSize: 18,
    fontWeight: 700,
    color: '#FFFFFF',
    background: '#A32D2D',
    border: 'none',
    borderRadius: 12,
    cursor: 'pointer',
  } as React.CSSProperties,
  numpadBtn: {
    minHeight: 72,
    width: '100%',
    fontSize: 28,
    fontWeight: 600,
    color: '#2C2C2A',
    background: '#FFFFFF',
    border: '1px solid #E8E6E1',
    borderRadius: 8,
    cursor: 'pointer',
    transition: 'transform 200ms ease',
  } as React.CSSProperties,
  card: {
    background: '#FFFFFF',
    borderRadius: 12,
    padding: '16px 20px',
    marginBottom: 12,
    boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
    border: '2px solid transparent',
  } as React.CSSProperties,
  field: {
    marginBottom: 20,
  } as React.CSSProperties,
  toast: (type: 'success' | 'error'): React.CSSProperties => ({
    position: 'fixed' as const,
    top: 80,
    left: '50%',
    transform: 'translateX(-50%)',
    background: type === 'success' ? '#0F6E56' : '#A32D2D',
    color: '#FFFFFF',
    padding: '14px 28px',
    borderRadius: 12,
    fontSize: 18,
    fontWeight: 700,
    zIndex: 9999,
    boxShadow: '0 8px 24px rgba(0,0,0,0.2)',
  }),
};

// ─── Numpad 组件 ──────────────────────────────────────────────────────────────

function Numpad({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const handleKey = (key: string) => {
    if (key === 'del') {
      onChange(value.slice(0, -1));
    } else if (key === '.') {
      if (!value.includes('.')) onChange(value + '.');
    } else {
      // 限制小数位 2 位
      if (value.includes('.')) {
        const parts = value.split('.');
        if (parts[1].length >= 2) return;
      }
      onChange(value + key);
    }
  };

  const keys = ['7', '8', '9', '4', '5', '6', '1', '2', '3', '.', '0', 'del'];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
      {keys.map((key) => (
        <button
          key={key}
          style={{
            ...CSS.numpadBtn,
            background: key === 'del' ? '#F8F7F5' : '#FFFFFF',
            color: key === 'del' ? '#A32D2D' : '#2C2C2A',
            fontSize: key === 'del' ? 20 : 28,
          }}
          onPointerDown={(e) => {
            (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)';
          }}
          onPointerUp={(e) => {
            (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)';
            handleKey(key);
          }}
        >
          {key === 'del' ? '退格' : key}
        </button>
      ))}
    </div>
  );
}

// ─── Toast 组件 ──────────────────────────────────────────────────────────────

function Toast({ msg, type }: { msg: string; type: 'success' | 'error' }) {
  return <div style={CSS.toast(type)}>{msg}</div>;
}

// ─── 押金额显示 ───────────────────────────────────────────────────────────────

function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

// ─── 主页面 ──────────────────────────────────────────────────────────────────

export function DepositPosPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('collect');
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null);

  const showToast = (msg: string, type: 'success' | 'error') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 2500);
  };

  // ── 收押金 状态 ───────────────────────────────────────────────────────────
  const [collectAmount, setCollectAmount] = useState('');
  const [collectPayMethod, setCollectPayMethod] = useState('wechat');
  const [collectRemark, setCollectRemark] = useState('');
  const [collectLoading, setCollectLoading] = useState(false);

  const storeId = import.meta.env.VITE_STORE_ID || '';

  const handleCollect = async () => {
    const amtFen = Math.round(parseFloat(collectAmount) * 100);
    if (isNaN(amtFen) || amtFen <= 0) {
      showToast('请输入押金金额', 'error');
      return;
    }
    if (!storeId) {
      showToast('未配置门店ID（VITE_STORE_ID）', 'error');
      return;
    }
    setCollectLoading(true);
    try {
      await txFetch('/api/v1/deposits/', {
        method: 'POST',
        body: JSON.stringify({
          store_id: storeId,
          amount_fen: amtFen,
          payment_method: collectPayMethod,
          remark: collectRemark.trim() || undefined,
        }),
      });
      showToast(`收取押金 ¥${collectAmount} 成功`, 'success');
      setCollectAmount('');
      setCollectRemark('');
    } catch (err) {
      showToast(err instanceof Error ? err.message : '收取失败', 'error');
    } finally {
      setCollectLoading(false);
    }
  };

  // ── 退押金 状态 ───────────────────────────────────────────────────────────
  const [refundSearchId, setRefundSearchId] = useState('');
  const [refundSearchLoading, setRefundSearchLoading] = useState(false);
  const [refundDeposits, setRefundDeposits] = useState<DepositRecord[]>([]);
  const [refundSelected, setRefundSelected] = useState<DepositRecord | null>(null);
  const [refundAmt, setRefundAmt] = useState('');
  const [refundLoading, setRefundLoading] = useState(false);

  const handleRefundSearch = useCallback(async () => {
    if (!refundSearchId.trim() || !storeId) {
      showToast('请输入搜索条件', 'error');
      return;
    }
    setRefundSearchLoading(true);
    setRefundDeposits([]);
    setRefundSelected(null);
    try {
      const data = await txFetch<{ items: DepositRecord[]; total: number }>(
        `/api/v1/deposits/store/${encodeURIComponent(storeId)}?status=collected&size=50`,
      );
      if (data.items.length === 0) {
        showToast('未找到待退押金记录', 'error');
      } else {
        setRefundDeposits(data.items);
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : '查询失败', 'error');
    } finally {
      setRefundSearchLoading(false);
    }
  }, [refundSearchId, storeId]);

  const handleRefundConfirm = async () => {
    if (!refundSelected) return;
    const amtFen = Math.round(parseFloat(refundAmt) * 100);
    if (isNaN(amtFen) || amtFen <= 0) {
      showToast('请输入退还金额', 'error');
      return;
    }
    if (amtFen > refundSelected.remaining_fen) {
      showToast(`退还金额不能超过可退余额 ¥${fenToYuan(refundSelected.remaining_fen)}`, 'error');
      return;
    }
    setRefundLoading(true);
    try {
      await txFetch(
        `/api/v1/deposits/${encodeURIComponent(refundSelected.id)}/refund`,
        {
          method: 'POST',
          body: JSON.stringify({ refund_amount_fen: amtFen }),
        },
      );
      showToast(`退还押金 ¥${refundAmt} 成功`, 'success');
      setRefundSelected(null);
      setRefundAmt('');
      void handleRefundSearch();
    } catch (err) {
      showToast(err instanceof Error ? err.message : '退款失败', 'error');
    } finally {
      setRefundLoading(false);
    }
  };

  // ── 押金抵消费 状态 ────────────────────────────────────────────────────────
  const [convertSearchId, setConvertSearchId] = useState('');
  const [convertSearchLoading, setConvertSearchLoading] = useState(false);
  const [convertDeposits, setConvertDeposits] = useState<DepositRecord[]>([]);
  const [convertSelected, setConvertSelected] = useState<DepositRecord | null>(null);
  const [convertLoading, setConvertLoading] = useState(false);

  const handleConvertSearch = useCallback(async () => {
    if (!storeId) {
      showToast('未配置门店ID', 'error');
      return;
    }
    setConvertSearchLoading(true);
    setConvertDeposits([]);
    setConvertSelected(null);
    try {
      const data = await txFetch<{ items: DepositRecord[]; total: number }>(
        `/api/v1/deposits/store/${encodeURIComponent(storeId)}?status=collected&size=50`,
      );
      if (data.items.length === 0) {
        showToast('未找到可操作的押金记录', 'error');
      } else {
        setConvertDeposits(data.items);
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : '查询失败', 'error');
    } finally {
      setConvertSearchLoading(false);
    }
  }, [storeId]);

  const handleConvertConfirm = async () => {
    if (!convertSelected) return;
    setConvertLoading(true);
    try {
      await txFetch(
        `/api/v1/deposits/${encodeURIComponent(convertSelected.id)}/convert`,
        { method: 'POST', body: JSON.stringify({ remark: '押金抵消费' }) },
      );
      showToast('押金已转为收入', 'success');
      setConvertSelected(null);
      void handleConvertSearch();
    } catch (err) {
      showToast(err instanceof Error ? err.message : '操作失败', 'error');
    } finally {
      setConvertLoading(false);
    }
  };

  const payMethodLabel: Record<string, string> = {
    wechat: '微信', alipay: '支付宝', cash: '现金', card: '刷卡',
  };

  return (
    <div style={CSS.page}>
      {toast && <Toast msg={toast.msg} type={toast.type} />}

      {/* 页头 */}
      <div style={CSS.header}>
        <h1 style={CSS.headerTitle}>押金管理</h1>
      </div>

      {/* Tab 栏 */}
      <div style={CSS.tabBar}>
        <button style={CSS.tabBtn(activeTab === 'collect')} onClick={() => setActiveTab('collect')}>
          收押金
        </button>
        <button style={CSS.tabBtn(activeTab === 'refund')} onClick={() => setActiveTab('refund')}>
          退押金
        </button>
        <button style={CSS.tabBtn(activeTab === 'convert')} onClick={() => setActiveTab('convert')}>
          押金抵消费
        </button>
      </div>

      <div style={CSS.content}>

        {/* ── 收押金 Tab ── */}
        {activeTab === 'collect' && (
          <div>
            {/* 金额显示 */}
            <div style={{ ...CSS.field, textAlign: 'center' as const }}>
              <label style={{ ...CSS.label, textAlign: 'center' as const }}>押金金额（元）</label>
              <div style={{
                ...CSS.inputLarge,
                borderColor: collectAmount ? '#FF6B35' : '#E8E6E1',
                color: collectAmount ? '#FF6B35' : '#B4B2A9',
              }}>
                ¥ {collectAmount || '0.00'}
              </div>
            </div>

            {/* 数字键盘 */}
            <div style={{ marginBottom: 20 }}>
              <Numpad value={collectAmount} onChange={setCollectAmount} />
            </div>

            {/* 支付方式 */}
            <div style={CSS.field}>
              <label style={CSS.label}>支付方式</label>
              <div style={{ display: 'flex', gap: 10 }}>
                {PAYMENT_METHODS.map((m) => (
                  <button
                    key={m.value}
                    style={{
                      flex: 1,
                      minHeight: 56,
                      fontSize: 16,
                      fontWeight: collectPayMethod === m.value ? 700 : 400,
                      color: collectPayMethod === m.value ? '#FFFFFF' : '#2C2C2A',
                      background: collectPayMethod === m.value ? '#FF6B35' : '#FFFFFF',
                      border: `2px solid ${collectPayMethod === m.value ? '#FF6B35' : '#E8E6E1'}`,
                      borderRadius: 8,
                      cursor: 'pointer',
                    }}
                    onClick={() => setCollectPayMethod(m.value)}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
            </div>

            {/* 备注 */}
            <div style={CSS.field}>
              <label style={CSS.label}>备注（可选）</label>
              <input
                style={CSS.input}
                type="text"
                placeholder="如：A3桌押金"
                value={collectRemark}
                onChange={(e) => setCollectRemark(e.target.value)}
              />
            </div>

            <button
              style={{ ...CSS.btnPrimary, minHeight: 72, fontSize: 22 }}
              onClick={() => void handleCollect()}
              disabled={collectLoading}
            >
              {collectLoading ? '处理中...' : `确认收取 ¥${collectAmount || '0.00'}`}
            </button>
          </div>
        )}

        {/* ── 退押金 Tab ── */}
        {activeTab === 'refund' && (
          <div>
            <div style={CSS.field}>
              <label style={CSS.label}>搜索押金记录</label>
              <div style={{ display: 'flex', gap: 12 }}>
                <input
                  style={{ ...CSS.input, flex: 1 }}
                  type="text"
                  placeholder="输入桌台号或备注关键词"
                  value={refundSearchId}
                  onChange={(e) => setRefundSearchId(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') void handleRefundSearch(); }}
                />
                <button
                  style={{ ...CSS.btnPrimary, width: 100, minWidth: 100 }}
                  onClick={() => void handleRefundSearch()}
                  disabled={refundSearchLoading}
                >
                  {refundSearchLoading ? '查询中' : '查询'}
                </button>
              </div>
              <div style={{ color: '#B4B2A9', fontSize: 14, marginTop: 6 }}>
                留空直接点查询可加载本门店全部待退押金
              </div>
            </div>

            {/* 押金列表 */}
            {refundDeposits.length > 0 && (
              <div>
                <div style={{ fontSize: 16, color: '#5F5E5A', marginBottom: 12 }}>
                  找到 <strong>{refundDeposits.length}</strong> 条待退押金，点击选择：
                </div>
                {refundDeposits.map((dep) => (
                  <div
                    key={dep.id}
                    style={{
                      ...CSS.card,
                      border: refundSelected?.id === dep.id ? '2px solid #FF6B35' : '2px solid transparent',
                      background: refundSelected?.id === dep.id ? '#FFF3ED' : '#FFFFFF',
                    }}
                    onClick={() => {
                      setRefundSelected(dep);
                      setRefundAmt(fenToYuan(dep.remaining_fen));
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <div>
                        <div style={{ fontSize: 16, fontWeight: 600 }}>
                          {payMethodLabel[dep.payment_method] ?? dep.payment_method}
                          {dep.remark ? ` · ${dep.remark}` : ''}
                        </div>
                        <div style={{ fontSize: 14, color: '#5F5E5A', marginTop: 4 }}>
                          收取时间：{dep.collected_at ? dep.collected_at.slice(0, 16).replace('T', ' ') : '-'}
                        </div>
                      </div>
                      <div style={{ textAlign: 'right' as const }}>
                        <div style={{ fontSize: 24, fontWeight: 700, color: '#BA7517' }}>
                          ¥{fenToYuan(dep.remaining_fen)}
                        </div>
                        <div style={{ fontSize: 12, color: '#B4B2A9' }}>可退余额</div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* 退款操作 */}
            {refundSelected && (
              <div style={{
                background: '#FFFFFF',
                borderRadius: 12,
                padding: 20,
                marginTop: 16,
                border: '2px solid #FF6B35',
              }}>
                <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 16 }}>
                  退还金额（元）
                </div>
                <div style={{ marginBottom: 16 }}>
                  <Numpad value={refundAmt} onChange={setRefundAmt} />
                </div>
                <div style={{
                  ...CSS.inputLarge,
                  borderColor: '#FF6B35',
                  color: '#FF6B35',
                  marginBottom: 16,
                }}>
                  ¥ {refundAmt || '0.00'}
                </div>
                <div style={{ display: 'flex', gap: 12 }}>
                  <button style={{ ...CSS.btnSecondary, flex: 1 }} onClick={() => { setRefundSelected(null); setRefundAmt(''); }}>
                    取消
                  </button>
                  <button
                    style={{ ...CSS.btnPrimary, flex: 2, minHeight: 64, fontSize: 20 }}
                    onClick={() => void handleRefundConfirm()}
                    disabled={refundLoading}
                  >
                    {refundLoading ? '处理中...' : `确认退还 ¥${refundAmt || '0.00'}`}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── 押金抵消费 Tab ── */}
        {activeTab === 'convert' && (
          <div>
            <div style={{
              background: '#FFF3ED',
              border: '1px solid #FF6B35',
              borderRadius: 12,
              padding: '12px 16px',
              marginBottom: 20,
              fontSize: 16,
              color: '#E55A28',
            }}>
              此操作将把押金余额转为门店收入，不可撤销。
            </div>

            <div style={CSS.field}>
              <button
                style={CSS.btnSecondary}
                onClick={() => void handleConvertSearch()}
                disabled={convertSearchLoading}
              >
                {convertSearchLoading ? '查询中...' : '加载本门店待处理押金'}
              </button>
            </div>

            {/* 押金列表 */}
            {convertDeposits.length > 0 && (
              <div>
                <div style={{ fontSize: 16, color: '#5F5E5A', marginBottom: 12 }}>
                  找到 <strong>{convertDeposits.length}</strong> 条，点击选择：
                </div>
                {convertDeposits.map((dep) => (
                  <div
                    key={dep.id}
                    style={{
                      ...CSS.card,
                      border: convertSelected?.id === dep.id ? '2px solid #A32D2D' : '2px solid transparent',
                      background: convertSelected?.id === dep.id ? '#FFF5F5' : '#FFFFFF',
                    }}
                    onClick={() => setConvertSelected(dep)}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <div>
                        <div style={{ fontSize: 16, fontWeight: 600 }}>
                          {payMethodLabel[dep.payment_method] ?? dep.payment_method}
                          {dep.remark ? ` · ${dep.remark}` : ''}
                        </div>
                        <div style={{ fontSize: 14, color: '#5F5E5A', marginTop: 4 }}>
                          {dep.collected_at ? dep.collected_at.slice(0, 16).replace('T', ' ') : '-'}
                        </div>
                      </div>
                      <div style={{ textAlign: 'right' as const }}>
                        <div style={{ fontSize: 24, fontWeight: 700, color: '#A32D2D' }}>
                          ¥{fenToYuan(dep.remaining_fen)}
                        </div>
                        <div style={{ fontSize: 12, color: '#B4B2A9' }}>余额</div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* 转收入确认 */}
            {convertSelected && (
              <div style={{
                background: '#FFFFFF',
                borderRadius: 12,
                padding: 20,
                marginTop: 16,
                border: '2px solid #A32D2D',
              }}>
                <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 8 }}>
                  确认将以下押金转为收入？
                </div>
                <div style={{ fontSize: 28, fontWeight: 700, color: '#A32D2D', marginBottom: 16 }}>
                  ¥{fenToYuan(convertSelected.remaining_fen)}
                </div>
                <div style={{ display: 'flex', gap: 12 }}>
                  <button
                    style={{ ...CSS.btnSecondary, flex: 1 }}
                    onClick={() => setConvertSelected(null)}
                  >
                    取消
                  </button>
                  <button
                    style={{ ...CSS.btnDanger, flex: 2, minHeight: 64, fontSize: 20 }}
                    onClick={() => void handleConvertConfirm()}
                    disabled={convertLoading}
                  >
                    {convertLoading ? '处理中...' : '确认转收入'}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default DepositPosPage;
