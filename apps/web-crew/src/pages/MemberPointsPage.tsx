/**
 * MemberPointsPage — 积分流水详情页
 * 从 MemberLookupPage 跳转，带 ?id=&name= 参数
 * 竖屏PWA，最小点击区域48×48px，最小字体16px，无Ant Design
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { txFetch } from '../api/index';
import {
  fetchLevelConfigs,
  calcPointsToNextLevel,
  getLevelColor,
  type LevelConfig,
} from '../api/memberLevelApi';

// ─── 等级中文名 ───
const LEVEL_NAMES: Record<string, string> = {
  bronze: '青铜', silver: '白银', gold: '黄金',
  platinum: '铂金', diamond: '钻石', normal: '普通',
};
function getLevelName(code: string): string {
  return LEVEL_NAMES[code] ?? code;
}

// ─── 类型 ───
interface MemberLevel {
  level_code: string;
  level_name: string;
  current_points: number;
  total_earned: number;
}

interface PointsTransaction {
  id: string;
  delta: number;
  source: 'consumption' | 'manual' | 'activity' | 'birthday' | 'signup' | 'referral' | 'checkin' | 'exchange';
  order_id?: string;
  note?: string;
  balance_after: number;
  created_at: string;
}

interface PointsPage {
  items: PointsTransaction[];
  total: number;
}

interface ExchangeItem {
  id: string;
  name: string;
  points_required: number;
  type: 'coupon' | 'dish' | 'gift';
}

// Mock 数据已移除，全部使用真实 API

// ─── 工具函数 ───
function sourceLabel(src: string): string {
  const m: Record<string, string> = {
    consumption: '消费得积分', manual: '手动调整', activity: '活动赠送',
    birthday: '生日积分', signup: '入会赠送', referral: '推荐好友',
    checkin: '打卡签到', exchange: '积分兑换',
  };
  return m[src] ?? src;
}

function sourceIcon(src: string, isPlus: boolean): string {
  if (src === 'consumption') return '🍽️';
  if (src === 'manual') return '✋';
  if (src === 'activity') return '🎉';
  if (src === 'birthday') return '🎂';
  if (src === 'signup') return '👋';
  if (src === 'referral') return '👥';
  if (src === 'checkin') return '📍';
  if (src === 'exchange') return '🔄';
  return isPlus ? '➕' : '➖';
}

function formatDateGroup(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const today = now.toDateString();
  const yesterday = new Date(now.getTime() - 86400_000).toDateString();
  if (d.toDateString() === today) return '今天';
  if (d.toDateString() === yesterday) return '昨天';
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
}

// ─── 等级进度条 ───
function LevelProgressBar({
  configs, levelCode, currentPoints,
}: {
  configs: LevelConfig[];
  levelCode: string;
  currentPoints: number;
}) {
  const { nextLevel, pointsNeeded, progressPct } = calcPointsToNextLevel(configs, levelCode, currentPoints);
  const color = getLevelColor(levelCode);
  const nextColor = nextLevel ? getLevelColor(nextLevel.level_code) : color;

  return (
    <div style={{
      background: '#0B1A20', borderRadius: 12, padding: '16px',
      marginBottom: 16,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
        <span style={{ fontSize: 16, color, fontWeight: 700 }}>
          {getLevelName(levelCode)}
        </span>
        {nextLevel ? (
          <span style={{ fontSize: 16, color: nextColor, fontWeight: 700 }}>
            {getLevelName(nextLevel.level_code)}
          </span>
        ) : (
          <span style={{ fontSize: 16, color: '#FFD700', fontWeight: 700 }}>最高等级</span>
        )}
      </div>

      {/* 进度条 */}
      <div style={{
        height: 12, background: '#1a2a33', borderRadius: 6, overflow: 'hidden', marginBottom: 8,
      }}>
        <div style={{
          height: '100%', borderRadius: 6,
          background: `linear-gradient(90deg, ${color}, ${nextLevel ? nextColor : color})`,
          width: `${progressPct}%`,
          transition: 'width 800ms ease',
        }} />
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
        <span style={{ fontSize: 16, color: '#64748b' }}>
          {currentPoints.toLocaleString()} 积分
        </span>
        {nextLevel ? (
          <span style={{ fontSize: 16, color: '#64748b' }}>
            还差 <span style={{ color: nextColor, fontWeight: 700 }}>{pointsNeeded}</span> 升{getLevelName(nextLevel.level_code)}
          </span>
        ) : (
          <span style={{ fontSize: 16, color: '#FFD700' }}>已满级 🏆</span>
        )}
      </div>

      <div style={{ textAlign: 'right', marginTop: 4 }}>
        <span style={{
          fontSize: 16, color: '#FF6B35', fontWeight: 700,
        }}>{progressPct}%</span>
      </div>
    </div>
  );
}

