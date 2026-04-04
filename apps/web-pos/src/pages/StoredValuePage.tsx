/**
 * StoredValuePage — POS端储值卡管理
 * 终端：Store-POS（触屏，安卓/iPad）
 * 规范：无Ant Design，纯inline style，最小48px点击区，最小16px字体
 * 品牌色：#FF6B35
 */
import { useState, useCallback } from 'react';
import { txFetch } from '../api/index';

// ─── 类型定义 ───────────────────────────────────────────────────────────────

interface StoredValueAccount {
  id: string;
  customer_name: string;
  phone: string;
  balance_fen: number;       // 余额（分）
  total_deposit_fen: number; // 累计充值（分）
  total_spent_fen: number;   // 累计消费（分）
  last_txn_at: string;
  tier: 'NORMAL' | 'SILVER' | 'GOLD' | 'BLACK_GOLD';
}

interface Transaction {
  id: string;
  type: 'deposit' | 'spend';
  amount_fen: number;
  balance_after_fen: number;
  note: string;
  created_at: string;
}

// ─── 充值预设金额 ─────────────────────────────────────────────────────────────
const PRESET_AMOUNTS = [100, 200, 500, 1000, 2000, 5000];

// ─── 工具函数 ────────────────────────────────────────────────────────────────

const fenToYuan = (fen: number): string =>
  (Math.abs(fen) / 100).toFixed(2);

const phoneDisplay = (phone: string): string =>
  phone.length >= 8
    ? phone.slice(0, 3) + '****' + phone.slice(-4)
    : phone;

const formatDate = (iso: string): string => {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};

/** 赠送额（充>=500赠5%） */
const calcBonus = (yuan: number): number =>
  yuan >= 500 ? Math.floor(yuan * 0.05) : 0;

// ─── 层级配置 ────────────────────────────────────────────────────────────────
const TIER_CONFIG: Record<StoredValueAccount['tier'], { label: string; bg: string; color: string }> = {
  NORMAL:    { label: '普通会员', bg: '#E8E6E1', color: '#5F5E5A' },
  SILVER:    { label: '银卡会员', bg: '#D8D8D8', color: '#4A4A4A' },
  GOLD:      { label: '金卡会员', bg: '#FFF0C0', color: '#8B6914' },
  BLACK_GOLD: { label: '黑金会员', bg: '#2C2C2A', color: '#D4AF37' },
};

// ─── CSS helper：按钮按下动效 ─────────────────────────────────────────────────
const btnBase: React.CSSProperties = {
  cursor: 'pointer',
  border: 'none',
  outline: 'none',
  transition: 'transform 0.15s ease, opacity 0.15s ease',
  WebkitTapHighlightColor: 'transparent',
  userSelect: 'none',
};

// ─── API ─────────────────────────────────────────────────────────────────────

async function apiQueryAccount(phone: string): Promise<StoredValueAccount> {
  return txFetch<StoredValueAccount>(
    `/api/v1/member/stored-value/account?phone=${encodeURIComponent(phone)}`
  );
}

async function apiDeposit(accountId: string, amountFen: number, note: string): Promise<{ new_balance_fen: number }> {
  return txFetch<{ new_balance_fen: number }>('/api/v1/member/stored-value/deposit', {
    method: 'POST',
    body: JSON.stringify({ account_id: accountId, amount_fen: amountFen, note }),
  });
}

async function apiGetTransactions(accountId: string): Promise<Transaction[]> {
  return txFetch<Transaction[]>(
    `/api/v1/member/stored-value/transactions?account_id=${encodeURIComponent(accountId)}`
  );
}

// ─── 主组件 ───────────────────────────────────────────────────────────────────

