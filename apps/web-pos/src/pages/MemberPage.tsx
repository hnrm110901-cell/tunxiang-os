/**
 * 会员管理页面 — POS 收银台会员查询、开卡、余额/积分查看、充值
 *
 * 功能：
 *   1. 手机号/姓名搜索会员
 *   2. 新会员注册（手机号 + 姓名）
 *   3. 会员详情面板（储值余额、积分、偏好、近期消费）
 *   4. 快捷操作：充值、绑定订单、返回
 */
import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

// ─── API 配置 ────────────────────────────────────────────────────────────────

const BASE = import.meta.env.VITE_API_BASE_URL || '';
const TENANT_ID = import.meta.env.VITE_TENANT_ID || '';

async function memberFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(TENANT_ID ? { 'X-Tenant-ID': TENANT_ID } : {}),
      ...(options.headers as Record<string, string> || {}),
    },
  });
  const json = await resp.json();
  if (!json.ok) throw new Error(json.error?.message || 'API Error');
  return json.data;
}

// ─── 类型定义 ────────────────────────────────────────────────────────────────

interface MemberInfo {
  customer_id: string;
  phone: string;
  display_name: string;
  vip_level?: string;
  total_visits?: number;
  total_spend_fen?: number;
  preferences?: string[];
  allergies?: string[];
  favorite_items?: string[];
  recent_orders?: RecentOrder[];
  card_id?: string;
  source?: string;
  created_at?: string;
}

interface RecentOrder {
  order_id: string;
  order_no: string;
  total_fen: number;
  created_at: string;
}

interface BalanceData {
  balance_fen: number;
}

interface PointsData {
  points: number;
}

// ─── 工具函数 ────────────────────────────────────────────────────────────────

const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

const VIP_COLORS: Record<string, { bg: string; color: string }> = {
  gold:     { bg: 'rgba(250,173,20,0.2)',  color: '#faad14' },
  silver:   { bg: 'rgba(192,192,192,0.2)', color: '#c0c0c0' },
  platinum: { bg: 'rgba(130,180,255,0.2)', color: '#82b4ff' },
  diamond:  { bg: 'rgba(185,130,255,0.2)', color: '#b982ff' },
};

const getVipStyle = (level?: string) => {
  if (!level) return { bg: 'rgba(255,255,255,0.08)', color: '#8A94A4' };
  return VIP_COLORS[level.toLowerCase()] || { bg: 'rgba(255,107,44,0.15)', color: '#FF6B2C' };
};

// ─── 组件 ────────────────────────────────────────────────────────────────────

