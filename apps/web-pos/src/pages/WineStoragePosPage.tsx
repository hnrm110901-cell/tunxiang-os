/**
 * 存酒管理 POS 页面 — 触控优化版
 * 终端：Store-POS（安卓 POS / iPad）
 * 功能：取酒（按手机号查询 → 选记录 → 输数量 → 确认）
 *       存酒（填信息 → 存入）
 * 技术：不使用 Ant Design，TXTouch 风格，大按钮大字体
 */
import React, { useCallback, useState } from 'react';
import { txFetch } from '../api';

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface WineRecord {
  id: string;
  wine_name: string;
  wine_category: string;
  quantity: number;
  original_qty: number;
  unit: string;
  status: string;
  stored_at: string;
  expires_at: string | null;
  cabinet_position: string | null;
}

type TabKey = 'retrieve' | 'store';

// ─── CSS-in-JS 样式常量（TXTouch 规范） ──────────────────────────────────────

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
    display: 'flex',
    alignItems: 'center',
    gap: 12,
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
    fontSize: 18,
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
    transition: 'transform 200ms ease',
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
  card: {
    background: '#FFFFFF',
    borderRadius: 12,
    padding: '16px 20px',
    marginBottom: 12,
    boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
    border: '2px solid transparent',
  } as React.CSSProperties,
  cardSelected: {
    background: '#FFF3ED',
    borderRadius: 12,
    padding: '16px 20px',
    marginBottom: 12,
    boxShadow: '0 4px 12px rgba(255,107,53,0.15)',
    border: '2px solid #FF6B35',
  } as React.CSSProperties,
  statusBadge: (status: string): React.CSSProperties => ({
    display: 'inline-block',
    padding: '2px 10px',
    borderRadius: 20,
    fontSize: 14,
    fontWeight: 600,
    background:
      status === 'stored' ? '#E6F7F0'
      : status === 'partially_retrieved' ? '#FFF7E6'
      : '#F5F5F5',
    color:
      status === 'stored' ? '#0F6E56'
      : status === 'partially_retrieved' ? '#BA7517'
      : '#5F5E5A',
  }),
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

// ─── Toast 组件 ──────────────────────────────────────────────────────────────

function Toast({ msg, type }: { msg: string; type: 'success' | 'error' }) {
  return <div style={CSS.toast(type)}>{msg}</div>;
}

// ─── 存酒 POS 主页面 ─────────────────────────────────────────────────────────

