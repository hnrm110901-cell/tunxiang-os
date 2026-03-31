/**
 * SegmentCenterPage — 人群分群中心
 * 11个系统分群 + 用户列表 + 分群规则 + 趋势分析
 */
import { useState, useMemo } from 'react';

// ---- 颜色常量 ----
const BG_1 = '#112228';
const BG_2 = '#1a2a33';
const BRAND = '#FF6B2C';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const PURPLE = '#722ed1';
const CYAN = '#13c2c2';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

// ---- 类型定义 ----

interface Segment {
  id: string;
  name: string;
  icon: string;
  count: number;
  percentage: number;
  change: number; // 较上期变化百分比
  revenue: number; // 贡献营收
  color: string;
  rules: SegmentRule[];
  description: string;
}

interface SegmentRule {
  field: string;
  operator: string;
  value: string;
}

interface SegmentUser {
  id: string;
  name: string;
  phone: string;
  tags: string[];
  totalSpend: number;
  orderCount: number;
  lastVisit: string;
  repeatProbability: number;
  segment: string;
}

interface TrendDataPoint {
  date: string;
  count: number;
}

// ---- Mock 数据 ----

const MOCK_SEGMENTS: Segment[] = [
  {
    id: 'all', name: '全部人群', icon: '\uD83D\uDC65', count: 48672, percentage: 100, change: 3.2,
    revenue: 12860000, color: TEXT_2,
    rules: [],
    description: '所有注册会员用户',
  },
  {
    id: 'new', name: '新客', icon: '\uD83C\uDF1F', count: 2847, percentage: 5.8, change: 12.3,
    revenue: 568000, color: GREEN,
    rules: [
      { field: '注册时间', operator: '在最近', value: '30天内' },
      { field: '消费次数', operator: '等于', value: '1次' },
    ],
    description: '近30天首次消费的用户',
  },
  {
    id: 'first-no-repeat', name: '首单未复购', icon: '\uD83D\uDCA4', count: 4231, percentage: 8.7, change: -2.1,
    revenue: 423100, color: YELLOW,
    rules: [
      { field: '消费次数', operator: '等于', value: '1次' },
      { field: '首单时间', operator: '超过', value: '7天' },
    ],
    description: '仅消费1次且首单超过7天的用户',
  },
  {
    id: 'sleeping', name: '沉睡客', icon: '\uD83D\uDE34', count: 8945, percentage: 18.4, change: 1.8,
    revenue: 0, color: RED,
    rules: [
      { field: '最后消费', operator: '超过', value: '60天' },
      { field: '历史消费次数', operator: '大于等于', value: '2次' },
    ],
    description: '超过60天未到店的老用户',
  },
  {
    id: 'high-freq', name: '高频复购', icon: '\uD83D\uDD25', count: 3456, percentage: 7.1, change: 5.6,
    revenue: 4320000, color: BRAND,
    rules: [
      { field: '月均消费次数', operator: '大于等于', value: '4次' },
      { field: '最后消费', operator: '在最近', value: '30天内' },
    ],
    description: '月均消费4次以上的活跃用户',
  },
  {
    id: 'high-value', name: '高价值', icon: '\uD83D\uDC8E', count: 1823, percentage: 3.7, change: 2.3,
    revenue: 5469000, color: PURPLE,
    rules: [
      { field: '累计消费金额', operator: '大于等于', value: '\u00A55,000' },
      { field: '月均消费次数', operator: '大于等于', value: '2次' },
    ],
    description: '累计消费超过5000元的核心用户',
  },
  {
    id: 'at-risk', name: '流失风险', icon: '\u26A0\uFE0F', count: 2134, percentage: 4.4, change: 8.7,
    revenue: 213400, color: RED,
    rules: [
      { field: '消费频率趋势', operator: '为', value: '持续下降' },
      { field: '最后消费', operator: '在', value: '30-60天' },
    ],
    description: '消费频率持续下降的用户',
  },
  {
    id: 'social-active', name: '社交活跃', icon: '\uD83D\uDCE3', count: 1567, percentage: 3.2, change: 4.1,
    revenue: 1880400, color: CYAN,
    rules: [
      { field: '分享次数', operator: '大于等于', value: '3次/月' },
      { field: '邀请好友数', operator: '大于等于', value: '1人' },
    ],
    description: '频繁分享和邀请好友的用户',
  },
  {
    id: 'coupon-sensitive', name: '券敏感型', icon: '\uD83C\uDF9F\uFE0F', count: 5678, percentage: 11.7, change: -0.8,
    revenue: 2840000, color: YELLOW,
    rules: [
      { field: '券使用率', operator: '大于等于', value: '80%' },
      { field: '无券消费占比', operator: '小于', value: '30%' },
    ],
    description: '高度依赖优惠券消费的用户',
  },
  {
    id: 'weekend', name: '周末客群', icon: '\uD83C\uDF1E', count: 6234, percentage: 12.8, change: 1.2,
    revenue: 3740400, color: BLUE,
    rules: [
      { field: '周末消费占比', operator: '大于等于', value: '70%' },
      { field: '消费次数', operator: '大于等于', value: '2次' },
    ],
    description: '主要在周末到店消费的用户',
  },
  {
    id: 'family', name: '家庭客群', icon: '\uD83D\uDC68\u200D\uD83D\uDC69\u200D\uD83D\uDC67\u200D\uD83D\uDC66', count: 3890, percentage: 8.0, change: 3.5,
    revenue: 4668000, color: GREEN,
    rules: [
      { field: '平均用餐人数', operator: '大于等于', value: '3人' },
      { field: '儿童餐点单率', operator: '大于', value: '0' },
    ],
    description: '多人聚餐且含儿童菜品的用户',
  },
];