export function StoredValuePage() {
  // 搜索状态
  const [query, setQuery] = useState('');
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState('');

  // 账户状态
  const [account, setAccount] = useState<StoredValueAccount | null>(null);

  // 充值弹窗
  const [showDeposit, setShowDeposit] = useState(false);
  const [selectedAmount, setSelectedAmount] = useState<number | null>(null);
  const [customAmount, setCustomAmount] = useState('');
  const [depositing, setDepositing] = useState(false);
  const [depositResult, setDepositResult] = useState<string>('');

  // 明细Drawer
  const [showDrawer, setShowDrawer] = useState(false);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loadingTxns, setLoadingTxns] = useState(false);

  // ── 搜索 ────────────────────────────────────────────────────────────────
  const handleSearch = useCallback(async () => {
    const q = query.trim();
    if (!q) return;
    setSearching(true);
    setSearchError('');
    setAccount(null);
    try {
      const acct = await apiQueryAccount(q);
      setAccount(acct);
    } catch (e: unknown) {
      setSearchError(e instanceof Error ? e.message : '查询失败，请重试');
    } finally {
      setSearching(false);
    }
  }, [query]);

  const handleClear = () => {
    setQuery('');
    setAccount(null);
    setSearchError('');
    setDepositResult('');
  };

  // ── 充值 ────────────────────────────────────────────────────────────────
  const depositYuan = selectedAmount ?? (customAmount ? Number(customAmount) : 0);
  const bonusYuan = calcBonus(depositYuan);

  const handleDeposit = async () => {
    if (!account || depositYuan <= 0) return;
    setDepositing(true);
    try {
      const totalYuan = depositYuan + bonusYuan;
      const result = await apiDeposit(account.id, totalYuan * 100, `充值¥${depositYuan}+赠¥${bonusYuan}`);
      // 更新账户余额
      setAccount((prev) => prev ? { ...prev, balance_fen: result.new_balance_fen, total_deposit_fen: prev.total_deposit_fen + totalYuan * 100 } : prev);
      setDepositResult(`充值成功！余额：¥${(result.new_balance_fen / 100).toFixed(2)}`);
      setShowDeposit(false);
      setSelectedAmount(null);
      setCustomAmount('');
    } catch {
      setDepositResult('充值失败，请重试');
    } finally {
      setDepositing(false);
    }
  };

  // ── 明细 ────────────────────────────────────────────────────────────────
  const handleOpenDrawer = async () => {
    if (!account) return;
    setShowDrawer(true);
    setLoadingTxns(true);
    try {
      const txns = await apiGetTransactions(account.id);
      setTransactions(txns);
    } catch (e) {
      console.error('加载交易明细失败', e);
      setTransactions([]);
    } finally {
      setLoadingTxns(false);
    }
  };

  // ── 渲染 ─────────────────────────────────────────────────────────────────
  return (
    <div style={{
      minHeight: '100vh',
      background: '#F8F7F5',
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif',
      position: 'relative',
    }}>

      {/* ─── 顶部搜索区 ─────────────────────────────────────────────── */}
      <div style={{
        background: '#FFFFFF',
        padding: '20px 24px',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        boxShadow: '0 2px 8px rgba(0,0,0,0.06)',
      }}>
        {/* 标题 */}
        <div style={{ fontSize: 22, fontWeight: 700, color: '#2C2C2A', marginRight: 8, whiteSpace: 'nowrap' }}>
          储值卡管理
        </div>

        {/* 搜索输入框 */}
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          placeholder="扫码 / 输入手机号查询"
          style={{
            flex: 1,
            height: 52,
            padding: '0 20px',
            fontSize: 18,
            borderRadius: 12,
            border: '2px solid #E8E6E1',
            background: '#F8F7F5',
            color: '#2C2C2A',
            outline: 'none',
            minWidth: 0,
          }}
          onFocus={(e) => { e.currentTarget.style.borderColor = '#FF6B35'; }}
          onBlur={(e) => { e.currentTarget.style.borderColor = '#E8E6E1'; }}
        />

        {/* 清除按钮 */}
        {query && (
          <button
            onClick={handleClear}
            style={{
              ...btnBase,
              height: 52,
              minWidth: 52,
              padding: '0 16px',
              borderRadius: 12,
              background: '#F0EDE6',
              color: '#5F5E5A',
              fontSize: 16,
              fontWeight: 600,
            }}
            onMouseDown={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
            onMouseUp={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
            onTouchStart={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
            onTouchEnd={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
          >
            清除
          </button>
        )}

        {/* 搜索按钮 */}
        <button
          onClick={handleSearch}
          disabled={!query.trim() || searching}
          style={{
            ...btnBase,
            height: 52,
            padding: '0 28px',
            borderRadius: 12,
            background: searching ? '#FFB895' : '#FF6B35',
            color: '#FFFFFF',
            fontSize: 18,
            fontWeight: 700,
            whiteSpace: 'nowrap',
            opacity: (!query.trim() || searching) ? 0.6 : 1,
          }}
          onMouseDown={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
          onMouseUp={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
          onTouchStart={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
          onTouchEnd={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
        >
          {searching ? '查询中…' : '查询'}
        </button>
      </div>

      {/* ─── 主体内容区 ─────────────────────────────────────────────── */}
      <div style={{ padding: 24, maxWidth: 800, margin: '0 auto' }}>

        {/* 错误提示 */}
        {searchError && (
          <div style={{
            padding: '16px 20px',
            background: '#FFF0F0',
            border: '1.5px solid #FFCCCC',
            borderRadius: 12,
            color: '#A32D2D',
            fontSize: 17,
            marginBottom: 20,
            fontWeight: 500,
          }}>
            {searchError}
          </div>
        )}

        {/* 充值成功提示 */}
        {depositResult && (
          <div style={{
            padding: '16px 20px',
            background: depositResult.includes('成功') ? '#F0FFF8' : '#FFF0F0',
            border: `1.5px solid ${depositResult.includes('成功') ? '#0F6E56' : '#FFCCCC'}`,
            borderRadius: 12,
            color: depositResult.includes('成功') ? '#0F6E56' : '#A32D2D',
            fontSize: 17,
            marginBottom: 20,
            fontWeight: 600,
          }}>
            {depositResult}
          </div>
        )}

        {/* 空状态提示 */}
        {!account && !searchError && !searching && (
          <div style={{
            textAlign: 'center',
            paddingTop: 80,
            color: '#B4B2A9',
          }}>
            <div style={{ fontSize: 64, marginBottom: 20 }}>💳</div>
            <div style={{ fontSize: 20, fontWeight: 600, marginBottom: 8 }}>请扫码或输入手机号查询储值账户</div>
            <div style={{ fontSize: 16, color: '#B4B2A9' }}>支持扫描会员码、手机号查询</div>
          </div>
        )}

        {/* ─── 账户信息卡 ─────────────────────────────────────────── */}
        {account && (
          <div style={{
            background: '#FFFFFF',
            borderRadius: 20,
            padding: 28,
            boxShadow: '0 4px 20px rgba(0,0,0,0.08)',
          }}>
            {/* 顶部：姓名 + 手机 + 层级 */}
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 20 }}>
              <div>
                <div style={{ fontSize: 28, fontWeight: 700, color: '#2C2C2A', lineHeight: 1.2 }}>
                  {account.customer_name}
                </div>
                <div style={{ fontSize: 17, color: '#5F5E5A', marginTop: 6 }}>
                  {phoneDisplay(account.phone)}
                </div>
              </div>
              <div style={{
                padding: '6px 16px',
                borderRadius: 20,
                background: TIER_CONFIG[account.tier].bg,
                color: TIER_CONFIG[account.tier].color,
                fontSize: 15,
                fontWeight: 700,
              }}>
                {TIER_CONFIG[account.tier].label}
              </div>
            </div>

            {/* 余额大字显示 */}
            <div style={{
              textAlign: 'center',
              padding: '28px 0',
              borderTop: '1.5px solid #F0EDE6',
              borderBottom: '1.5px solid #F0EDE6',
              marginBottom: 24,
            }}>
              <div style={{ fontSize: 16, color: '#5F5E5A', marginBottom: 8 }}>当前余额</div>
              <div style={{
                fontSize: 52,
                fontWeight: 800,
                color: '#FF6B35',
                letterSpacing: -1,
                lineHeight: 1.1,
              }}>
                ¥{fenToYuan(account.balance_fen)}
              </div>
            </div>

            {/* 三项数据 */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr 1fr',
              gap: 12,
              marginBottom: 24,
            }}>
              {[
                { label: '累计充值', value: `¥${fenToYuan(account.total_deposit_fen)}`, color: '#0F6E56' },
                { label: '累计消费', value: `¥${fenToYuan(account.total_spent_fen)}`, color: '#A32D2D' },
                { label: '最后交易', value: formatDate(account.last_txn_at).split(' ')[0], color: '#5F5E5A' },
              ].map((item) => (
                <div key={item.label} style={{
                  textAlign: 'center',
                  padding: '14px 8px',
                  background: '#F8F7F5',
                  borderRadius: 12,
                }}>
                  <div style={{ fontSize: 13, color: '#B4B2A9', marginBottom: 6 }}>{item.label}</div>
                  <div style={{ fontSize: 17, fontWeight: 700, color: item.color }}>{item.value}</div>
                </div>
              ))}
            </div>

            {/* 操作按钮：充值 + 查看明细 */}
            <div style={{ display: 'flex', gap: 14 }}>
              <button
                onClick={() => { setShowDeposit(true); setDepositResult(''); }}
                style={{
                  ...btnBase,
                  flex: 1,
                  height: 60,
                  borderRadius: 14,
                  background: '#52c41a',
                  color: '#FFFFFF',
                  fontSize: 20,
                  fontWeight: 700,
                }}
                onMouseDown={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
                onMouseUp={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
                onTouchStart={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
                onTouchEnd={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
              >
                充值
              </button>
              <button
                onClick={handleOpenDrawer}
                style={{
                  ...btnBase,
                  flex: 1,
                  height: 60,
                  borderRadius: 14,
                  background: '#E8E6E1',
                  color: '#2C2C2A',
                  fontSize: 20,
                  fontWeight: 700,
                }}
                onMouseDown={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
                onMouseUp={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
                onTouchStart={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
                onTouchEnd={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
              >
                查看明细
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ─── 充值弹窗 ──────────────────────────────────────────────── */}
      {showDeposit && account && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.55)',
            display: 'flex',
            alignItems: 'flex-end',
            justifyContent: 'center',
            zIndex: 100,
          }}
          onClick={(e) => { if (e.target === e.currentTarget) { setShowDeposit(false); } }}
        >
          <div style={{
            width: '100%',
            maxWidth: 640,
            background: '#FFFFFF',
            borderRadius: '20px 20px 0 0',
            padding: '28px 24px 36px',
            boxShadow: '0 -8px 32px rgba(0,0,0,0.12)',
          }}>
            {/* 弹窗标题 */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
              <div style={{ fontSize: 22, fontWeight: 700, color: '#2C2C2A' }}>
                充值 · {account.customer_name}
              </div>
              <button
                onClick={() => setShowDeposit(false)}
                style={{
                  ...btnBase,
                  width: 44, height: 44,
                  borderRadius: '50%',
                  background: '#F0EDE6',
                  color: '#5F5E5A',
                  fontSize: 20,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}
              >
                ✕
              </button>
            </div>

            {/* 预设金额 */}
            <div style={{ fontSize: 16, color: '#5F5E5A', marginBottom: 12 }}>选择充值金额</div>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, 1fr)',
              gap: 10,
              marginBottom: 20,
            }}>
              {PRESET_AMOUNTS.map((amt) => {
                const bonus = calcBonus(amt);
                const isSelected = selectedAmount === amt;
                return (
                  <button
                    key={amt}
                    onClick={() => { setSelectedAmount(isSelected ? null : amt); setCustomAmount(''); }}
                    style={{
                      ...btnBase,
                      height: 72,
                      borderRadius: 14,
                      border: `2px solid ${isSelected ? '#FF6B35' : '#E8E6E1'}`,
                      background: isSelected ? '#FFF3ED' : '#F8F7F5',
                      color: isSelected ? '#FF6B35' : '#2C2C2A',
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 2,
                    }}
                    onMouseDown={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.96)'; }}
                    onMouseUp={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
                    onTouchStart={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.96)'; }}
                    onTouchEnd={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
                  >
                    <span style={{ fontSize: 20, fontWeight: 700 }}>¥{amt}</span>
                    {bonus > 0 && (
                      <span style={{ fontSize: 13, color: '#52c41a', fontWeight: 600 }}>赠¥{bonus}</span>
                    )}
                  </button>
                );
              })}
            </div>

            {/* 自定义金额 */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 24 }}>
              <span style={{ fontSize: 16, color: '#5F5E5A', whiteSpace: 'nowrap' }}>自定义：¥</span>
              <input
                type="number"
                min="1"
                value={customAmount}
                onChange={(e) => { setCustomAmount(e.target.value); setSelectedAmount(null); }}
                placeholder="输入金额"
                style={{
                  flex: 1,
                  height: 52,
                  padding: '0 16px',
                  fontSize: 18,
                  borderRadius: 12,
                  border: '2px solid #E8E6E1',
                  background: '#F8F7F5',
                  color: '#2C2C2A',
                  outline: 'none',
                }}
                onFocus={(e) => { e.currentTarget.style.borderColor = '#FF6B35'; }}
                onBlur={(e) => { e.currentTarget.style.borderColor = '#E8E6E1'; }}
              />
            </div>

            {/* 赠送显示 */}
            {depositYuan > 0 && bonusYuan > 0 && (
              <div style={{
                padding: '12px 16px',
                background: '#F0FFF8',
                borderRadius: 10,
                marginBottom: 20,
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}>
                <span style={{ fontSize: 16, color: '#0F6E56' }}>
                  充¥{depositYuan} 赠¥{bonusYuan}（赠5%）
                </span>
                <span style={{ fontSize: 18, fontWeight: 700, color: '#0F6E56' }}>
                  实到¥{depositYuan + bonusYuan}
                </span>
              </div>
            )}

            {/* 确认按钮 */}
            <button
              onClick={handleDeposit}
              disabled={depositing || depositYuan <= 0}
              style={{
                ...btnBase,
                width: '100%',
                height: 64,
                borderRadius: 16,
                background: depositYuan > 0 ? '#52c41a' : '#E8E6E1',
                color: depositYuan > 0 ? '#FFFFFF' : '#B4B2A9',
                fontSize: 20,
                fontWeight: 700,
                opacity: (depositing || depositYuan <= 0) ? 0.7 : 1,
              }}
              onMouseDown={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
              onMouseUp={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
              onTouchStart={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(0.97)'; }}
              onTouchEnd={(e) => { (e.currentTarget as HTMLButtonElement).style.transform = 'scale(1)'; }}
            >
              {depositing
                ? '处理中…'
                : depositYuan > 0
                  ? `确认充值 ¥${depositYuan}${bonusYuan > 0 ? ` + 赠¥${bonusYuan}` : ''}`
                  : '请选择或输入充值金额'
              }
            </button>
          </div>
        </div>
      )}

      {/* ─── 交易明细 Drawer ────────────────────────────────────────── */}
      {/* 遮罩 */}
      {showDrawer && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.4)',
            zIndex: 200,
          }}
          onClick={() => setShowDrawer(false)}
        />
      )}

      {/* Drawer 面板 */}
      <div style={{
        position: 'fixed',
        top: 0,
        right: showDrawer ? 0 : '-82vw',
        width: '80vw',
        maxWidth: 560,
        height: '100vh',
        background: '#FFFFFF',
        boxShadow: '-8px 0 32px rgba(0,0,0,0.14)',
        zIndex: 201,
        transition: 'right 0.3s ease-out',
        display: 'flex',
        flexDirection: 'column',
      }}>
        {/* Drawer 标题 */}
        <div style={{
          padding: '24px 20px 16px',
          borderBottom: '1.5px solid #F0EDE6',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexShrink: 0,
        }}>
          <div>
            <div style={{ fontSize: 22, fontWeight: 700, color: '#2C2C2A' }}>储值明细</div>
            {account && (
              <div style={{ fontSize: 15, color: '#5F5E5A', marginTop: 4 }}>
                {account.customer_name} · {phoneDisplay(account.phone)}
              </div>
            )}
          </div>
          <button
            onClick={() => setShowDrawer(false)}
            style={{
              ...btnBase,
              width: 44, height: 44,
              borderRadius: '50%',
              background: '#F0EDE6',
              color: '#5F5E5A',
              fontSize: 20,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            ✕
          </button>
        </div>

        {/* Drawer 列表 */}
        <div style={{
          flex: 1,
          overflowY: 'auto',
          WebkitOverflowScrolling: 'touch' as any,
          padding: '12px 0',
        }}>
          {loadingTxns ? (
            <div style={{ textAlign: 'center', padding: 40, color: '#B4B2A9', fontSize: 17 }}>
              加载中…
            </div>
          ) : transactions.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 40, color: '#B4B2A9', fontSize: 17 }}>
              暂无交易记录
            </div>
          ) : (
            transactions.map((txn) => (
              <div key={txn.id} style={{
                display: 'flex',
                alignItems: 'center',
                padding: '16px 20px',
                borderBottom: '1px solid #F0EDE6',
                gap: 14,
              }}>
                {/* 类型图标 */}
                <div style={{
                  width: 44,
                  height: 44,
                  borderRadius: '50%',
                  background: txn.type === 'deposit' ? '#F0FFF8' : '#FFF0F0',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 22,
                  flexShrink: 0,
                }}>
                  {txn.type === 'deposit' ? '↑' : '↓'}
                </div>

                {/* 备注 + 时间 */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    fontSize: 16,
                    fontWeight: 600,
                    color: '#2C2C2A',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}>
                    {txn.note}
                  </div>
                  <div style={{ fontSize: 14, color: '#B4B2A9', marginTop: 3 }}>
                    {formatDate(txn.created_at)}
                  </div>
                </div>

                {/* 金额 + 余额 */}
                <div style={{ textAlign: 'right', flexShrink: 0 }}>
                  <div style={{
                    fontSize: 18,
                    fontWeight: 700,
                    color: txn.type === 'deposit' ? '#0F6E56' : '#A32D2D',
                  }}>
                    {txn.type === 'deposit' ? '+' : '-'}¥{fenToYuan(txn.amount_fen)}
                  </div>
                  <div style={{ fontSize: 14, color: '#B4B2A9', marginTop: 3 }}>
                    余¥{fenToYuan(Math.abs(txn.balance_after_fen))}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
