/**
 * 会员识别页面 — 搜索会员 → 查看等级/积分/偏好 → 关联当前订单
 * 移动端竖屏, 最小字体16px, 热区>=48px
 */
import { useState, useCallback, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { formatPrice } from '@tx-ds/utils';
import { searchMember, bindMemberToOrder, type MemberInfo } from '../api/index';
import { MemberInsightCard } from './MemberInsightCard';
import { getStoredValue, type StoredValueTransaction } from '../api/storedValueApi';
import {
  fetchLevelConfigs,
  checkMemberUpgrade,
  fetchLevelHistory,
  getLevelColor,
  calcPointsToNextLevel,
  type LevelConfig,
  type LevelHistoryItem,
} from '../api/memberLevelApi';
import { getMemberPoints, type MemberPoints } from '../api/memberPointsApi';
import { MemberPointsCard } from '../components/MemberPointsCard';

/* ---------- 样式常量 ---------- */
const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B2C',
  green: '#22c55e',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
  gold: '#facc15',
  info: '#185FA5',
  red: '#ef4444',
};


function levelColor(level: string): string {
  if (level === '金卡') return C.gold;
  if (level === '银卡') return '#c0c0c0';
  if (level === '黑金') return C.white;
  return C.muted;
}

/* ---------- 交易类型颜色 ---------- */
function txnColor(type: string): string {
  if (type === 'recharge') return '#22c55e';   // 绿
  if (type === 'consume') return '#ef4444';    // 红
  if (type === 'refund') return '#3b82f6';     // 蓝
  return '#64748b';
}

function txnLabel(type: string): string {
  const map: Record<string, string> = {
    recharge: '充值', consume: '消费', refund: '退款',
    adjustment: '调整', expire: '过期',
  };
  return map[type] ?? type;
}

/** @deprecated Use formatPrice from @tx-ds/utils */
function fen2yuanStr(fen: number): string {
  return (Math.abs(fen) / 100).toFixed(2).replace(/\.00$/, '');
}

const TENANT_ID = (import.meta.env.VITE_TENANT_ID as string) || 'demo-tenant';

/* ---------- 等级权益 Sheet ---------- */
interface LevelBenefitSheetProps {
  member: MemberInfo;
  configs: LevelConfig[];
  levelHistory: LevelHistoryItem[];
  onClose: () => void;
  onCheckUpgrade: () => void;
  upgrading: boolean;
}