const generateMockUsers = (segmentId: string): SegmentUser[] => {
  const lastNames = ['张', '李', '王', '刘', '陈', '杨', '赵', '黄', '周', '吴', '徐', '孙', '马', '朱', '胡'];
  const firstNames = ['伟', '芳', '娜', '敏', '强', '磊', '洋', '艳', '勇', '军', '杰', '娟', '涛', '明', '超'];
  const tagPool = ['高频', '忠诚', '价格敏感', '社交达人', '周末', '午餐', '晚餐', '外卖', '堂食', '团购', '新客', '老客', 'VIP'];

  return Array.from({ length: 20 }, (_, i) => {
    const lastName = lastNames[Math.floor(Math.random() * lastNames.length)];
    const firstName = firstNames[Math.floor(Math.random() * firstNames.length)];
    const tagCount = 2 + Math.floor(Math.random() * 3);
    const shuffledTags = [...tagPool].sort(() => Math.random() - 0.5);
    return {
      id: `user-${segmentId}-${i}`,
      name: `${lastName}${firstName}`,
      phone: `1${['38', '39', '56', '58', '87', '88'][Math.floor(Math.random() * 6)]}****${String(1000 + Math.floor(Math.random() * 9000)).slice(0, 4)}`,
      tags: shuffledTags.slice(0, tagCount),
      totalSpend: Math.round(500 + Math.random() * 15000),
      orderCount: Math.round(1 + Math.random() * 50),
      lastVisit: `2026-03-${String(10 + Math.floor(Math.random() * 16)).padStart(2, '0')}`,
      repeatProbability: Math.round(Math.random() * 100),
      segment: segmentId,
    };
  });
};

const generateTrendData = (): TrendDataPoint[] => {
  const base = 2000 + Math.floor(Math.random() * 3000);
  return Array.from({ length: 14 }, (_, i) => ({
    date: `03-${String(13 + i).padStart(2, '0')}`,
    count: base + Math.floor(Math.random() * 500) - 250,
  }));
};

// ---- 组件 ----

function SegmentSidebar({ segments, activeId, onSelect }: {
  segments: Segment[];
  activeId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <div style={{
      width: 220, minWidth: 220, background: BG_1, borderRadius: 10,
      border: `1px solid ${BG_2}`, padding: '8px 0', overflowY: 'auto',
      maxHeight: 'calc(100vh - 200px)',
    }}>
      <div style={{ padding: '8px 16px 12px', fontSize: 13, fontWeight: 700, color: TEXT_3 }}>系统分群</div>
      {segments.map(seg => (
        <div
          key={seg.id}
          onClick={() => onSelect(seg.id)}
          style={{
            display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px',
            cursor: 'pointer', transition: 'background .15s',
            background: activeId === seg.id ? BRAND + '15' : 'transparent',
            borderLeft: activeId === seg.id ? `3px solid ${BRAND}` : '3px solid transparent',
          }}
        >
          <span style={{ fontSize: 16 }}>{seg.icon}</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 500, color: activeId === seg.id ? TEXT_1 : TEXT_2 }}>{seg.name}</div>
            <div style={{ fontSize: 11, color: TEXT_4 }}>{seg.count.toLocaleString()}人</div>
          </div>
          <span style={{
            fontSize: 10, color: seg.change >= 0 ? GREEN : RED,
          }}>{seg.change >= 0 ? '+' : ''}{seg.change}%</span>
        </div>
      ))}
    </div>
  );
}