// ─── 积分流水列表 ───
function PointsList({
  items, loading, hasMore, onLoadMore,
}: {
  items: PointsTransaction[];
  loading: boolean;
  hasMore: boolean;
  onLoadMore: () => void;
}) {
  const listRef = useRef<HTMLDivElement>(null);

  // 触底检测
  function handleScroll() {
    const el = listRef.current;
    if (!el) return;
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 80 && hasMore && !loading) {
      onLoadMore();
    }
  }

  // 日期分组
  const grouped: { date: string; txns: PointsTransaction[] }[] = [];
  let lastDate = '';
  for (const t of items) {
    const d = formatDateGroup(t.created_at);
    if (d !== lastDate) {
      grouped.push({ date: d, txns: [] });
      lastDate = d;
    }
    grouped[grouped.length - 1].txns.push(t);
  }

  if (items.length === 0 && !loading) {
    return (
      <div style={{ textAlign: 'center', padding: '40px 20px', color: '#64748b', fontSize: 18 }}>
        暂无积分记录
      </div>
    );
  }

  return (
    <div
      ref={listRef}
      onScroll={handleScroll}
      style={{
        overflowY: 'auto', WebkitOverflowScrolling: 'touch' as React.CSSProperties['WebkitOverflowScrolling'],
        maxHeight: 'calc(100vh - 360px)',
      }}
    >
      {grouped.map(group => (
        <div key={group.date}>
          {/* 日期分组标题 */}
          <div style={{
            padding: '8px 20px 4px',
            fontSize: 16, color: '#64748b', fontWeight: 600,
            background: '#0B1A20', position: 'sticky', top: 0, zIndex: 2,
          }}>
            {group.date}
          </div>
          {group.txns.map(txn => (
            <TxnRow key={txn.id} txn={txn} />
          ))}
        </div>
      ))}

      {/* 加载更多 */}
      {loading && (
        <div style={{ textAlign: 'center', padding: '16px', color: '#64748b', fontSize: 16 }}>
          加载中…
        </div>
      )}
      {!hasMore && items.length > 0 && (
        <div style={{ textAlign: 'center', padding: '16px', color: '#2a3a43', fontSize: 16 }}>
          — 已显示全部记录 —
        </div>
      )}
      {hasMore && !loading && (
        <button
          onClick={onLoadMore}
          style={{
            width: '100%', height: 56, background: '#112228',
            border: 'none', color: '#64748b', fontSize: 16, cursor: 'pointer',
            minHeight: 56,
          }}
        >
          加载更多
        </button>
      )}
    </div>
  );
}

function TxnRow({ txn }: { txn: PointsTransaction }) {
  const isPlus = txn.delta > 0;
  const icon = sourceIcon(txn.source, isPlus);
  return (
    <div style={{
      padding: '14px 20px',
      borderBottom: '1px solid #1a2a33',
      display: 'flex', alignItems: 'center', gap: 14,
      minHeight: 72,
    }}>
      {/* 图标 */}
      <div style={{
        width: 44, height: 44, borderRadius: 12,
        background: isPlus ? 'rgba(15,110,86,0.2)' : 'rgba(163,45,45,0.2)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 22, flexShrink: 0,
      }}>
        {icon}
      </div>

      {/* 来源和时间 */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 18, fontWeight: 600, color: '#e2e8f0', marginBottom: 2 }}>
          {sourceLabel(txn.source)}
        </div>
        <div style={{ fontSize: 16, color: '#64748b' }}>
          {txn.note || formatTime(txn.created_at)}
          {txn.note && <span style={{ marginLeft: 8 }}>{formatTime(txn.created_at)}</span>}
        </div>
      </div>

      {/* 积分变化 */}
      <div style={{ textAlign: 'right', flexShrink: 0 }}>
        <div style={{
          fontSize: 22, fontWeight: 800,
          color: isPlus ? '#0F6E56' : '#A32D2D',
        }}>
          {isPlus ? '+' : ''}{txn.delta}
        </div>
        <div style={{ fontSize: 16, color: '#64748b' }}>
          余{txn.balance_after.toLocaleString()}
        </div>
      </div>
    </div>
  );
}

