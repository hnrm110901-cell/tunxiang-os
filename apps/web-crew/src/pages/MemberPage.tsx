/**
 * 会员识别页面 — 搜索会员 → 查看等级/积分/偏好 → 关联当前订单
 * 移动端竖屏, 最小字体16px, 热区>=48px
 */
import { useState } from 'react';

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
};

/* ---------- Mock 数据 ---------- */
interface MockMember {
  id: string;
  name: string;
  phone: string;
  level: string;
  points: number;
  balanceYuan: number;
  preferences: string[];
  visitCount: number;
  lastVisit: string;
}

const MOCK_MEMBERS: MockMember[] = [
  {
    id: 'm1', name: '王建国', phone: '138****1234', level: '金卡',
    points: 12680, balanceYuan: 856, preferences: ['不吃香菜', '微辣', '喜欢鱼类'],
    visitCount: 46, lastVisit: '2026-03-25',
  },
  {
    id: 'm2', name: '李晓红', phone: '139****5678', level: '银卡',
    points: 5200, balanceYuan: 320, preferences: ['不吃辣', '少盐'],
    visitCount: 18, lastVisit: '2026-03-20',
  },
  {
    id: 'm3', name: '张伟', phone: '136****9012', level: '普通',
    points: 860, balanceYuan: 0, preferences: [],
    visitCount: 3, lastVisit: '2026-02-14',
  },
];

function levelColor(level: string): string {
  if (level === '金卡') return C.gold;
  if (level === '银卡') return '#c0c0c0';
  if (level === '黑金') return C.white;
  return C.muted;
}

/* ---------- 组件 ---------- */
export function MemberPage() {
  const [keyword, setKeyword] = useState('');
  const [results, setResults] = useState<MockMember[]>([]);
  const [searched, setSearched] = useState(false);
  const [selected, setSelected] = useState<MockMember | null>(null);
  const [bound, setBound] = useState(false);

  const handleSearch = () => {
    if (!keyword.trim()) return;
    setSearched(true);
    // 模拟搜索: 匹配手机号或姓名
    const kw = keyword.trim().toLowerCase();
    const matched = MOCK_MEMBERS.filter(
      m => m.phone.includes(kw) || m.name.toLowerCase().includes(kw),
    );
    setResults(matched);
    setSelected(null);
    setBound(false);
  };

  const handleBind = () => {
    if (!selected) return;
    setBound(true);
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
      {searched && results.length === 0 && (
        <div style={{ textAlign: 'center', padding: 40, color: C.muted, fontSize: 16 }}>
          未找到匹配的会员
        </div>
      )}

      {results.map(m => {
        const isSelected = selected?.id === m.id;
        return (
          <button
            key={m.id}
            onClick={() => { setSelected(m); setBound(false); }}
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
          <h2 style={{ fontSize: 18, fontWeight: 700, color: C.white, margin: '0 0 14px' }}>
            {selected.name} 会员详情
          </h2>

          {/* 积分/余额/来店 */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 16 }}>
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
                {'\u00A5'}{selected.balanceYuan}
              </div>
            </div>
            <div style={{
              background: C.bg, borderRadius: 8, padding: 12, textAlign: 'center',
            }}>
              <div style={{ fontSize: 16, color: C.muted }}>来店</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: C.white, marginTop: 4 }}>
                {selected.visitCount}次
              </div>
            </div>
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

          <div style={{ fontSize: 16, color: C.muted, marginBottom: 16 }}>
            上次来店: {selected.lastVisit}
          </div>

          {/* 关联订单 */}
          <button
            onClick={handleBind}
            disabled={bound}
            style={{
              width: '100%', minHeight: 56, borderRadius: 12,
              background: bound ? C.green : C.accent,
              color: C.white, border: 'none',
              fontSize: 18, fontWeight: 700, cursor: bound ? 'default' : 'pointer',
            }}
          >
            {bound ? '已关联当前订单' : '关联当前订单'}
          </button>
        </div>
      )}
    </div>
  );
}
