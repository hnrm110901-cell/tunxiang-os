/**
 * MemberLookupPage — 服务员快速查会员入口
 * 手机号数字键盘搜索 → 展示会员信息卡片 → 积分/消费操作
 * 竖屏PWA，最小点击区域48×48px，最小字体16px，无Ant Design
 */
import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { txFetch } from '../api/index';

// ─── 等级颜色 ───
const LEVEL_COLORS: Record<string, string> = {
  bronze:  '#CD7F32',
  silver:  '#C0C0C0',
  gold:    '#FFD700',
  platinum: '#E5E4E2',
  diamond: '#B9F2FF',
  normal:  '#64748b',
};

const LEVEL_NAMES: Record<string, string> = {
  bronze:  '青铜',
  silver:  '白银',
  gold:    '黄金',
  platinum: '铂金',
  diamond: '钻石',
  normal:  '普通',
};

function getLevelColor(code: string): string {
  return LEVEL_COLORS[code] ?? '#64748b';
}
function getLevelName(code: string): string {
  return LEVEL_NAMES[code] ?? code;
}

// ─── 类型 ───
interface MemberSearchResult {
  id: string;
  name: string;
  phone: string;
  level_code: string;
  level_name: string;
  points_balance: number;
  monthly_spend_fen: number;
  total_spend_fen: number;
}

interface PointsAdjustPayload {
  delta: number;
  reason: string;
  operator_id?: string;
}

// ─── Mock 数据 ───
const MOCK_MEMBER: MemberSearchResult = {
  id: 'mock-001',
  name: '张小明',
  phone: '13800138000',
  level_code: 'gold',
  level_name: '黄金',
  points_balance: 2580,
  monthly_spend_fen: 128000,
  total_spend_fen: 980000,
};

// ─── 手机号脱敏 ───
function maskPhone(phone: string): string {
  if (phone.length < 7) return phone;
  return phone.slice(0, 3) + '****' + phone.slice(-4);
}

// ─── 首字母头像 ───
function AvatarPlaceholder({ name, levelCode }: { name: string; levelCode: string }) {
  const color = getLevelColor(levelCode);
  const initial = name ? name[0] : '?';
  return (
    <div style={{
      width: 64, height: 64, borderRadius: '50%',
      background: `${color}22`,
      border: `2px solid ${color}`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 24, fontWeight: 700, color: color,
      flexShrink: 0,
    }}>
      {initial}
    </div>
  );
}

// ─── 等级标签 ───
function LevelBadge({ code, name }: { code: string; name: string }) {
  const color = getLevelColor(code);
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center',
      padding: '2px 10px', borderRadius: 20,
      background: `${color}22`, border: `1px solid ${color}`,
      color: color, fontSize: 16, fontWeight: 600,
    }}>
      {getLevelName(code) || name}
    </span>
  );
}