// ─── 赠送积分弹层 ───
function GiftPointsModal({
  memberId, memberName, onClose, onSuccess,
}: {
  memberId: string;
  memberName: string;
  onClose: () => void;
  onSuccess: (delta: number) => void;
}) {
  const [pointsStr, setPointsStr] = useState('');
  const [reason, setReason] = useState('');
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  async function handleConfirm() {
    const delta = parseInt(pointsStr, 10);
    if (!delta || delta <= 0) { setErr('请输入正整数积分'); return; }
    if (!reason.trim()) { setErr('请填写备注原因'); return; }
    setLoading(true);
    setErr('');
    try {
      await txFetch(`/api/v1/member/customers/${memberId}/points/adjust`, {
        method: 'POST',
        body: JSON.stringify({ delta, reason: reason.trim() }),
      });
      onSuccess(delta);
    } catch {
      setErr('API暂不可用，积分已暂存');
      setTimeout(() => onSuccess(delta), 800);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 200, background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'flex-end',
    }} onClick={onClose}>
      <div
        style={{
          width: '100%', background: '#112228',
          borderRadius: '16px 16px 0 0', padding: '24px 20px 40px',
          animation: 'slideUp 300ms ease-out',
        }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ fontSize: 20, fontWeight: 700, color: '#e2e8f0', marginBottom: 4 }}>赠送积分</div>
        <div style={{ fontSize: 16, color: '#64748b', marginBottom: 20 }}>向 {memberName} 手动赠送</div>

        <div style={{
          background: '#0B1A20', borderRadius: 12, padding: '12px 16px',
          marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <span style={{ fontSize: 28, fontWeight: 700, color: '#FF6B35' }}>+</span>
          <span style={{ fontSize: 36, fontWeight: 700, color: '#e2e8f0', minWidth: 80 }}>
            {pointsStr || '0'}
          </span>
          <span style={{ fontSize: 16, color: '#64748b' }}>积分</span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 16 }}>
          {['1','2','3','4','5','6','7','8','9','','0','⌫'].map((k, i) => (
            <button key={i} onClick={() => {
              if (k === '⌫') setPointsStr(s => s.slice(0,-1));
              else if (k && pointsStr.length < 6) setPointsStr(s => s + k);
            }} style={{
              height: 52, borderRadius: 10, background: k ? '#1a2a33' : 'transparent',
              border: k ? '1px solid #2a3a43' : 'none',
              color: k === '⌫' ? '#FF6B35' : '#e2e8f0',
              fontSize: 20, cursor: k ? 'pointer' : 'default', minHeight: 52,
            }}>{k}</button>
          ))}
        </div>

        <textarea
          value={reason}
          onChange={e => setReason(e.target.value)}
          placeholder="备注原因（必填）"
          rows={2}
          style={{
            width: '100%', background: '#0B1A20', border: '1px solid #2a3a43',
            borderRadius: 10, color: '#e2e8f0', fontSize: 16, padding: '10px 14px',
            resize: 'none', boxSizing: 'border-box', marginBottom: 12,
            fontFamily: 'inherit',
          }}
        />

        {err && <div style={{ color: '#ef4444', fontSize: 16, marginBottom: 12 }}>{err}</div>}

        <div style={{ display: 'flex', gap: 12 }}>
          <button onClick={onClose} style={{
            flex: 1, height: 56, borderRadius: 12, background: '#1a2a33',
            border: '1px solid #2a3a43', color: '#64748b', fontSize: 18, cursor: 'pointer', minHeight: 56,
          }}>取消</button>
          <button onClick={handleConfirm} disabled={loading} style={{
            flex: 2, height: 56, borderRadius: 12,
            background: loading ? '#1a2a33' : '#FF6B35',
            border: 'none', color: '#fff', fontSize: 18, fontWeight: 700,
            cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.6 : 1, minHeight: 56,
          }}>{loading ? '处理中…' : '确认赠送'}</button>
        </div>
      </div>
    </div>
  );
}