function SegmentOverviewCard({ segment }: { segment: Segment }) {
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 20,
      border: `1px solid ${BG_2}`, marginBottom: 16,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <span style={{ fontSize: 28 }}>{segment.icon}</span>
        <div>
          <div style={{ fontSize: 18, fontWeight: 700 }}>{segment.name}</div>
          <div style={{ fontSize: 12, color: TEXT_3, marginTop: 2 }}>{segment.description}</div>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
        <div>
          <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 4 }}>人数</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: TEXT_1 }}>{segment.count.toLocaleString()}</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 4 }}>占比</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: TEXT_1 }}>{segment.percentage}%</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 4 }}>较上期变化</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: segment.change >= 0 ? GREEN : RED }}>
            {segment.change >= 0 ? '+' : ''}{segment.change}%
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 4 }}>贡献营收</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: TEXT_1 }}>
            \u00A5{(segment.revenue / 10000).toFixed(1)}万
          </div>
        </div>
      </div>
    </div>
  );
}

function UserTable({ users }: { users: SegmentUser[] }) {
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 16,
      border: `1px solid ${BG_2}`, marginBottom: 16,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ fontSize: 15, fontWeight: 700 }}>用户列表</div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button style={{
            padding: '4px 12px', borderRadius: 6, border: `1px solid ${BG_2}`,
            background: BG_2, color: TEXT_2, fontSize: 11, cursor: 'pointer',
          }}>导出</button>
          <button style={{
            padding: '4px 12px', borderRadius: 6, border: 'none',
            background: BRAND + '22', color: BRAND, fontSize: 11, cursor: 'pointer', fontWeight: 600,
          }}>创建旅程</button>
        </div>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${BG_2}` }}>
              {['用户', '手机号', '标签', '累计消费', '消费次数', '最后到店', '复购概率'].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '8px 10px', color: TEXT_4, fontWeight: 600, fontSize: 11, whiteSpace: 'nowrap' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {users.map(u => (
              <tr key={u.id} style={{ borderBottom: `1px solid ${BG_2}` }}>
                <td style={{ padding: '10px', color: TEXT_1, fontWeight: 500 }}>{u.name}</td>
                <td style={{ padding: '10px', color: TEXT_3, fontFamily: 'monospace', fontSize: 12 }}>{u.phone}</td>
                <td style={{ padding: '10px' }}>
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {u.tags.map(t => (
                      <span key={t} style={{
                        fontSize: 10, padding: '1px 6px', borderRadius: 4,
                        background: BLUE + '22', color: BLUE,
                      }}>{t}</span>
                    ))}
                  </div>
                </td>
                <td style={{ padding: '10px', color: TEXT_2 }}>\u00A5{u.totalSpend.toLocaleString()}</td>
                <td style={{ padding: '10px', color: TEXT_2 }}>{u.orderCount}</td>
                <td style={{ padding: '10px', color: TEXT_3 }}>{u.lastVisit}</td>
                <td style={{ padding: '10px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <div style={{ width: 50, height: 4, borderRadius: 2, background: BG_2 }}>
                      <div style={{
                        width: `${u.repeatProbability}%`, height: '100%', borderRadius: 2,
                        background: u.repeatProbability >= 60 ? GREEN : u.repeatProbability >= 30 ? YELLOW : RED,
                      }} />
                    </div>
                    <span style={{
                      fontSize: 11,
                      color: u.repeatProbability >= 60 ? GREEN : u.repeatProbability >= 30 ? YELLOW : RED,
                    }}>{u.repeatProbability}%</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SegmentRules({ rules }: { rules: SegmentRule[] }) {
  if (rules.length === 0) return null;
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 16,
      border: `1px solid ${BG_2}`, marginBottom: 16, flex: 1,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>分群规则</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {rules.map((rule, i) => (
          <div key={i} style={{
            display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
            background: BG_2, borderRadius: 8,
          }}>
            {i > 0 && <span style={{ fontSize: 11, fontWeight: 700, color: BRAND, marginRight: 4 }}>AND</span>}
            <span style={{
              fontSize: 12, padding: '2px 8px', borderRadius: 4,
              background: BLUE + '22', color: BLUE, fontWeight: 500,
            }}>{rule.field}</span>
            <span style={{ fontSize: 12, color: TEXT_3 }}>{rule.operator}</span>
            <span style={{ fontSize: 12, color: TEXT_1, fontWeight: 600 }}>{rule.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function TrendMiniChart({ data }: { data: TrendDataPoint[] }) {
  const maxCount = Math.max(...data.map(d => d.count));
  const minCount = Math.min(...data.map(d => d.count));
  const range = maxCount - minCount || 1;
  const chartH = 100;
  const chartW = data.length * 30;

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 16,
      border: `1px solid ${BG_2}`, marginBottom: 16, flex: 1,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 12 }}>趋势分析（近14天）</div>
      <svg width="100%" height={chartH + 20} viewBox={`0 0 ${chartW} ${chartH + 20}`} style={{ overflow: 'visible' }}>
        <defs>
          <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={BRAND} stopOpacity="0.3" />
            <stop offset="100%" stopColor={BRAND} stopOpacity="0.02" />
          </linearGradient>
        </defs>
        {/* 面积 */}
        <polygon
          points={[
            ...data.map((d, i) => `${i * 30 + 15},${chartH - ((d.count - minCount) / range) * (chartH - 10) - 5}`),
            `${(data.length - 1) * 30 + 15},${chartH}`,
            `15,${chartH}`,
          ].join(' ')}
          fill="url(#trendFill)"
        />
        {/* 线 */}
        <polyline
          fill="none" stroke={BRAND} strokeWidth={2}
          points={data.map((d, i) => `${i * 30 + 15},${chartH - ((d.count - minCount) / range) * (chartH - 10) - 5}`).join(' ')}
        />
        {data.map((d, i) => (
          <circle key={i} cx={i * 30 + 15} cy={chartH - ((d.count - minCount) / range) * (chartH - 10) - 5}
            r={2.5} fill={BRAND} />
        ))}
        {data.filter((_, i) => i % 3 === 0).map((d, _i, _arr) => {
          const origIdx = data.indexOf(d);
          return (
            <text key={origIdx} x={origIdx * 30 + 15} y={chartH + 14} textAnchor="middle" fill={TEXT_4} fontSize={9}>
              {d.date}
            </text>
          );
        })}
      </svg>
    </div>
  );
}

// ---- 主页面 ----

export function SegmentCenterPage() {
  const [activeSegmentId, setActiveSegmentId] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');

  const activeSegment = useMemo(
    () => MOCK_SEGMENTS.find(s => s.id === activeSegmentId) || MOCK_SEGMENTS[0],
    [activeSegmentId],
  );

  const users = useMemo(() => generateMockUsers(activeSegmentId), [activeSegmentId]);
  const trendData = useMemo(() => generateTrendData(), [activeSegmentId]);

  const filteredUsers = useMemo(() => {
    if (!searchQuery) return users;
    return users.filter(u =>
      u.name.includes(searchQuery) || u.phone.includes(searchQuery) || u.tags.some(t => t.includes(searchQuery))
    );
  }, [users, searchQuery]);

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      {/* 顶部 */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 16, flexWrap: 'wrap', gap: 12,
      }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>人群分群中心</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <select style={{
            background: BG_1, border: `1px solid ${BG_2}`, borderRadius: 6,
            color: TEXT_2, padding: '6px 12px', fontSize: 13, outline: 'none',
          }}>
            <option>近30天</option>
            <option>近7天</option>
            <option>近90天</option>
          </select>
          <select style={{
            background: BG_1, border: `1px solid ${BG_2}`, borderRadius: 6,
            color: TEXT_2, padding: '6px 12px', fontSize: 13, outline: 'none',
          }}>
            <option>全部门店</option>
            <option>芙蓉路店</option>
            <option>万达广场店</option>
            <option>梅溪湖店</option>
          </select>
          <input
            placeholder="搜索用户/标签..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            style={{
              background: BG_1, border: `1px solid ${BG_2}`, borderRadius: 6,
              color: TEXT_2, padding: '6px 12px', fontSize: 13, outline: 'none',
              width: 180,
            }}
          />
          <button style={{
            padding: '6px 16px', borderRadius: 6, border: 'none',
            background: BRAND, color: '#fff', fontSize: 13, fontWeight: 700,
            cursor: 'pointer',
          }}>+ 新建分群</button>
        </div>
      </div>

      {/* 主体: 左侧导航 + 右侧内容 */}
      <div style={{ display: 'flex', gap: 16 }}>
        <SegmentSidebar
          segments={MOCK_SEGMENTS}
          activeId={activeSegmentId}
          onSelect={setActiveSegmentId}
        />

        <div style={{ flex: 1, minWidth: 0 }}>
          {/* 人群概览卡 */}
          <SegmentOverviewCard segment={activeSegment} />

          {/* 用户列表 */}
          <UserTable users={filteredUsers} />

          {/* 分群规则 + 趋势分析 */}
          <div style={{ display: 'flex', gap: 16 }}>
            <SegmentRules rules={activeSegment.rules} />
            <TrendMiniChart data={trendData} />
          </div>
        </div>
      </div>
    </div>
  );
}