export function MemberPage() {
  const navigate = useNavigate();

  // 搜索状态
  const [keyword, setKeyword] = useState('');
  const [searchResults, setSearchResults] = useState<MemberInfo[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState('');

  // 选中会员
  const [selected, setSelected] = useState<MemberInfo | null>(null);
  const [balanceFen, setBalanceFen] = useState<number | null>(null);
  const [points, setPoints] = useState<number | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // 新会员注册
  const [showRegister, setShowRegister] = useState(false);
  const [regPhone, setRegPhone] = useState('');
  const [regName, setRegName] = useState('');
  const [registering, setRegistering] = useState(false);
  const [regResult, setRegResult] = useState('');

  // 充值
  const [showRecharge, setShowRecharge] = useState(false);
  const [rechargeAmountYuan, setRechargeAmountYuan] = useState('');
  const [recharging, setRecharging] = useState(false);
  const [rechargeResult, setRechargeResult] = useState('');

  // ── 搜索会员 ──

  const handleSearch = useCallback(async () => {
    const q = keyword.trim();
    if (!q) return;
    setSearching(true);
    setSearchError('');
    setSelected(null);
    setBalanceFen(null);
    setPoints(null);
    try {
      const data = await memberFetch<MemberInfo[]>(
        `/api/v1/member/depth/search?keyword=${encodeURIComponent(q)}`,
      );
      setSearchResults(data || []);
      if (!data || data.length === 0) {
        setSearchError('未找到会员，可点击"新会员注册"开卡');
      }
    } catch (err) {
      setSearchError(err instanceof Error ? err.message : '搜索失败');
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  }, [keyword]);

  const handleSearchKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSearch();
  };

  // ── 选中会员 → 加载余额/积分 ──

  const handleSelectMember = useCallback(async (member: MemberInfo) => {
    setSelected(member);
    setLoadingDetail(true);
    setBalanceFen(null);
    setPoints(null);
    setShowRecharge(false);
    setRechargeResult('');

    // 并行加载余额和积分
    const balanceP = memberFetch<BalanceData>(
      `/api/v1/members/${member.customer_id}/sv/balance`,
    ).then((d) => setBalanceFen(d.balance_fen)).catch(() => setBalanceFen(0));

    const pointsP = member.card_id
      ? memberFetch<PointsData>(
          `/api/v1/member/points/cards/${member.card_id}/balance`,
        ).then((d) => setPoints(d.points)).catch(() => setPoints(0))
      : Promise.resolve().then(() => setPoints(0));

    await Promise.all([balanceP, pointsP]);
    setLoadingDetail(false);
  }, []);

  // ── 新会员注册 ──

  const handleRegister = useCallback(async () => {
    const phone = regPhone.trim();
    if (!phone) return;
    setRegistering(true);
    setRegResult('');
    try {
      const data = await memberFetch<{ customer_id: string }>(
        '/api/v1/member/customers',
        {
          method: 'POST',
          body: JSON.stringify({
            phone,
            display_name: regName.trim() || undefined,
            source: 'pos',
          }),
        },
      );
      setRegResult(`注册成功 ID: ${data.customer_id}`);
      setRegPhone('');
      setRegName('');
      // 自动搜索新注册的会员
      setKeyword(phone);
      setTimeout(() => {
        setShowRegister(false);
        handleSearch();
      }, 800);
    } catch (err) {
      setRegResult(err instanceof Error ? err.message : '注册失败');
    } finally {
      setRegistering(false);
    }
  }, [regPhone, regName, handleSearch]);

  // ── 充值 ──

  const handleRecharge = useCallback(async () => {
    if (!selected || !rechargeAmountYuan.trim()) return;
    const amountFen = Math.round(parseFloat(rechargeAmountYuan) * 100);
    if (isNaN(amountFen) || amountFen <= 0) {
      setRechargeResult('请输入有效金额');
      return;
    }
    setRecharging(true);
    setRechargeResult('');
    try {
      await memberFetch<unknown>(
        `/api/v1/members/${selected.customer_id}/sv/charge`,
        {
          method: 'POST',
          body: JSON.stringify({ amount_fen: amountFen }),
        },
      );
      setRechargeResult(`充值成功 +${fen2yuan(amountFen)}`);
      setRechargeAmountYuan('');
      // 刷新余额
      memberFetch<BalanceData>(
        `/api/v1/members/${selected.customer_id}/sv/balance`,
      ).then((d) => setBalanceFen(d.balance_fen)).catch(() => {});
    } catch (err) {
      setRechargeResult(err instanceof Error ? err.message : '充值失败');
    } finally {
      setRecharging(false);
    }
  }, [selected, rechargeAmountYuan]);

  // ── 快捷充值金额 ──

  const QUICK_AMOUNTS = [100, 200, 500, 1000];

  // ── 渲染 ──

  return (
    <div style={pageStyle}>
      <div style={{ display: 'flex', height: '100vh' }}>

        {/* ── 左侧：搜索 + 结果列表 ── */}
        <div style={{ flex: 1, padding: 20, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

          {/* 顶部标题栏 */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>会员管理</h2>
            <button
              type="button"
              onClick={() => navigate(-1)}
              style={{ ...btnBase, background: '#1a2a33', color: '#8A94A4', border: '1px solid #333' }}
            >
              返回
            </button>
          </div>

          {/* 搜索栏 */}
          <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
            <input
              type="text"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onKeyDown={handleSearchKeyDown}
              placeholder="输入手机号或姓名搜索会员"
              autoFocus
              style={inputStyle}
            />
            <button
              type="button"
              onClick={handleSearch}
              disabled={searching || !keyword.trim()}
              style={{
                ...btnBase,
                background: keyword.trim() ? '#FF6B2C' : '#333',
                color: '#fff',
                minWidth: 80,
                fontWeight: 600,
              }}
            >
              {searching ? '搜索中...' : '搜索'}
            </button>
            <button
              type="button"
              onClick={() => { setShowRegister(!showRegister); setRegResult(''); }}
              style={{ ...btnBase, background: '#1a2a33', color: '#52c41a', border: '1px solid #2E6B4A', minWidth: 100 }}
            >
              {showRegister ? '取消' : '新会员注册'}
            </button>
          </div>

          {/* 新会员注册表单（内联） */}
          {showRegister && (
            <div style={{ ...cardStyle, marginBottom: 16, border: '1px solid #2E6B4A' }}>
              <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 12, color: '#52c41a' }}>新会员注册</div>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                <input
                  type="tel"
                  value={regPhone}
                  onChange={(e) => setRegPhone(e.target.value)}
                  placeholder="手机号（必填）"
                  style={{ ...inputStyle, flex: '1 1 160px' }}
                />
                <input
                  type="text"
                  value={regName}
                  onChange={(e) => setRegName(e.target.value)}
                  placeholder="姓名（选填）"
                  style={{ ...inputStyle, flex: '1 1 120px' }}
                />
                <button
                  type="button"
                  onClick={handleRegister}
                  disabled={registering || !regPhone.trim()}
                  style={{
                    ...btnBase,
                    background: regPhone.trim() ? '#52c41a' : '#333',
                    color: '#fff',
                    fontWeight: 600,
                    minWidth: 80,
                  }}
                >
                  {registering ? '注册中...' : '注册'}
                </button>
              </div>
              {regResult && (
                <div style={{
                  marginTop: 10,
                  fontSize: 14,
                  color: regResult.startsWith('注册成功') ? '#52c41a' : '#ff4d4f',
                }}>
                  {regResult}
                </div>
              )}
            </div>
          )}

          {/* 搜索错误/提示 */}
          {searchError && (
            <div style={{ color: '#faad14', fontSize: 15, marginBottom: 12 }}>{searchError}</div>
          )}

          {/* 搜索结果列表 */}
          <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' as unknown as string }}>
            {searchResults.map((m) => {
              const isActive = selected?.customer_id === m.customer_id;
              const vip = getVipStyle(m.vip_level);
              return (
                <div
                  key={m.customer_id}
                  role="button"
                  tabIndex={0}
                  onClick={() => handleSelectMember(m)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSelectMember(m)}
                  style={{
                    ...cardStyle,
                    marginBottom: 10,
                    cursor: 'pointer',
                    border: isActive ? '2px solid #FF6B2C' : '1.5px solid transparent',
                    transition: 'border-color 150ms',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                      <div style={{ fontSize: 18, fontWeight: 600 }}>
                        {m.display_name || '未命名'}
                        {m.vip_level && (
                          <span style={{
                            marginLeft: 8,
                            padding: '2px 8px',
                            borderRadius: 4,
                            fontSize: 12,
                            fontWeight: 600,
                            background: vip.bg,
                            color: vip.color,
                          }}>
                            {m.vip_level.toUpperCase()}
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: 15, color: '#8A94A4', marginTop: 4 }}>{m.phone}</div>
                    </div>
                    <div style={{ textAlign: 'right', fontSize: 14, color: '#999' }}>
                      {m.total_visits != null && <div>到店 {m.total_visits} 次</div>}
                      {m.total_spend_fen != null && <div>累计消费 {fen2yuan(m.total_spend_fen)}</div>}
                    </div>
                  </div>
                </div>
              );
            })}

            {/* 空状态 */}
            {!searching && searchResults.length === 0 && !searchError && (
              <div style={{ textAlign: 'center', color: '#555', marginTop: 60, fontSize: 16 }}>
                输入手机号或姓名搜索会员
              </div>
            )}
          </div>
        </div>

        {/* ── 右侧：会员详情面板 ── */}
        <div style={{
          width: 380,
          background: '#112228',
          padding: 20,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}>
          {!selected ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#555', fontSize: 16 }}>
              选择左侧会员查看详情
            </div>
          ) : (
            <>
              {/* 会员基本信息 */}
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 22, fontWeight: 700 }}>
                  {selected.display_name || '未命名'}
                </div>
                <div style={{ fontSize: 15, color: '#8A94A4', marginTop: 4 }}>{selected.phone}</div>
                <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                  {selected.vip_level && (() => {
                    const vs = getVipStyle(selected.vip_level);
                    return (
                      <span style={{ padding: '3px 10px', borderRadius: 6, fontSize: 13, fontWeight: 600, background: vs.bg, color: vs.color }}>
                        {selected.vip_level.toUpperCase()}
                      </span>
                    );
                  })()}
                  {selected.total_visits != null && (
                    <span style={detailTagStyle}>到店 {selected.total_visits} 次</span>
                  )}
                  {selected.total_spend_fen != null && (
                    <span style={detailTagStyle}>累计 {fen2yuan(selected.total_spend_fen)}</span>
                  )}
                </div>
              </div>

              {/* 储值余额 & 积分 */}
              <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
                <div style={{ flex: 1, ...cardStyle, padding: 14, textAlign: 'center' }}>
                  <div style={{ fontSize: 13, color: '#8A94A4', marginBottom: 6 }}>储值余额</div>
                  <div style={{ fontSize: 22, fontWeight: 700, color: '#FF6B2C' }}>
                    {loadingDetail ? '...' : balanceFen != null ? fen2yuan(balanceFen) : '--'}
                  </div>
                </div>
                <div style={{ flex: 1, ...cardStyle, padding: 14, textAlign: 'center' }}>
                  <div style={{ fontSize: 13, color: '#8A94A4', marginBottom: 6 }}>积分</div>
                  <div style={{ fontSize: 22, fontWeight: 700, color: '#faad14' }}>
                    {loadingDetail ? '...' : points != null ? points.toLocaleString() : '--'}
                  </div>
                </div>
              </div>

              {/* 偏好/过敏/收藏 */}
              {(selected.preferences?.length || selected.allergies?.length || selected.favorite_items?.length) ? (
                <div style={{ ...cardStyle, marginBottom: 16, padding: 14 }}>
                  {selected.allergies && selected.allergies.length > 0 && (
                    <div style={{ marginBottom: 8 }}>
                      <span style={{ fontSize: 13, color: '#ff4d4f', fontWeight: 600 }}>过敏: </span>
                      {selected.allergies.map((a) => (
                        <span key={a} style={{ ...tagChip, background: 'rgba(255,77,79,0.15)', color: '#ff4d4f' }}>{a}</span>
                      ))}
                    </div>
                  )}
                  {selected.preferences && selected.preferences.length > 0 && (
                    <div style={{ marginBottom: 8 }}>
                      <span style={{ fontSize: 13, color: '#8A94A4', fontWeight: 600 }}>偏好: </span>
                      {selected.preferences.map((p) => (
                        <span key={p} style={{ ...tagChip, background: 'rgba(255,255,255,0.08)', color: '#ccc' }}>{p}</span>
                      ))}
                    </div>
                  )}
                  {selected.favorite_items && selected.favorite_items.length > 0 && (
                    <div>
                      <span style={{ fontSize: 13, color: '#faad14', fontWeight: 600 }}>常点: </span>
                      {selected.favorite_items.map((f) => (
                        <span key={f} style={{ ...tagChip, background: 'rgba(250,173,20,0.12)', color: '#faad14' }}>{f}</span>
                      ))}
                    </div>
                  )}
                </div>
              ) : null}

              {/* 近期消费 */}
              {selected.recent_orders && selected.recent_orders.length > 0 && (
                <div style={{ ...cardStyle, padding: 14, marginBottom: 16, flex: 1, overflowY: 'auto' }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: '#8A94A4', marginBottom: 8 }}>近期消费</div>
                  {selected.recent_orders.map((o) => (
                    <div key={o.order_id} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #1a2a33', fontSize: 14 }}>
                      <span style={{ color: '#ccc' }}>{o.order_no}</span>
                      <span style={{ color: '#FF6B2C', fontWeight: 600 }}>{fen2yuan(o.total_fen)}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* 充值面板 */}
              {showRecharge && (
                <div style={{ ...cardStyle, marginBottom: 16, padding: 14, border: '1px solid rgba(255,107,44,0.3)' }}>
                  <div style={{ fontSize: 15, fontWeight: 600, color: '#FF6B2C', marginBottom: 10 }}>储值充值</div>
                  <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
                    {QUICK_AMOUNTS.map((amt) => (
                      <button
                        key={amt}
                        type="button"
                        onClick={() => setRechargeAmountYuan(String(amt))}
                        style={{
                          ...btnBase,
                          background: rechargeAmountYuan === String(amt) ? '#FF6B2C' : '#1a2a33',
                          color: '#fff',
                          fontSize: 15,
                          padding: '8px 16px',
                          border: rechargeAmountYuan === String(amt) ? 'none' : '1px solid #333',
                        }}
                      >
                        {amt}元
                      </button>
                    ))}
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <input
                      type="number"
                      value={rechargeAmountYuan}
                      onChange={(e) => setRechargeAmountYuan(e.target.value)}
                      placeholder="自定义金额（元）"
                      style={{ ...inputStyle, flex: 1 }}
                    />
                    <button
                      type="button"
                      onClick={handleRecharge}
                      disabled={recharging || !rechargeAmountYuan.trim()}
                      style={{
                        ...btnBase,
                        background: rechargeAmountYuan.trim() ? '#FF6B2C' : '#333',
                        color: '#fff',
                        fontWeight: 600,
                        minWidth: 70,
                      }}
                    >
                      {recharging ? '...' : '确认'}
                    </button>
                  </div>
                  {rechargeResult && (
                    <div style={{
                      marginTop: 8,
                      fontSize: 14,
                      color: rechargeResult.startsWith('充值成功') ? '#52c41a' : '#ff4d4f',
                    }}>
                      {rechargeResult}
                    </div>
                  )}
                </div>
              )}

              {/* 操作按钮 */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 'auto' }}>
                <button
                  type="button"
                  onClick={() => { setShowRecharge(!showRecharge); setRechargeResult(''); }}
                  style={{ ...actionBtnStyle, background: '#FF6B2C', color: '#fff', border: 'none' }}
                >
                  {showRecharge ? '收起充值' : '充值'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    // 将会员ID存入 sessionStorage 供结算页使用
                    if (selected) {
                      sessionStorage.setItem('tx_bound_member_id', selected.customer_id);
                      sessionStorage.setItem('tx_bound_member_name', selected.display_name || selected.phone);
                    }
                    navigate(-1);
                  }}
                  style={{ ...actionBtnStyle, background: '#1a2a33', color: '#fff', border: '1.5px solid #FF6B2C' }}
                >
                  绑定订单
                </button>
                <button
                  type="button"
                  onClick={() => navigate(-1)}
                  style={{ ...actionBtnStyle, background: '#1a2a33', color: '#8A94A4', border: '1.5px solid #333' }}
                >
                  返回
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── 样式常量 ────────────────────────────────────────────────────────────────

const pageStyle: React.CSSProperties = {
  background: '#0B1A20',
  minHeight: '100vh',
  color: '#fff',
  fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif',
};

const cardStyle: React.CSSProperties = {
  background: '#112228',
  borderRadius: 12,
  padding: 16,
};

const inputStyle: React.CSSProperties = {
  background: '#1a2a33',
  border: '1.5px solid #333',
  borderRadius: 8,
  color: '#fff',
  fontSize: 16,
  padding: '10px 14px',
  outline: 'none',
  fontFamily: 'inherit',
};

const btnBase: React.CSSProperties = {
  padding: '10px 16px',
  border: 'none',
  borderRadius: 8,
  fontSize: 15,
  cursor: 'pointer',
  fontFamily: 'inherit',
};

const actionBtnStyle: React.CSSProperties = {
  padding: '14px 0',
  borderRadius: 10,
  fontSize: 17,
  fontWeight: 600,
  cursor: 'pointer',
  fontFamily: 'inherit',
  textAlign: 'center',
};

const detailTagStyle: React.CSSProperties = {
  padding: '3px 10px',
  borderRadius: 6,
  fontSize: 13,
  background: 'rgba(255,255,255,0.08)',
  color: '#8A94A4',
};

const tagChip: React.CSSProperties = {
  display: 'inline-block',
  padding: '2px 8px',
  borderRadius: 4,
  fontSize: 13,
  marginRight: 4,
  marginBottom: 4,
};