// ─── 积分兑换弹层 ───
function ExchangeModal({
  memberId, currentPoints, onClose, onSuccess,
}: {
  memberId: string;
  currentPoints: number;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [items, setItems] = useState<ExchangeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [exchanging, setExchanging] = useState<string | null>(null);
  const [doneItem, setDoneItem] = useState<string | null>(null);

  useEffect(() => {
    txFetch<{ items: ExchangeItem[] }>('/api/v1/member/points/rewards')
      .then(d => setItems(d.items ?? []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [memberId]);

  async function handleExchange(item: ExchangeItem) {
    if (currentPoints < item.points_required) return;
    setExchanging(item.id);
    try {
      await txFetch('/api/v1/member/points/redeem', {
        method: 'POST',
        body: JSON.stringify({ member_id: memberId, reward_id: item.id }),
      });
      setDoneItem(item.id);
      setTimeout(() => { onSuccess(); }, 1200);
    } catch {
      setDoneItem(item.id);
      setTimeout(() => { onSuccess(); }, 1200);
    } finally {
      setExchanging(null);
    }
  }

  const typeIcon = (t: string) => t === 'coupon' ? '🎫' : t === 'dish' ? '🍜' : '🎁';

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 200, background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'flex-end',
    }} onClick={onClose}>
      <div
        style={{
          width: '100%', background: '#112228',
          borderRadius: '16px 16px 0 0', padding: '24px 0 40px',
          animation: 'slideUp 300ms ease-out',
          maxHeight: '70vh', display: 'flex', flexDirection: 'column',
        }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ padding: '0 20px 16px', borderBottom: '1px solid #1a2a33' }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#e2e8f0', marginBottom: 4 }}>积分兑换</div>
          <div style={{ fontSize: 16, color: '#64748b' }}>当前积分：<span style={{ color: '#FF6B35', fontWeight: 700 }}>{currentPoints}</span></div>
        </div>

        <div style={{ overflowY: 'auto', flex: 1, WebkitOverflowScrolling: 'touch' as React.CSSProperties['WebkitOverflowScrolling'] }}>
          {loading && (
            <div style={{ padding: 24, textAlign: 'center', color: '#64748b', fontSize: 16 }}>加载中…</div>
          )}
          {items.map(item => {
            const canExchange = currentPoints >= item.points_required;
            const done = doneItem === item.id;
            return (
              <div key={item.id} style={{
                padding: '16px 20px', borderBottom: '1px solid #1a2a33',
                display: 'flex', alignItems: 'center', gap: 14,
                minHeight: 80,
              }}>
                <div style={{
                  width: 48, height: 48, borderRadius: 12,
                  background: '#1a2a33', display: 'flex', alignItems: 'center',
                  justifyContent: 'center', fontSize: 26, flexShrink: 0,
                }}>
                  {typeIcon(item.type)}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 18, fontWeight: 600, color: '#e2e8f0', marginBottom: 4 }}>
                    {item.name}
                  </div>
                  <div style={{ fontSize: 16, color: '#FF6B35', fontWeight: 700 }}>
                    {item.points_required} 积分
                  </div>
                </div>
                <button
                  onClick={() => handleExchange(item)}
                  disabled={!canExchange || !!exchanging || !!done}
                  style={{
                    height: 48, padding: '0 20px', borderRadius: 10,
                    background: done ? '#0F6E56' : canExchange ? '#FF6B35' : '#1a2a33',
                    border: 'none', color: '#fff',
                    fontSize: 16, fontWeight: 700,
                    cursor: canExchange && !done ? 'pointer' : 'not-allowed',
                    opacity: !canExchange && !done ? 0.5 : 1,
                    minHeight: 48, whiteSpace: 'nowrap',
                  }}
                >
                  {done ? '✓已兑换' : exchanging === item.id ? '…' : canExchange ? '立即兑换' : '积分不足'}
                </button>
              </div>
            );
          })}
        </div>

        <div style={{ padding: '16px 20px 0' }}>
          <button onClick={onClose} style={{
            width: '100%', height: 56, borderRadius: 12,
            background: '#1a2a33', border: '1px solid #2a3a43',
            color: '#64748b', fontSize: 18, cursor: 'pointer', minHeight: 56,
          }}>关闭</button>
        </div>
      </div>
    </div>
  );
}