export function WineStoragePosPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('retrieve');

  // Toast
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null);
  const showToast = (msg: string, type: 'success' | 'error') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 2500);
  };

  // 取酒 Tab 状态
  const [phone, setPhone] = useState('');
  const [searchLoading, setSearchLoading] = useState(false);
  const [wineList, setWineList] = useState<WineRecord[]>([]);
  const [selectedWine, setSelectedWine] = useState<WineRecord | null>(null);
  const [retrieveQty, setRetrieveQty] = useState('1');
  const [confirmLoading, setConfirmLoading] = useState(false);

  // 存酒 Tab 状态
  const [storePhone, setStorePhone] = useState('');
  const [storeWineName, setStoreWineName] = useState('');
  const [storeCategory, setStoreCategory] = useState('白酒');
  const [storeQty, setStoreQty] = useState('');
  const [storeExpiresDays, setStoreExpiresDays] = useState('180');
  const [storeNotes, setStoreNotes] = useState('');
  const [storeLoading, setStoreLoading] = useState(false);

  // 按手机号（实际为 customer_id）查询存酒
  const handleSearch = useCallback(async () => {
    if (!phone.trim()) {
      showToast('请输入手机号或客户ID', 'error');
      return;
    }
    setSearchLoading(true);
    setWineList([]);
    setSelectedWine(null);
    try {
      const data = await txFetch<{ items: WineRecord[]; total: number }>(
        `/api/v1/wine-storage/customer/${encodeURIComponent(phone.trim())}?status=stored&size=50`,
      );
      if (data.items.length === 0) {
        showToast('未找到该客户的存酒记录', 'error');
      } else {
        setWineList(data.items);
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : '查询失败', 'error');
    } finally {
      setSearchLoading(false);
    }
  }, [phone]);

  // 确认取酒
  const handleRetrieveConfirm = async () => {
    if (!selectedWine) return;
    const qty = parseFloat(retrieveQty);
    if (isNaN(qty) || qty <= 0) {
      showToast('请输入有效的取出数量', 'error');
      return;
    }
    if (qty > selectedWine.quantity) {
      showToast(`取出数量不能超过剩余量 ${selectedWine.quantity} ${selectedWine.unit}`, 'error');
      return;
    }
    setConfirmLoading(true);
    try {
      await txFetch(
        `/api/v1/wine-storage/${encodeURIComponent(selectedWine.id)}/retrieve`,
        {
          method: 'POST',
          body: JSON.stringify({ quantity: qty }),
        },
      );
      showToast(`取酒成功：${selectedWine.wine_name} × ${qty} ${selectedWine.unit}`, 'success');
      setSelectedWine(null);
      setRetrieveQty('1');
      // 刷新列表
      void handleSearch();
    } catch (err) {
      showToast(err instanceof Error ? err.message : '取酒失败', 'error');
    } finally {
      setConfirmLoading(false);
    }
  };

  // 存酒（需要后端完整信息，POS 端简化流程：需要真实 customerId & orderId）
  const handleStoreWine = async () => {
    if (!storePhone.trim() || !storeWineName.trim() || !storeQty) {
      showToast('请填写完整信息', 'error');
      return;
    }
    const qty = parseFloat(storeQty);
    if (isNaN(qty) || qty <= 0) {
      showToast('请输入有效数量', 'error');
      return;
    }
    setStoreLoading(true);
    try {
      // POS 端简化：customer_id 和 source_order_id 在实际使用中需从当前订单上下文注入
      // 此处以 phone 作为 customer_id 占位，实际 production 通过会员查询获取
      await txFetch(
        '/api/v1/wine-storage/',
        {
          method: 'POST',
          body: JSON.stringify({
            customer_id: storePhone.trim(),
            source_order_id: '00000000-0000-0000-0000-000000000000',
            wine_name: storeWineName.trim(),
            wine_category: storeCategory,
            quantity: qty,
            expires_days: parseInt(storeExpiresDays, 10) || 180,
            notes: storeNotes.trim() || undefined,
          }),
        },
      );
      showToast('存酒成功', 'success');
      setStorePhone('');
      setStoreWineName('');
      setStoreQty('');
      setStoreNotes('');
    } catch (err) {
      showToast(err instanceof Error ? err.message : '存酒失败', 'error');
    } finally {
      setStoreLoading(false);
    }
  };

  const statusLabel: Record<string, string> = {
    stored: '存储中',
    partially_retrieved: '部分取出',
  };

  return (
    <div style={CSS.page}>
      {toast && <Toast msg={toast.msg} type={toast.type} />}

      {/* 页头 */}
      <div style={CSS.header}>
        <h1 style={CSS.headerTitle}>存酒管理</h1>
      </div>

      {/* Tab 栏 */}
      <div style={CSS.tabBar}>
        <button style={CSS.tabBtn(activeTab === 'retrieve')} onClick={() => setActiveTab('retrieve')}>
          取酒
        </button>
        <button style={CSS.tabBtn(activeTab === 'store')} onClick={() => setActiveTab('store')}>
          存酒
        </button>
      </div>

      {/* 内容区 */}
      <div style={CSS.content}>

        {/* ── 取酒 Tab ── */}
        {activeTab === 'retrieve' && (
          <div>
            {/* 手机号输入 */}
            <div style={CSS.field}>
              <label style={CSS.label}>客户手机号 / ID</label>
              <div style={{ display: 'flex', gap: 12 }}>
                <input
                  style={{ ...CSS.input, flex: 1 }}
                  type="tel"
                  placeholder="输入客户手机号或ID"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') void handleSearch(); }}
                />
                <button
                  style={{
                    ...CSS.btnPrimary,
                    width: 100,
                    minWidth: 100,
                  }}
                  onClick={() => void handleSearch()}
                  disabled={searchLoading}
                >
                  {searchLoading ? '查询中' : '查询'}
                </button>
              </div>
            </div>

            {/* 存酒列表 */}
            {wineList.length > 0 && (
              <div>
                <div style={{ fontSize: 16, color: '#5F5E5A', marginBottom: 12 }}>
                  找到 <strong>{wineList.length}</strong> 条存酒记录，点击选择：
                </div>
                {wineList.map((item) => (
                  <div
                    key={item.id}
                    style={selectedWine?.id === item.id ? CSS.cardSelected : CSS.card}
                    onClick={() => {
                      setSelectedWine(item);
                      setRetrieveQty('1');
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <div>
                        <div style={{ fontSize: 20, fontWeight: 700, color: '#2C2C2A', marginBottom: 4 }}>
                          {item.wine_name}
                        </div>
                        <div style={{ fontSize: 16, color: '#5F5E5A' }}>
                          {item.wine_category} · 柜位：{item.cabinet_position || '未设置'}
                        </div>
                        {item.expires_at && (
                          <div style={{ fontSize: 14, color: '#B4B2A9', marginTop: 4 }}>
                            到期：{item.expires_at.slice(0, 10)}
                          </div>
                        )}
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <div style={{ fontSize: 28, fontWeight: 700, color: '#0F6E56' }}>
                          {item.quantity}
                        </div>
                        <div style={{ fontSize: 14, color: '#5F5E5A' }}>{item.unit} 剩余</div>
                        <div style={{ marginTop: 6 }}>
                          <span style={CSS.statusBadge(item.status)}>
                            {statusLabel[item.status] ?? item.status}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* 取酒操作区 */}
            {selectedWine && (
              <div style={{
                background: '#FFFFFF',
                borderRadius: 12,
                padding: '20px',
                marginTop: 16,
                border: '2px solid #FF6B35',
              }}>
                <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 16 }}>
                  取出：{selectedWine.wine_name}
                </div>
                <div style={CSS.field}>
                  <label style={CSS.label}>
                    取出数量（剩余 {selectedWine.quantity} {selectedWine.unit}）
                  </label>
                  <input
                    style={CSS.input}
                    type="number"
                    min="0.1"
                    max={selectedWine.quantity}
                    step="0.1"
                    value={retrieveQty}
                    onChange={(e) => setRetrieveQty(e.target.value)}
                  />
                </div>
                <div style={{ display: 'flex', gap: 12, marginTop: 8 }}>
                  <button
                    style={{ ...CSS.btnSecondary, flex: 1 }}
                    onClick={() => setSelectedWine(null)}
                  >
                    取消
                  </button>
                  <button
                    style={{ ...CSS.btnPrimary, flex: 2 }}
                    onClick={() => void handleRetrieveConfirm()}
                    disabled={confirmLoading}
                  >
                    {confirmLoading ? '处理中...' : '确认取酒'}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── 存酒 Tab ── */}
        {activeTab === 'store' && (
          <div>
            <div style={CSS.field}>
              <label style={CSS.label}>客户手机号 / ID *</label>
              <input
                style={CSS.input}
                type="tel"
                placeholder="输入客户手机号"
                value={storePhone}
                onChange={(e) => setStorePhone(e.target.value)}
              />
            </div>

            <div style={CSS.field}>
              <label style={CSS.label}>酒品名称 *</label>
              <input
                style={CSS.input}
                type="text"
                placeholder="如：茅台 53° 飞天"
                value={storeWineName}
                onChange={(e) => setStoreWineName(e.target.value)}
              />
            </div>

            <div style={CSS.field}>
              <label style={CSS.label}>酒类 *</label>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' as const }}>
                {['白酒', '红酒', '啤酒', '洋酒', '其他'].map((cat) => (
                  <button
                    key={cat}
                    style={{
                      minHeight: 48,
                      padding: '0 20px',
                      fontSize: 16,
                      fontWeight: storeCategory === cat ? 700 : 400,
                      color: storeCategory === cat ? '#FFFFFF' : '#2C2C2A',
                      background: storeCategory === cat ? '#FF6B35' : '#FFFFFF',
                      border: `2px solid ${storeCategory === cat ? '#FF6B35' : '#E8E6E1'}`,
                      borderRadius: 8,
                      cursor: 'pointer',
                    }}
                    onClick={() => setStoreCategory(cat)}
                  >
                    {cat}
                  </button>
                ))}
              </div>
            </div>

            <div style={CSS.field}>
              <label style={CSS.label}>存入数量（瓶）*</label>
              <input
                style={CSS.input}
                type="number"
                min="0.1"
                step="0.1"
                placeholder="0"
                value={storeQty}
                onChange={(e) => setStoreQty(e.target.value)}
              />
            </div>

            <div style={CSS.field}>
              <label style={CSS.label}>有效期（天）</label>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' as const }}>
                {[90, 180, 365].map((d) => (
                  <button
                    key={d}
                    style={{
                      minHeight: 48,
                      padding: '0 20px',
                      fontSize: 16,
                      fontWeight: storeExpiresDays === String(d) ? 700 : 400,
                      color: storeExpiresDays === String(d) ? '#FFFFFF' : '#2C2C2A',
                      background: storeExpiresDays === String(d) ? '#FF6B35' : '#FFFFFF',
                      border: `2px solid ${storeExpiresDays === String(d) ? '#FF6B35' : '#E8E6E1'}`,
                      borderRadius: 8,
                      cursor: 'pointer',
                    }}
                    onClick={() => setStoreExpiresDays(String(d))}
                  >
                    {d}天
                  </button>
                ))}
                <input
                  style={{ ...CSS.input, flex: 1, minWidth: 80, fontSize: 16 }}
                  type="number"
                  min="1"
                  placeholder="自定义"
                  value={[90, 180, 365].includes(parseInt(storeExpiresDays)) ? '' : storeExpiresDays}
                  onChange={(e) => setStoreExpiresDays(e.target.value)}
                />
              </div>
            </div>

            <div style={CSS.field}>
              <label style={CSS.label}>备注（可选）</label>
              <input
                style={CSS.input}
                type="text"
                placeholder="如：柜位A3"
                value={storeNotes}
                onChange={(e) => setStoreNotes(e.target.value)}
              />
            </div>

            <button
              style={CSS.btnPrimary}
              onClick={() => void handleStoreWine()}
              disabled={storeLoading}
            >
              {storeLoading ? '存入中...' : '确认存酒'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default WineStoragePosPage;