function LevelBenefitSheet({ member, configs, levelHistory, onClose, onCheckUpgrade, upgrading }: LevelBenefitSheetProps) {
  // 匹配当前等级配置（level字段可能是 '金卡'/'gold' 等不同格式）
  const currentConfig = configs.find(c =>
    c.level_code === member.level ||
    c.level_name === member.level ||
    c.level_name.startsWith(member.level),
  ) ?? configs.find(c => c.level_code === 'normal');

  const { nextLevel, pointsNeeded, progressPct } = currentConfig
    ? calcPointsToNextLevel(configs, currentConfig.level_code, member.points)
    : { nextLevel: null, pointsNeeded: 0, progressPct: 100 };

  function discountLabel(rate: number): string {
    if (rate >= 1.0) return '无折扣';
    return `全场${(rate * 10).toFixed(1).replace(/\.0$/, '')}折`;
  }

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)',
        zIndex: 200, display: 'flex', alignItems: 'flex-end',
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: '100%', background: '#0e1a20', borderRadius: '16px 16px 0 0',
          padding: '20px 16px 40px', maxHeight: '88vh', overflowY: 'auto',
          border: `1px solid ${currentConfig ? getLevelColor(currentConfig.level_code) + '44' : '#1a2a33'}`,
          borderBottom: 'none',
        }}
      >
        <div style={{ width: 40, height: 4, borderRadius: 2, background: '#64748b', margin: '0 auto 16px' }} />

        {/* 当前等级标题 */}
        <div style={{ textAlign: 'center', marginBottom: 20 }}>
          <div style={{
            fontSize: 24, fontWeight: 700,
            color: currentConfig ? getLevelColor(currentConfig.level_code) : '#64748b',
          }}>
            {currentConfig?.level_name ?? member.level}
          </div>
          <div style={{ fontSize: 16, color: '#64748b', marginTop: 4 }}>
            当前积分: <span style={{ color: '#FF6B2C', fontWeight: 700 }}>{member.points.toLocaleString()}</span>
            {nextLevel && (
              <span> / {nextLevel.min_points.toLocaleString()} 分升{nextLevel.level_name}</span>
            )}
          </div>
        </div>

        {/* 进度条 */}
        {nextLevel && (
          <div style={{ marginBottom: 20 }}>
            <div style={{
              height: 10, borderRadius: 5, background: '#1a2a33', overflow: 'hidden', marginBottom: 6,
            }}>
              <div style={{
                height: '100%', borderRadius: 5,
                width: `${progressPct}%`,
                background: currentConfig ? getLevelColor(currentConfig.level_code) : '#FF6B2C',
                transition: 'width 0.5s ease',
              }} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14, color: '#64748b' }}>
              <span>{progressPct}%</span>
              <span>还差 {pointsNeeded.toLocaleString()} 积分升{nextLevel.level_name}</span>
            </div>
          </div>
        )}

        {!nextLevel && (
          <div style={{
            textAlign: 'center', fontSize: 15, color: '#facc15',
            padding: '8px 0', marginBottom: 12,
          }}>
            已达最高等级 ✦
          </div>
        )}

        <div style={{ height: 1, background: '#1a2a33', margin: '0 0 16px' }} />

        {/* 当前权益 */}
        <div style={{ fontSize: 16, fontWeight: 700, color: '#e2e8f0', marginBottom: 12 }}>当前权益</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 20 }}>
          {currentConfig && currentConfig.discount_rate < 1 && (
            <div style={{ fontSize: 16, color: '#e2e8f0' }}>
              <span style={{ color: '#22c55e', marginRight: 8 }}>✓</span>
              {discountLabel(currentConfig.discount_rate)}
            </div>
          )}
          {currentConfig && currentConfig.birthday_bonus_multiplier > 1 && (
            <div style={{ fontSize: 16, color: '#e2e8f0' }}>
              <span style={{ color: '#22c55e', marginRight: 8 }}>✓</span>
              生日 {currentConfig.birthday_bonus_multiplier}x 积分
            </div>
          )}
          {currentConfig?.priority_queue && (
            <div style={{ fontSize: 16, color: '#e2e8f0' }}>
              <span style={{ color: '#22c55e', marginRight: 8 }}>✓</span>
              等位优先排队
            </div>
          )}
          {currentConfig?.free_delivery && (
            <div style={{ fontSize: 16, color: '#e2e8f0' }}>
              <span style={{ color: '#22c55e', marginRight: 8 }}>✓</span>
              外卖免配送费
            </div>
          )}
          {(!currentConfig || (currentConfig.discount_rate >= 1 && !currentConfig.priority_queue && !currentConfig.free_delivery)) && (
            <div style={{ fontSize: 16, color: '#64748b' }}>暂无额外权益</div>
          )}
        </div>

        {/* 升降级历史 */}
        {levelHistory.length > 0 && (
          <>
            <div style={{ height: 1, background: '#1a2a33', margin: '0 0 14px' }} />
            <div style={{ fontSize: 16, fontWeight: 700, color: '#e2e8f0', marginBottom: 10 }}>等级变更记录</div>
            {levelHistory.slice(0, 3).map(h => (
              <div key={h.id} style={{
                fontSize: 14, color: '#64748b', padding: '6px 0',
                borderBottom: '1px solid #1a2a3322',
              }}>
                <span style={{ color: '#e2e8f0' }}>{h.from_level ?? '无'}</span>
                <span style={{ margin: '0 8px' }}>→</span>
                <span style={{ color: '#FF6B2C', fontWeight: 700 }}>{h.to_level}</span>
                <span style={{ marginLeft: 12 }}>{h.created_at.slice(0, 10)}</span>
              </div>
            ))}
          </>
        )}

        {/* 手动触发升级检查 */}
        <button
          onClick={onCheckUpgrade}
          disabled={upgrading}
          style={{
            width: '100%', minHeight: 52, borderRadius: 12, border: 'none',
            background: upgrading ? '#64748b' : '#FF6B35',
            color: '#ffffff', fontSize: 17, fontWeight: 700,
            cursor: upgrading ? 'default' : 'pointer', marginTop: 20,
          }}
        >
          {upgrading ? '检查中...' : '检查升级资格'}
        </button>
      </div>
    </div>
  );
}