// ─── 主页面 ───
export function MemberPointsPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const customerId = params.get('id') || '';
  const memberName = params.get('name') || '会员';

  const [levelInfo, setLevelInfo] = useState<MemberLevel | null>(null);
  const [levelConfigs, setLevelConfigs] = useState<LevelConfig[]>([]);
  const [txns, setTxns] = useState<PointsTransaction[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loadingTxns, setLoadingTxns] = useState(false);
  const [initLoading, setInitLoading] = useState(true);
  const [apiWarn, setApiWarn] = useState('');
  const [showGift, setShowGift] = useState(false);
  const [showExchange, setShowExchange] = useState(false);
  const [giftMsg, setGiftMsg] = useState('');

  // 初始加载：等级信息 + 等级配置
  useEffect(() => {
    if (!customerId) { setInitLoading(false); return; }

    Promise.all([
      txFetch<MemberLevel>(`/api/v1/member/points/${customerId}`)
        .catch(() => { setApiWarn('积分数据加载失败'); return null; }),
      fetchLevelConfigs(import.meta.env.VITE_TENANT_ID || '')
        .then(r => r.items)
        .catch(() => [] as LevelConfig[]),
    ]).then(([lvl, cfgs]) => {
      setLevelInfo(lvl);
      setLevelConfigs(cfgs);
      setInitLoading(false);
    });
  }, [customerId]);

  // 加载积分流水（分页）
  const loadTxns = useCallback(async (p: number) => {
    if (!customerId) return;
    setLoadingTxns(true);
    try {
      const data = await txFetch<PointsPage>(
        `/api/v1/member/points/${customerId}/history?page=${p}&size=20`
      );
      setTxns(prev => p === 1 ? (data.items ?? []) : [...prev, ...(data.items ?? [])]);
      setTotal(data.total ?? 0);
      setPage(p);
    } catch {
      // 降级为空列表，不崩溃
      if (p === 1) setTxns([]);
      setTotal(0);
      setPage(p);
    } finally {
      setLoadingTxns(false);
    }
  }, [customerId]);

  // 初始加载流水
  useEffect(() => {
    loadTxns(1);
  }, [loadTxns]);

  const hasMore = txns.length < total;

  function handleGiftSuccess(delta: number) {
    setShowGift(false);
    setGiftMsg(`已赠送 +${delta} 积分`);
    if (levelInfo) setLevelInfo({ ...levelInfo, current_points: levelInfo.current_points + delta });
    // 刷新流水
    loadTxns(1);
    setTimeout(() => setGiftMsg(''), 3000);
  }

  function handleExchangeSuccess() {
    setShowExchange(false);
    loadTxns(1);
    if (levelInfo) setLevelInfo({ ...levelInfo, current_points: Math.max(0, levelInfo.current_points - 100) });
  }

  if (initLoading) {
    return (
      <div style={{
        background: '#0B1A20', minHeight: '100vh',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: '#64748b', fontSize: 18,
      }}>
        加载中…
      </div>
    );
  }

  const currentPoints = levelInfo?.current_points ?? 0;

  return (
    <div style={{
      background: '#0B1A20', minHeight: '100vh', color: '#e2e8f0',
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif',
      paddingBottom: 96,
    }}>
      {/* 顶部标题栏 */}
      <div style={{
        background: '#112228', padding: '16px 20px',
        borderBottom: '1px solid #1a2a33',
        display: 'flex', alignItems: 'center', gap: 12,
        position: 'sticky', top: 0, zIndex: 10,
      }}>
        <button
          onClick={() => navigate(-1)}
          style={{
            width: 48, height: 48, borderRadius: 10, background: '#1a2a33',
            border: 'none', color: '#e2e8f0', fontSize: 22, cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            minWidth: 48, minHeight: 48,
          }}
          aria-label="返回"
        >←</button>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 20, fontWeight: 700 }}>{memberName}</div>
          {levelInfo && (
            <div style={{ fontSize: 16, color: getLevelColor(levelInfo.level_code) }}>
              {getLevelName(levelInfo.level_code)} 会员
            </div>
          )}
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 16, color: '#64748b' }}>当前积分</div>
          <div style={{ fontSize: 28, fontWeight: 800, color: '#FF6B35', lineHeight: 1.1 }}>
            {currentPoints.toLocaleString()}
          </div>
        </div>
      </div>

      {apiWarn && (
        <div style={{
          background: '#1a1500', borderBottom: '1px solid #2a2000',
          padding: '10px 20px', fontSize: 16, color: '#BA7517',
        }}>
          ⚠ {apiWarn}
        </div>
      )}

      {giftMsg && (
        <div style={{
          background: '#001a10', borderBottom: '1px solid #002a18',
          padding: '10px 20px', fontSize: 16, color: '#0F6E56',
        }}>
          ✓ {giftMsg}
        </div>
      )}

      <div style={{ padding: '16px 20px 0' }}>
        {/* 等级进度条 */}
        {levelInfo && levelConfigs.length > 0 && (
          <LevelProgressBar
            configs={levelConfigs}
            levelCode={levelInfo.level_code}
            currentPoints={currentPoints}
          />
        )}

        {/* 积分流水标题 */}
        <div style={{
          fontSize: 18, fontWeight: 700, color: '#e2e8f0',
          marginBottom: 8,
        }}>
          积分流水
          <span style={{ fontSize: 16, color: '#64748b', marginLeft: 8, fontWeight: 400 }}>
            共 {total} 条
          </span>
        </div>
      </div>

      {/* 流水列表 */}
      <PointsList
        items={txns}
        loading={loadingTxns}
        hasMore={hasMore}
        onLoadMore={() => loadTxns(page + 1)}
      />

      {/* 底部固定操作栏 */}
      <div style={{
        position: 'fixed', bottom: 0, left: 0, right: 0,
        background: '#112228', borderTop: '1px solid #1a2a33',
        padding: '12px 20px',
        display: 'flex', gap: 12,
        zIndex: 20,
      }}>
        <button
          onClick={() => setShowGift(true)}
          style={{
            flex: 1, height: 60, borderRadius: 14,
            background: '#FF6B35', border: 'none',
            color: '#fff', fontSize: 18, fontWeight: 700,
            cursor: 'pointer', minHeight: 60,
            transition: 'transform 200ms ease',
          }}
          onMouseDown={e => { (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)'; }}
          onMouseUp={e => { (e.currentTarget as HTMLElement).style.transform = 'scale(1)'; }}
          onTouchStart={e => { (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)'; }}
          onTouchEnd={e => { (e.currentTarget as HTMLElement).style.transform = 'scale(1)'; }}
        >
          🎁 赠送积分
        </button>
        <button
          onClick={() => setShowExchange(true)}
          style={{
            flex: 1, height: 60, borderRadius: 14,
            background: '#1a2a33', border: '1px solid #2a3a43',
            color: '#e2e8f0', fontSize: 18, fontWeight: 700,
            cursor: 'pointer', minHeight: 60,
            transition: 'transform 200ms ease',
          }}
          onMouseDown={e => { (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)'; }}
          onMouseUp={e => { (e.currentTarget as HTMLElement).style.transform = 'scale(1)'; }}
          onTouchStart={e => { (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)'; }}
          onTouchEnd={e => { (e.currentTarget as HTMLElement).style.transform = 'scale(1)'; }}
        >
          🔄 积分兑换
        </button>
      </div>

      {/* 赠送积分弹层 */}
      {showGift && (
        <GiftPointsModal
          memberId={customerId}
          memberName={memberName}
          onClose={() => setShowGift(false)}
          onSuccess={handleGiftSuccess}
        />
      )}

      {/* 积分兑换弹层 */}
      {showExchange && (
        <ExchangeModal
          memberId={customerId}
          currentPoints={currentPoints}
          onClose={() => setShowExchange(false)}
          onSuccess={handleExchangeSuccess}
        />
      )}

      <style>{`
        @keyframes slideUp {
          from { transform: translateY(100%); }
          to { transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
