/**
 * NewProductListPage -- 新品机会列表
 * 路由: /hq/market-intel/new-products
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

// ---- 颜色常量 ----
const BG_1 = '#1a2836';
const BG_2 = '#243442';
const BRAND = '#ff6b2c';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const TEXT_1 = '#ffffff';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

// ---- 类型定义 ----
type OpportunityStatus = '待评估' | '评估中' | '试点中' | '已采纳' | '已否决';

interface OpportunitySummary {
  id: string;
  name: string;
  score: number;
  status: OpportunityStatus;
  category: string;
  source: string;
  heatScore: number;
  brandFit: number;
  costFeasibility: number;
  date: string;
  tags: string[];
}

// ---- Mock 数据 ----
const MOCK_OPPORTUNITIES: OpportunitySummary[] = [
  { id: 'opp-1', name: '酸汤火锅', score: 87, status: '待评估', category: '汤锅', source: '市场趋势+竞对', heatScore: 95, brandFit: 78, costFeasibility: 75, date: '2026-03-26', tags: ['高热度', '竞对在做'] },
  { id: 'opp-2', name: '一人食精品套餐', score: 82, status: '评估中', category: '套餐', source: '需求趋势', heatScore: 88, brandFit: 85, costFeasibility: 82, date: '2026-03-25', tags: ['需求增长', '低成本'] },
  { id: 'opp-3', name: '低脂健康套餐', score: 79, status: '待评估', category: '健康餐', source: '社媒趋势', heatScore: 85, brandFit: 72, costFeasibility: 80, date: '2026-03-24', tags: ['健康趋势'] },
  { id: 'opp-4', name: '酸笋系列配菜', score: 75, status: '试点中', category: '配菜', source: '原料发现', heatScore: 70, brandFit: 80, costFeasibility: 78, date: '2026-03-23', tags: ['新原料', '试点中'] },
  { id: 'opp-5', name: '春季时令菜品', score: 73, status: '已采纳', category: '时令', source: '节气策略', heatScore: 65, brandFit: 82, costFeasibility: 85, date: '2026-03-22', tags: ['节气限定'] },
  { id: 'opp-6', name: '外卖专属套餐', score: 80, status: '评估中', category: '套餐', source: '竞对分析', heatScore: 82, brandFit: 78, costFeasibility: 88, date: '2026-03-21', tags: ['防御策略', '外卖'] },
  { id: 'opp-7', name: '儿童友好餐', score: 68, status: '待评估', category: '亲子', source: '需求洞察', heatScore: 55, brandFit: 75, costFeasibility: 72, date: '2026-03-20', tags: ['家庭客群'] },
  { id: 'opp-8', name: '下午茶甜品', score: 58, status: '已否决', category: '甜品', source: '社媒趋势', heatScore: 48, brandFit: 45, costFeasibility: 68, date: '2026-03-19', tags: ['品牌偏离'] },
  { id: 'opp-9', name: '预制菜到家系列', score: 72, status: '评估中', category: '预制菜', source: '渠道拓展', heatScore: 75, brandFit: 65, costFeasibility: 70, date: '2026-03-18', tags: ['新渠道', '风险'] },
  { id: 'opp-10', name: '辣度分级体系', score: 77, status: '已采纳', category: '产品优化', source: '顾客反馈', heatScore: 68, brandFit: 90, costFeasibility: 92, date: '2026-03-17', tags: ['体验优化', '低成本'] },
];

// ---- 组件 ----

function ScoreCircle({ score }: { score: number }) {
  const color = score >= 80 ? GREEN : score >= 65 ? YELLOW : RED;
  return (
    <div style={{
      width: 44, height: 44, borderRadius: '50%',
      border: `3px solid ${color}`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 16, fontWeight: 700, color,
      flexShrink: 0,
    }}>
      {score}
    </div>
  );
}

function MiniBar({ value, max, color }: { value: number; max: number; color: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4, minWidth: 80 }}>
      <div style={{ flex: 1, height: 4, borderRadius: 2, background: BG_2 }}>
        <div style={{ width: `${(value / max) * 100}%`, height: '100%', borderRadius: 2, background: color }} />
      </div>
      <span style={{ fontSize: 10, color: TEXT_4, minWidth: 20 }}>{value}</span>
    </div>
  );
}

export function NewProductListPage() {
  const navigate = useNavigate();
  const [statusFilter, setStatusFilter] = useState<string>('全部');
  const [sortBy, setSortBy] = useState<'score' | 'date' | 'heat'>('score');

  const statuses = ['全部', '待评估', '评估中', '试点中', '已采纳', '已否决'];
  const statusColors: Record<string, string> = {
    '待评估': YELLOW, '评估中': BLUE, '试点中': BRAND, '已采纳': GREEN, '已否决': TEXT_4,
  };

  const filtered = MOCK_OPPORTUNITIES
    .filter(o => statusFilter === '全部' || o.status === statusFilter)
    .sort((a, b) => {
      if (sortBy === 'score') return b.score - a.score;
      if (sortBy === 'heat') return b.heatScore - a.heatScore;
      return b.date.localeCompare(a.date);
    });

  const statusCounts = statuses.reduce((acc, s) => {
    acc[s] = s === '全部' ? MOCK_OPPORTUNITIES.length : MOCK_OPPORTUNITIES.filter(o => o.status === s).length;
    return acc;
  }, {} as Record<string, number>);

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>新品机会列表</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: TEXT_3 }}>排序:</span>
          {(['score', 'date', 'heat'] as const).map(s => {
            const labels: Record<string, string> = { score: '综合评分', date: '发现时间', heat: '市场热度' };
            return (
              <button key={s} onClick={() => setSortBy(s)} style={{
                padding: '4px 10px', borderRadius: 6, border: 'none', cursor: 'pointer',
                background: sortBy === s ? BRAND : BG_2,
                color: sortBy === s ? '#fff' : TEXT_3,
                fontSize: 11, fontWeight: 600,
              }}>{labels[s]}</button>
            );
          })}
        </div>
      </div>

      {/* 状态筛选 */}
      <div style={{
        display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap',
      }}>
        {statuses.map(s => (
          <button key={s} onClick={() => setStatusFilter(s)} style={{
            padding: '6px 14px', borderRadius: 8, cursor: 'pointer',
            background: statusFilter === s ? (statusColors[s] || BRAND) + '22' : BG_1,
            color: statusFilter === s ? (statusColors[s] || BRAND) : TEXT_3,
            fontSize: 12, fontWeight: 600,
            border: `1px solid ${statusFilter === s ? (statusColors[s] || BRAND) + '44' : BG_2}`,
          }}>
            {s} ({statusCounts[s]})
          </button>
        ))}
      </div>

      {/* 列表 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {filtered.map(opp => (
          <div
            key={opp.id}
            onClick={() => navigate(`/hq/market-intel/new-products/${opp.id}`)}
            style={{
              display: 'flex', alignItems: 'center', gap: 14, padding: '14px 18px',
              background: BG_1, borderRadius: 10, cursor: 'pointer',
              border: `1px solid ${BG_2}`, transition: 'border-color .15s',
            }}
          >
            <ScoreCircle score={opp.score} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                <span style={{ fontSize: 15, fontWeight: 700, color: TEXT_1 }}>{opp.name}</span>
                <span style={{
                  fontSize: 10, padding: '1px 6px', borderRadius: 4,
                  background: (statusColors[opp.status] || TEXT_4) + '22',
                  color: statusColors[opp.status] || TEXT_4, fontWeight: 600,
                }}>{opp.status}</span>
                <span style={{ fontSize: 11, color: TEXT_4 }}>{opp.category}</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                <div>
                  <span style={{ fontSize: 10, color: TEXT_4, marginRight: 4 }}>热度</span>
                  <MiniBar value={opp.heatScore} max={100} color={BRAND} />
                </div>
                <div>
                  <span style={{ fontSize: 10, color: TEXT_4, marginRight: 4 }}>适配</span>
                  <MiniBar value={opp.brandFit} max={100} color={BLUE} />
                </div>
                <div>
                  <span style={{ fontSize: 10, color: TEXT_4, marginRight: 4 }}>成本</span>
                  <MiniBar value={opp.costFeasibility} max={100} color={GREEN} />
                </div>
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4, flexShrink: 0 }}>
              <span style={{ fontSize: 11, color: TEXT_4 }}>{opp.date}</span>
              <div style={{ display: 'flex', gap: 4 }}>
                {opp.tags.map((tag, i) => (
                  <span key={i} style={{
                    fontSize: 10, padding: '1px 5px', borderRadius: 3,
                    background: BG_2, color: TEXT_3,
                  }}>{tag}</span>
                ))}
              </div>
              <span style={{ fontSize: 11, color: TEXT_4 }}>来源: {opp.source}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