/* ---------- 组件 ---------- */
export function MemberPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const orderId = searchParams.get('order_id') || '';

  const [keyword, setKeyword] = useState('');
  const [results, setResults] = useState<MemberInfo[]>([]);
  const [searched, setSearched] = useState(false);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<MemberInfo | null>(null);
  const [bound, setBound] = useState(false);
  const [binding, setBinding] = useState(false);
  const [bindError, setBindError] = useState('');
  const [insightDismissed, setInsightDismissed] = useState(false);

  // 储值相关
  const [svTxns, setSvTxns] = useState<StoredValueTransaction[]>([]);
  const [svExpanded, setSvExpanded] = useState(false);
  const [svLoading, setSvLoading] = useState(false);

  // 等级相关
  const [levelConfigs, setLevelConfigs] = useState<LevelConfig[]>([]);
  const [levelHistory, setLevelHistory] = useState<LevelHistoryItem[]>([]);
  const [showLevelSheet, setShowLevelSheet] = useState(false);
  const [upgrading, setUpgrading] = useState(false);
  const [upgradeMsg, setUpgradeMsg] = useState('');

  // 积分相关
  const [memberPoints, setMemberPoints] = useState<MemberPoints | null>(null);
  const [pointsLoading, setPointsLoading] = useState(false);
  const [pointsExpanded, setPointsExpanded] = useState(false);
  const [comingSoonToast, setComingSoonToast] = useState(false);

  // 加载储值交易明细
  useEffect(() => {
    if (!selected) { setSvTxns([]); return; }
    setSvLoading(true);
    getStoredValue(selected.member_id)
      .then(acc => setSvTxns(acc.transactions))
      .catch(() => setSvTxns([]))
      .finally(() => setSvLoading(false));
  }, [selected]);

  // 加载等级配置和历史
  useEffect(() => {
    fetchLevelConfigs(TENANT_ID)
      .then(res => setLevelConfigs(res.items))
      .catch(() => setLevelConfigs([]));
  }, []);

  useEffect(() => {
    if (!selected) { setLevelHistory([]); return; }
    fetchLevelHistory(selected.member_id)
      .then(res => setLevelHistory(res.items))
      .catch(() => setLevelHistory([]));
  }, [selected]);

  // 加载会员积分数据
  useEffect(() => {
    if (!selected) { setMemberPoints(null); return; }
    setPointsLoading(true);
    getMemberPoints(selected.member_id)
      .then(res => { if (res.ok) setMemberPoints(res.data); })
      .catch(() => setMemberPoints(null))
      .finally(() => setPointsLoading(false));
  }, [selected]);

  // 检查升级
  const handleCheckUpgrade = useCallback(async () => {
    if (!selected) return;
    setUpgrading(true);
    setUpgradeMsg('');
    try {
      const res = await checkMemberUpgrade(selected.member_id);
      if (res.upgraded) {
        setUpgradeMsg(`升级成功！${res.from_level} → ${res.to_level}`);
        // 刷新历史
        const hist = await fetchLevelHistory(selected.member_id);
        setLevelHistory(hist.items);
      } else {
        setUpgradeMsg(`当前等级: ${res.to_level}，积分${res.current_points}，无需变更`);
      }
    } catch {
      setUpgradeMsg('检查失败，请重试');
    } finally {
      setUpgrading(false);
    }
  }, [selected]);

  const handleSearch = useCallback(async () => {
    if (!keyword.trim()) return;
    setSearched(true);
    setSearching(true);
    setResults([]);
    setSelected(null);
    setBound(false);
    setBindError('');
    try {
      const res = await searchMember(keyword.trim());
      setResults(res.items);
    } catch {
      // 搜索失败静默处理，显示空结果
    } finally {
      setSearching(false);
    }
  }, [keyword]);

  const handleBind = async () => {
    if (!selected || !orderId) { setBound(true); return; }
    setBinding(true);
    setBindError('');
    try {
      await bindMemberToOrder(orderId, selected.member_id);
      setBound(true);
    } catch (err) {
      setBindError(err instanceof Error ? err.message : '关联失败，请重试');
    } finally {
      setBinding(false);
    }
  };

  return (
    <div style={{ padding: '16px 12px 80px', background: C.bg, minHeight: '100vh' }}>
      <h1 style={{ fontSize: 20, fontWeight: 700, color: C.white, margin: '0 0 4px' }}>
        会员识别
      </h1>
      <p style={{ fontSize: 16, color: C.muted, margin: '0 0 16px' }}>
        搜索会员并关联当前订单
      </p>

      {/* 搜索栏 */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <input
          type="text"
          inputMode="tel"
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSearch()}
          placeholder="手机号 / 卡号 / 姓名"
          style={{
            flex: 1, padding: 14, fontSize: 18,
            background: C.card, border: `1px solid ${C.border}`,
            borderRadius: 12, color: C.white,
          }}
        />
        <button
          onClick={handleSearch}
          style={{
            minWidth: 72, minHeight: 48, borderRadius: 12,
            background: C.accent, color: C.white, border: 'none',
            fontSize: 16, fontWeight: 700, cursor: 'pointer',
          }}
        >
          搜索
        </button>
      </div>

      {/* 搜索结果 */}
      {searching && (
        <div style={{ textAlign: 'center', padding: 40, color: C.muted, fontSize: 16 }}>搜索中...</div>
      )}
      {searched && !searching && results.length === 0 && (
        <div style={{ textAlign: 'center', padding: 40, color: C.muted, fontSize: 16 }}>
          未找到匹配的会员
        </div>
      )}

      {results.map(m => {
        const isSelected = selected?.member_id === m.member_id;
        return (
          <button
            key={m.member_id}
            onClick={() => { setSelected(m); setBound(false); setBindError(''); setInsightDismissed(false); }}
            style={{
              display: 'block', width: '100%', textAlign: 'left',
              padding: 16, marginBottom: 10, borderRadius: 12,
              background: isSelected ? `${C.accent}11` : C.card,
              border: isSelected ? `2px solid ${C.accent}` : `1px solid ${C.border}`,
              cursor: 'pointer',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                {/* 头像 */}
                <div style={{
                  width: 48, height: 48, borderRadius: 24,
                  background: `linear-gradient(135deg, ${C.accent}, ${C.green})`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 18, fontWeight: 700, color: C.white, flexShrink: 0,
                }}>
                  {m.name.slice(-1)}
                </div>
                <div>
                  <div style={{ fontSize: 18, fontWeight: 600, color: C.white }}>{m.name}</div>
                  <div style={{ fontSize: 16, color: C.muted }}>{m.phone}</div>
                </div>
              </div>
              <span style={{
                fontSize: 16, fontWeight: 700, padding: '4px 10px',
                borderRadius: 6, background: `${levelColor(m.level)}22`,
                color: levelColor(m.level),
              }}>
                {m.level}
              </span>
            </div>
          </button>
        );
      })}

      {/* 会员详情 */}
      {selected && (
        <div style={{
          background: C.card, borderRadius: 12, padding: 16, marginTop: 8,
          border: `1px solid ${C.border}`,
        }}>
          {/* 标题行 + 等级badge */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
            <h2 style={{ fontSize: 18, fontWeight: 700, color: C.white, margin: 0 }}>
              {selected.name} 会员详情
            </h2>
            <button
              onClick={() => setShowLevelSheet(true)}
              style={{
                minHeight: 36, padding: '0 12px', borderRadius: 8, border: 'none',
                background: `${levelColor(selected.level)}22`,
                color: levelColor(selected.level),
                fontSize: 15, fontWeight: 700, cursor: 'pointer',
              }}
            >
              {selected.level} ›
            </button>
          </div>

          {/* 积分进度条（到下一等级）*/}
          {(() => {
            const currentConfig = levelConfigs.find(c =>
              c.level_code === selected.level ||
              c.level_name === selected.level ||
              c.level_name.startsWith(selected.level),
            );
            if (!currentConfig) return null;
            const { nextLevel, pointsNeeded, progressPct } = calcPointsToNextLevel(
              levelConfigs, currentConfig.level_code, selected.points,
            );
            if (!nextLevel) return null;
            return (
              <div style={{ marginBottom: 14 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14, color: C.muted, marginBottom: 5 }}>
                  <span>距离{nextLevel.level_name}</span>
                  <span style={{ color: C.accent }}>还差 {pointsNeeded.toLocaleString()} 积分</span>
                </div>
                <div style={{ height: 6, borderRadius: 3, background: C.border, overflow: 'hidden' }}>
                  <div style={{
                    height: '100%', borderRadius: 3,
                    width: `${progressPct}%`,
                    background: getLevelColor(currentConfig.level_code) || C.accent,
                  }} />
                </div>
              </div>
            );
          })()}

          {/* 升级检查提示 */}
          {upgradeMsg && (
            <div style={{
              fontSize: 14, color: C.green, padding: '8px 12px', borderRadius: 8,
              background: `${C.green}15`, border: `1px solid ${C.green}30`,
              marginBottom: 12,
            }}>
              {upgradeMsg}
            </div>
          )}

          {/* MemberPointsCard — 积分卡片 */}
          {pointsLoading && (
            <div style={{
              background: C.card, borderRadius: 12, padding: 20,
              border: `1px solid ${C.border}`, marginBottom: 14,
            }}>
              {/* 骨架屏 */}
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
                <div style={{ height: 20, width: 80, borderRadius: 6, background: C.border }} />
                <div style={{ height: 28, width: 90, borderRadius: 20, background: C.border }} />
              </div>
              <div style={{ height: 80, borderRadius: 10, background: C.border, marginBottom: 14 }} />
              <div style={{ height: 10, borderRadius: 5, background: C.border, marginBottom: 10 }} />
              <div style={{ display: 'flex', gap: 10 }}>
                <div style={{ flex: 1, height: 48, borderRadius: 10, background: C.border }} />
                <div style={{ flex: 1, height: 48, borderRadius: 10, background: C.border }} />
              </div>
            </div>
          )}
          {!pointsLoading && memberPoints && (() => {
            const nextCfg = levelConfigs.find(c => c.level_code === memberPoints.level)
              ? (() => {
                  const sorted = [...levelConfigs].sort((a, b) => a.sort_order - b.sort_order);
                  const idx = sorted.findIndex(c => c.level_code === memberPoints.level);
                  return idx >= 0 && idx < sorted.length - 1 ? sorted[idx + 1] : null;
                })()
              : null;
            return (
              <div style={{ marginBottom: 14 }}>
                <MemberPointsCard
                  memberId={memberPoints.member_id}
                  memberName={selected!.name}
                  currentLevel={memberPoints.level}
                  points={memberPoints.current_points}
                  nextLevelPoints={nextCfg ? nextCfg.min_points : memberPoints.next_level_threshold}
                  nextLevel={nextCfg ? nextCfg.level_name : ''}
                  onViewDetail={() => navigate(`/member-points?id=${encodeURIComponent(selected!.member_id)}&name=${encodeURIComponent(selected!.name)}`)}
                  onRecharge={() => navigate(`/stored-value-recharge?member_id=${encodeURIComponent(selected!.member_id)}&member_name=${encodeURIComponent(selected!.name)}`)}
                />
              </div>
            );
          })()}

          {/* 积分明细折叠列表 */}
          {!pointsLoading && memberPoints && memberPoints.transactions.length > 0 && (
            <div style={{ marginBottom: 14 }}>
              <button
                onClick={() => setPointsExpanded(e => !e)}
                style={{
                  width: '100%', minHeight: 44, borderRadius: 8,
                  background: C.bg, border: `1px solid ${C.border}`,
                  color: C.text, fontSize: 16, fontWeight: 600,
                  cursor: 'pointer', display: 'flex',
                  alignItems: 'center', justifyContent: 'space-between',
                  padding: '0 14px',
                }}
              >
                <span>积分明细</span>
                <span style={{ color: C.muted }}>{pointsExpanded ? '▲' : '▼'}</span>
              </button>
              {pointsExpanded && (
                <div style={{ marginTop: 8 }}>
                  {memberPoints.transactions.slice(0, 10).map(t => (
                    <div key={t.id} style={{
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      padding: '10px 0', borderBottom: `1px solid ${C.border}`,
                    }}>
                      <div>
                        <div style={{ fontSize: 16, color: C.text }}>{t.reason}</div>
                        <div style={{ fontSize: 14, color: C.muted, marginTop: 2 }}>
                          {t.created_at.slice(0, 10)}
                        </div>
                      </div>
                      <span style={{
                        fontSize: 18, fontWeight: 700,
                        color: t.change >= 0 ? C.green : C.red,
                      }}>
                        {t.change >= 0 ? `+${t.change}` : `${t.change}`}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* 快捷操作区 */}
          <div style={{
            display: 'grid', gridTemplateColumns: '1fr 1fr 1fr',
            gap: 10, marginBottom: 14,
          }}>
            {/* 积分兑换（即将上线） */}
            <button
              onClick={() => {
                setComingSoonToast(true);
                setTimeout(() => setComingSoonToast(false), 2000);
              }}
              style={{
                minHeight: 72, borderRadius: 10,
                background: C.bg, border: `1px solid ${C.border}`,
                color: C.muted, fontSize: 14, fontWeight: 600,
                cursor: 'pointer', display: 'flex',
                flexDirection: 'column', alignItems: 'center',
                justifyContent: 'center', gap: 6, padding: 8,
              }}
            >
              <span style={{ fontSize: 24 }}>🎁</span>
              <span style={{ fontSize: 14 }}>积分兑换</span>
            </button>
            {/* 充值储值 */}
            <button
              onClick={() => navigate(`/stored-value-recharge?member_id=${encodeURIComponent(selected!.member_id)}&member_name=${encodeURIComponent(selected!.name)}`)}
              style={{
                minHeight: 72, borderRadius: 10,
                background: `${C.green}15`, border: `1px solid ${C.green}40`,
                color: C.green, fontSize: 14, fontWeight: 600,
                cursor: 'pointer', display: 'flex',
                flexDirection: 'column', alignItems: 'center',
                justifyContent: 'center', gap: 6, padding: 8,
              }}
            >
              <span style={{ fontSize: 24 }}>💳</span>
              <span style={{ fontSize: 14 }}>充值储值</span>
            </button>
            {/* 消费记录（折叠查看） */}
            <button
              onClick={() => setSvExpanded(e => !e)}
              style={{
                minHeight: 72, borderRadius: 10,
                background: C.bg, border: `1px solid ${C.border}`,
                color: C.muted, fontSize: 14, fontWeight: 600,
                cursor: 'pointer', display: 'flex',
                flexDirection: 'column', alignItems: 'center',
                justifyContent: 'center', gap: 6, padding: 8,
              }}
            >
              <span style={{ fontSize: 24 }}>📊</span>
              <span style={{ fontSize: 14 }}>消费记录</span>
            </button>
          </div>

          {/* 即将上线 Toast */}
          {comingSoonToast && (
            <div style={{
              position: 'fixed', bottom: 100, left: '50%', transform: 'translateX(-50%)',
              background: '#1E3A45', color: C.text, fontSize: 16, fontWeight: 600,
              padding: '12px 24px', borderRadius: 24, zIndex: 500,
              border: `1px solid ${C.border}`,
              whiteSpace: 'nowrap',
              boxShadow: '0 4px 20px rgba(0,0,0,0.4)',
            }}>
              积分兑换功能即将上线
            </div>
          )}

          {/* 积分/余额/来店 */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 12 }}>
            <div style={{
              background: C.bg, borderRadius: 8, padding: 12, textAlign: 'center',
            }}>
              <div style={{ fontSize: 16, color: C.muted }}>积分</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: C.accent, marginTop: 4 }}>
                {selected.points.toLocaleString()}
              </div>
            </div>
            <div style={{
              background: C.bg, borderRadius: 8, padding: 12, textAlign: 'center',
            }}>
              <div style={{ fontSize: 16, color: C.muted }}>余额</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: C.green, marginTop: 4 }}>
                {'\u00A5'}{((selected.balance_fen ?? 0) / 100).toFixed(0)}
              </div>
            </div>
            <div style={{
              background: C.bg, borderRadius: 8, padding: 12, textAlign: 'center',
            }}>
              <div style={{ fontSize: 16, color: C.muted }}>来店</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: C.white, marginTop: 4 }}>
                {selected.visit_count}次
              </div>
            </div>
          </div>

          {/* 充值按钮 */}
          <button
            onClick={() => navigate(`/stored-value-recharge?member_id=${encodeURIComponent(selected.member_id)}&member_name=${encodeURIComponent(selected.name)}`)}
            style={{
              width: '100%', minHeight: 48, borderRadius: 10,
              background: `${C.green}22`, border: `1px solid ${C.green}55`,
              color: C.green, fontSize: 17, fontWeight: 700,
              cursor: 'pointer', marginBottom: 16,
            }}
          >
            + 储值充值
          </button>

          {/* 交易明细折叠 */}
          <div style={{ marginBottom: 16 }}>
            <button
              onClick={() => setSvExpanded(e => !e)}
              style={{
                width: '100%', minHeight: 44, borderRadius: 8,
                background: C.bg, border: `1px solid ${C.border}`,
                color: C.text, fontSize: 16, fontWeight: 600,
                cursor: 'pointer', display: 'flex',
                alignItems: 'center', justifyContent: 'space-between',
                padding: '0 14px',
              }}
            >
              <span>交易明细</span>
              <span style={{ color: C.muted }}>{svExpanded ? '▲' : '▼'}</span>
            </button>

            {svExpanded && (
              <div style={{ marginTop: 8 }}>
                {svLoading && (
                  <div style={{ fontSize: 16, color: C.muted, textAlign: 'center', padding: 16 }}>加载中...</div>
                )}
                {!svLoading && svTxns.length === 0 && (
                  <div style={{ fontSize: 16, color: C.muted, textAlign: 'center', padding: 16 }}>暂无交易记录</div>
                )}
                {!svLoading && svTxns.slice(0, svExpanded ? 5 : 5).map(t => (
                  <div key={t.id} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '10px 0', borderBottom: `1px solid ${C.border}`,
                  }}>
                    <div>
                      <span style={{
                        fontSize: 14, fontWeight: 700, color: txnColor(t.type),
                        background: `${txnColor(t.type)}18`, padding: '2px 8px',
                        borderRadius: 5, marginRight: 8,
                      }}>
                        {txnLabel(t.type)}
                      </span>
                      <span style={{ fontSize: 14, color: C.muted }}>
                        {t.created_at ? t.created_at.slice(0, 16).replace('T', ' ') : ''}
                      </span>
                      {t.note && (
                        <div style={{ fontSize: 13, color: C.muted, marginTop: 2 }}>{t.note}</div>
                      )}
                    </div>
                    <span style={{
                      fontSize: 17, fontWeight: 700,
                      color: t.amount_fen >= 0 ? C.green : C.red,
                    }}>
                      {t.amount_fen >= 0 ? '+' : '-'}¥{fen2yuanStr(t.amount_fen)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 偏好 */}
          {selected.preferences.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 16, color: C.muted, marginBottom: 8 }}>口味偏好</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {selected.preferences.map(pref => (
                  <span key={pref} style={{
                    fontSize: 16, padding: '6px 12px', borderRadius: 8,
                    background: `${C.info}22`, color: '#5b9bd5',
                  }}>
                    {pref}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* 过敏/忌口：待后端 CDP 扩展字段后接入 */}

          <div style={{ fontSize: 16, color: C.muted, marginBottom: 16 }}>
            上次来店: {selected.last_visit}
          </div>

          {bindError && (
            <div style={{ fontSize: 16, color: '#ef4444', marginBottom: 10 }}>{bindError}</div>
          )}

          {/* 关联订单 */}
          <button
            onClick={handleBind}
            disabled={bound || binding}
            style={{
              width: '100%', minHeight: 56, borderRadius: 12,
              background: bound ? C.green : binding ? C.muted : C.accent,
              color: C.white, border: 'none',
              fontSize: 18, fontWeight: 700, cursor: (bound || binding) ? 'default' : 'pointer',
            }}
          >
            {bound ? '✓ 已关联当前订单' : binding ? '关联中...' : orderId ? '关联当前订单' : '查看会员信息'}
          </button>

          {/* 会员洞察卡片：关联成功后自动展示 */}
          {bound && selected && orderId && !insightDismissed && (
            <MemberInsightCard
              memberId={selected.member_id}
              memberName={selected.name}
              memberLevel={selected.level}
              orderId={orderId}
              onDismiss={() => setInsightDismissed(true)}
            />
          )}
        </div>
      )}

      {/* 等级权益 Sheet */}
      {showLevelSheet && selected && (
        <LevelBenefitSheet
          member={selected}
          configs={levelConfigs}
          levelHistory={levelHistory}
          onClose={() => setShowLevelSheet(false)}
          onCheckUpgrade={async () => {
            setShowLevelSheet(false);
            await handleCheckUpgrade();
          }}
          upgrading={upgrading}
        />
      )}
    </div>
  );
}