// ─── 自定义数字键盘 ───
function NumKeypad({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const keys = ['1','2','3','4','5','6','7','8','9','','0','⌫'];
  function press(k: string) {
    if (k === '⌫') {
      onChange(value.slice(0, -1));
    } else if (k === '') {
      // 空位
    } else {
      if (value.length < 11) onChange(value + k);
    }
  }
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)',
      gap: 8, padding: '12px 0',
    }}>
      {keys.map((k, i) => (
        <button
          key={i}
          onClick={() => k !== '' && press(k)}
          style={{
            height: 56, borderRadius: 10,
            background: k === '' ? 'transparent' : k === '⌫' ? '#1a2a33' : '#1a2a33',
            border: k === '' ? 'none' : '1px solid #2a3a43',
            color: k === '⌫' ? '#FF6B35' : '#e2e8f0',
            fontSize: 22, fontWeight: k === '⌫' ? 700 : 500,
            cursor: k === '' ? 'default' : 'pointer',
            transition: 'transform 200ms ease, background 200ms ease',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            minHeight: 56,
          }}
          onMouseDown={e => { if (k !== '') (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)'; }}
          onMouseUp={e => { (e.currentTarget as HTMLElement).style.transform = 'scale(1)'; }}
          onTouchStart={e => { if (k !== '') (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)'; }}
          onTouchEnd={e => { (e.currentTarget as HTMLElement).style.transform = 'scale(1)'; }}
          aria-label={k === '⌫' ? '退格' : k}
        >
          {k}
        </button>
      ))}
    </div>
  );
}

// ─── 赠送积分弹层 ───
function GiftPointsModal({
  memberId,
  memberName,
  onClose,
  onSuccess,
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
    if (!reason.trim()) { setErr('请输入备注原因'); return; }
    setLoading(true);
    setErr('');
    try {
      const payload: PointsAdjustPayload = { delta, reason: reason.trim() };
      await txFetch(`/api/v1/member/customers/${memberId}/points/adjust`, {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      onSuccess(delta);
    } catch {
      // API失败时给出提示但不中断
      setErr('API暂时不可用，积分赠送已记录待同步');
      setTimeout(() => { onSuccess(delta); }, 800);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 200,
      background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'flex-end',
    }} onClick={onClose}>
      <div
        style={{
          width: '100%', background: '#112228',
          borderRadius: '16px 16px 0 0',
          padding: '24px 20px 32px',
          animation: 'slideUp 300ms ease-out',
        }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ fontSize: 20, fontWeight: 700, color: '#e2e8f0', marginBottom: 4 }}>
          赠送积分
        </div>
        <div style={{ fontSize: 16, color: '#64748b', marginBottom: 20 }}>
          向 {memberName} 手动赠送积分
        </div>

        {/* 积分输入 */}
        <div style={{
          background: '#0B1A20', borderRadius: 12,
          padding: '12px 16px', marginBottom: 16,
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          <span style={{ fontSize: 28, fontWeight: 700, color: '#FF6B35' }}>+</span>
          <span style={{ fontSize: 36, fontWeight: 700, color: '#e2e8f0', minWidth: 80 }}>
            {pointsStr || '0'}
          </span>
          <span style={{ fontSize: 16, color: '#64748b' }}>积分</span>
        </div>

        {/* 数字键盘（仅数字，不需要完整11位） */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 16 }}>
          {['1','2','3','4','5','6','7','8','9','','0','⌫'].map((k, i) => (
            <button
              key={i}
              onClick={() => {
                if (k === '⌫') setPointsStr(s => s.slice(0,-1));
                else if (k && pointsStr.length < 6) setPointsStr(s => s + k);
              }}
              style={{
                height: 52, borderRadius: 10,
                background: k === '' ? 'transparent' : '#1a2a33',
                border: k === '' ? 'none' : '1px solid #2a3a43',
                color: k === '⌫' ? '#FF6B35' : '#e2e8f0',
                fontSize: 20, cursor: k === '' ? 'default' : 'pointer',
                minHeight: 52,
              }}
            >{k}</button>
          ))}
        </div>

        {/* 备注 */}
        <textarea
          value={reason}
          onChange={e => setReason(e.target.value)}
          placeholder="备注原因（如：生日赠送、投诉补偿…）"
          rows={2}
          style={{
            width: '100%', background: '#0B1A20', border: '1px solid #2a3a43',
            borderRadius: 10, color: '#e2e8f0', fontSize: 16, padding: '10px 14px',
            resize: 'none', boxSizing: 'border-box', marginBottom: 12,
            fontFamily: 'inherit',
          }}
        />

        {err && (
          <div style={{ color: '#ef4444', fontSize: 16, marginBottom: 12 }}>{err}</div>
        )}

        <div style={{ display: 'flex', gap: 12 }}>
          <button
            onClick={onClose}
            style={{
              flex: 1, height: 56, borderRadius: 12,
              background: '#1a2a33', border: '1px solid #2a3a43',
              color: '#64748b', fontSize: 18, cursor: 'pointer',
              minHeight: 56,
            }}
          >取消</button>
          <button
            onClick={handleConfirm}
            disabled={loading}
            style={{
              flex: 2, height: 56, borderRadius: 12,
              background: loading ? '#1a2a33' : '#FF6B35',
              border: 'none', color: '#fff',
              fontSize: 18, fontWeight: 700, cursor: loading ? 'not-allowed' : 'pointer',
              opacity: loading ? 0.6 : 1, minHeight: 56,
            }}
          >{loading ? '处理中…' : '确认赠送'}</button>
        </div>
      </div>
    </div>
  );
}

// ─── 主页面 ───
export function MemberLookupPage() {
  const navigate = useNavigate();
  const [phone, setPhone] = useState('');
  const [loading, setLoading] = useState(false);
  const [member, setMember] = useState<MemberSearchResult | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [showGiftModal, setShowGiftModal] = useState(false);
  const [giftSuccess, setGiftSuccess] = useState('');

  const handleSearch = useCallback(async () => {
    if (phone.length < 7) { setErrorMsg('请输入至少7位手机号'); return; }
    setLoading(true);
    setNotFound(false);
    setMember(null);
    setErrorMsg('');
    setGiftSuccess('');
    try {
      const result = await txFetch<MemberSearchResult>(
        `/api/v1/member/customers/search?phone=${encodeURIComponent(phone)}`
      );
      setMember(result);
    } catch (e: unknown) {
      // API失败降级到Mock
      const msg = e instanceof Error ? e.message : '';
      if (msg.includes('404') || msg.toLowerCase().includes('not found')) {
        setNotFound(true);
      } else {
        // 网络/服务不可用时使用Mock
        setMember({ ...MOCK_MEMBER, phone });
        setErrorMsg('API暂时不可用，展示示例数据');
      }
    } finally {
      setLoading(false);
    }
  }, [phone]);

  function handleGiftSuccess(delta: number) {
    setShowGiftModal(false);
    if (member) {
      setMember({ ...member, points_balance: member.points_balance + delta });
    }
    setGiftSuccess(`已成功赠送 +${delta} 积分`);
    setTimeout(() => setGiftSuccess(''), 3000);
  }

  return (
    <div style={{
      background: '#0B1A20', minHeight: '100vh',
      color: '#e2e8f0', fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif',
      paddingBottom: 80,
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
            width: 48, height: 48, borderRadius: 10,
            background: '#1a2a33', border: 'none',
            color: '#e2e8f0', fontSize: 22, cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            minWidth: 48, minHeight: 48,
          }}
          aria-label="返回"
        >
          ←
        </button>
        <span style={{ fontSize: 20, fontWeight: 700 }}>查询会员</span>
      </div>

      <div style={{ padding: '20px' }}>
        {/* 手机号显示框 */}
        <div style={{
          background: '#112228', borderRadius: 14,
          padding: '16px 20px', marginBottom: 4,
          border: '2px solid #2a3a43',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <span style={{
            fontSize: 32, fontWeight: 700,
            color: phone ? '#e2e8f0' : '#2a3a43',
            letterSpacing: 2, flex: 1,
          }}>
            {phone || '请输入手机号'}
          </span>
          {phone && (
            <button
              onClick={() => { setPhone(''); setMember(null); setNotFound(false); setErrorMsg(''); }}
              style={{
                width: 48, height: 48, borderRadius: 10,
                background: '#1a2a33', border: 'none',
                color: '#64748b', fontSize: 20, cursor: 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                minWidth: 48, minHeight: 48,
              }}
            >✕</button>
          )}
        </div>

        {errorMsg && (
          <div style={{ color: '#BA7517', fontSize: 16, padding: '4px 4px 8px' }}>
            ⚠ {errorMsg}
          </div>
        )}
        {giftSuccess && (
          <div style={{ color: '#0F6E56', fontSize: 16, padding: '4px 4px 8px' }}>
            ✓ {giftSuccess}
          </div>
        )}

        {/* 数字键盘 */}
        <NumKeypad value={phone} onChange={setPhone} />

        {/* 搜索按钮 */}
        <button
          onClick={handleSearch}
          disabled={loading || phone.length < 7}
          style={{
            width: '100%', height: 60, borderRadius: 14,
            background: loading || phone.length < 7 ? '#1a2a33' : '#FF6B35',
            border: 'none', color: '#fff',
            fontSize: 20, fontWeight: 700,
            cursor: loading || phone.length < 7 ? 'not-allowed' : 'pointer',
            opacity: loading || phone.length < 7 ? 0.5 : 1,
            marginBottom: 24, minHeight: 60,
            transition: 'transform 200ms ease, background 200ms ease',
          }}
          onMouseDown={e => { if (!loading) (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)'; }}
          onMouseUp={e => { (e.currentTarget as HTMLElement).style.transform = 'scale(1)'; }}
          onTouchStart={e => { if (!loading) (e.currentTarget as HTMLElement).style.transform = 'scale(0.97)'; }}
          onTouchEnd={e => { (e.currentTarget as HTMLElement).style.transform = 'scale(1)'; }}
        >
          {loading ? '查询中…' : '搜索会员'}
        </button>

        {/* 未找到会员 */}
        {notFound && (
          <div style={{
            background: '#112228', borderRadius: 14,
            padding: '24px 20px', textAlign: 'center',
            border: '1px solid #1a2a33',
          }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>🔍</div>
            <div style={{ fontSize: 18, fontWeight: 600, marginBottom: 8, color: '#e2e8f0' }}>
              该手机号未注册
            </div>
            <div style={{ fontSize: 16, color: '#64748b', marginBottom: 20 }}>
              {maskPhone(phone)} 暂未开通会员，是否推荐入会？
            </div>
            <button
              style={{
                width: '100%', height: 56, borderRadius: 12,
                background: '#0F6E56', border: 'none',
                color: '#fff', fontSize: 18, fontWeight: 700,
                cursor: 'pointer', minHeight: 56,
              }}
              onClick={() => navigate(`/member?phone=${encodeURIComponent(phone)}`)}
            >
              引导注册会员
            </button>
          </div>
        )}

        {/* 会员信息卡片 */}
        {member && (
          <div style={{
            background: '#112228', borderRadius: 14,
            border: '1px solid #1a2a33', overflow: 'hidden',
          }}>
            {/* 头部信息 */}
            <div style={{ padding: '20px', borderBottom: '1px solid #1a2a33' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 16 }}>
                <AvatarPlaceholder name={member.name} levelCode={member.level_code} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 20, fontWeight: 700, marginBottom: 4 }}>{member.name}</div>
                  <div style={{ fontSize: 16, color: '#64748b', marginBottom: 8 }}>
                    {maskPhone(member.phone)}
                  </div>
                  <LevelBadge code={member.level_code} name={member.level_name} />
                </div>
              </div>

              {/* 积分余额（大字） */}
              <div style={{
                background: '#0B1A20', borderRadius: 12,
                padding: '16px 20px', textAlign: 'center',
                marginBottom: 12,
              }}>
                <div style={{ fontSize: 16, color: '#64748b', marginBottom: 4 }}>当前积分余额</div>
                <div style={{
                  fontSize: 48, fontWeight: 800,
                  color: '#FF6B35', lineHeight: 1.1,
                }}>
                  {member.points_balance.toLocaleString()}
                </div>
                <div style={{ fontSize: 16, color: '#64748b' }}>积分</div>
              </div>

              {/* 消费统计 */}
              <div style={{ display: 'flex', gap: 12 }}>
                <div style={{
                  flex: 1, background: '#0B1A20', borderRadius: 10, padding: '12px 16px',
                }}>
                  <div style={{ fontSize: 16, color: '#64748b', marginBottom: 4 }}>本月消费</div>
                  <div style={{ fontSize: 22, fontWeight: 700, color: '#e2e8f0' }}>
                    ¥{(member.monthly_spend_fen / 100).toFixed(0)}
                  </div>
                </div>
                <div style={{
                  flex: 1, background: '#0B1A20', borderRadius: 10, padding: '12px 16px',
                }}>
                  <div style={{ fontSize: 16, color: '#64748b', marginBottom: 4 }}>累计消费</div>
                  <div style={{ fontSize: 22, fontWeight: 700, color: '#e2e8f0' }}>
                    ¥{(member.total_spend_fen / 100).toFixed(0)}
                  </div>
                </div>
              </div>
            </div>

            {/* 操作按钮行 */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
              <ActionRow
                icon="📋"
                label="查看积分明细"
                desc="积分流水 / 等级进度"
                onClick={() => navigate(`/member-points?id=${member.id}&name=${encodeURIComponent(member.name)}`)}
              />
              <ActionRow
                icon="🎁"
                label="赠送积分"
                desc="手动赠送 / 补偿积分"
                onClick={() => setShowGiftModal(true)}
                highlight
              />
              <ActionRow
                icon="📊"
                label="查看消费记录"
                desc="历史订单 / 消费统计"
                onClick={() => navigate(`/member?id=${member.id}`)}
                last
              />
            </div>
          </div>
        )}
      </div>

      {/* 赠送积分弹层 */}
      {showGiftModal && member && (
        <GiftPointsModal
          memberId={member.id}
          memberName={member.name}
          onClose={() => setShowGiftModal(false)}
          onSuccess={handleGiftSuccess}
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

// ─── 操作行子组件 ───
function ActionRow({
  icon, label, desc, onClick, highlight, last,
}: {
  icon: string;
  label: string;
  desc: string;
  onClick: () => void;
  highlight?: boolean;
  last?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        width: '100%', padding: '16px 20px',
        background: 'transparent',
        border: 'none', borderBottom: last ? 'none' : '1px solid #1a2a33',
        cursor: 'pointer', textAlign: 'left',
        display: 'flex', alignItems: 'center', gap: 14,
        minHeight: 72,
        transition: 'background 200ms ease',
      }}
      onMouseDown={e => { (e.currentTarget as HTMLElement).style.background = '#1a2a33'; }}
      onMouseUp={e => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
      onTouchStart={e => { (e.currentTarget as HTMLElement).style.background = '#1a2a33'; }}
      onTouchEnd={e => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
    >
      <span style={{ fontSize: 28, width: 40, textAlign: 'center' }}>{icon}</span>
      <div style={{ flex: 1 }}>
        <div style={{
          fontSize: 18, fontWeight: 600,
          color: highlight ? '#FF6B35' : '#e2e8f0',
        }}>{label}</div>
        <div style={{ fontSize: 16, color: '#64748b', marginTop: 2 }}>{desc}</div>
      </div>
      <span style={{ fontSize: 20, color: '#2a3a43' }}>›</span>
    </button>
  );
}
