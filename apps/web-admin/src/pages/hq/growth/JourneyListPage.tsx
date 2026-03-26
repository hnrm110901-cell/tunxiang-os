/**
 * JourneyListPage — 客户旅程列表
 * 展示所有旅程的状态、数据和管理操作
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

// ---- 颜色常量 ----
const BG_1 = '#112228';
const BG_2 = '#1a2a33';
const BRAND = '#FF6B2C';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const PURPLE = '#722ed1';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

// ---- 类型定义 ----

type JourneyStatus = '草稿' | '运行中' | '已暂停' | '已结束';

interface Journey {
  id: string;
  name: string;
  description: string;
  status: JourneyStatus;
  targetSegment: string;
  targetCount: number;
  executedCount: number;
  conversionRate: number;
  nodeCount: number;
  createdAt: string;
  updatedAt: string;
  creator: string;
}

// ---- Mock 数据 ----

const MOCK_JOURNEYS: Journey[] = [
  {
    id: 'j1', name: '新客首单转复购旅程', description: '针对首单客户，通过多触点引导完成第二次消费',
    status: '运行中', targetSegment: '首单未复购', targetCount: 4231, executedCount: 3876,
    conversionRate: 18.4, nodeCount: 7, createdAt: '2026-03-10', updatedAt: '2026-03-25', creator: '运营小王',
  },
  {
    id: 'j2', name: '沉睡客唤醒旅程', description: '60天未到店客户的分阶段唤醒策略',
    status: '运行中', targetSegment: '沉睡客', targetCount: 8945, executedCount: 6234,
    conversionRate: 12.7, nodeCount: 9, createdAt: '2026-03-05', updatedAt: '2026-03-24', creator: '运营小李',
  },
  {
    id: 'j3', name: '高价值客户维护旅程', description: 'VIP客户的专属权益和关怀触达',
    status: '运行中', targetSegment: '高价值', targetCount: 1823, executedCount: 1823,
    conversionRate: 45.2, nodeCount: 5, createdAt: '2026-02-20', updatedAt: '2026-03-26', creator: '运营小王',
  },
  {
    id: 'j4', name: '老带新裂变旅程', description: '社交活跃用户的裂变分享激励',
    status: '已暂停', targetSegment: '社交活跃', targetCount: 1567, executedCount: 980,
    conversionRate: 8.9, nodeCount: 6, createdAt: '2026-03-01', updatedAt: '2026-03-20', creator: '运营小张',
  },
  {
    id: 'j5', name: '流失预警挽回旅程', description: '消费频率下降客户的精准挽回',
    status: '草稿', targetSegment: '流失风险', targetCount: 2134, executedCount: 0,
    conversionRate: 0, nodeCount: 8, createdAt: '2026-03-24', updatedAt: '2026-03-26', creator: '运营小李',
  },
  {
    id: 'j6', name: '周末特惠推送旅程', description: '周末客群的定向优惠触达',
    status: '已结束', targetSegment: '周末客群', targetCount: 6234, executedCount: 5870,
    conversionRate: 22.3, nodeCount: 4, createdAt: '2026-02-15', updatedAt: '2026-03-15', creator: '运营小王',
  },
  {
    id: 'j7', name: '家庭套餐推广旅程', description: '家庭客群的套餐优惠和亲子活动推送',
    status: '草稿', targetSegment: '家庭客群', targetCount: 3890, executedCount: 0,
    conversionRate: 0, nodeCount: 5, createdAt: '2026-03-25', updatedAt: '2026-03-26', creator: '运营小张',
  },
];

// ---- 主页面 ----

export function JourneyListPage() {
  const navigate = useNavigate();
  const [filterStatus, setFilterStatus] = useState<JourneyStatus | '全部'>('全部');
  const [searchQuery, setSearchQuery] = useState('');

  const filteredJourneys = MOCK_JOURNEYS.filter(j => {
    if (filterStatus !== '全部' && j.status !== filterStatus) return false;
    if (searchQuery && !j.name.includes(searchQuery) && !j.description.includes(searchQuery)) return false;
    return true;
  });

  const statusColors: Record<JourneyStatus, string> = {
    '草稿': TEXT_4,
    '运行中': GREEN,
    '已暂停': YELLOW,
    '已结束': BLUE,
  };

  const statusCounts = {
    '全部': MOCK_JOURNEYS.length,
    '运行中': MOCK_JOURNEYS.filter(j => j.status === '运行中').length,
    '草稿': MOCK_JOURNEYS.filter(j => j.status === '草稿').length,
    '已暂停': MOCK_JOURNEYS.filter(j => j.status === '已暂停').length,
    '已结束': MOCK_JOURNEYS.filter(j => j.status === '已结束').length,
  };

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      {/* 顶部 */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 16, flexWrap: 'wrap', gap: 12,
      }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>客户旅程</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <input
            placeholder="搜索旅程..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            style={{
              background: BG_1, border: `1px solid ${BG_2}`, borderRadius: 6,
              color: TEXT_2, padding: '6px 12px', fontSize: 13, outline: 'none', width: 200,
            }}
          />
          <button
            onClick={() => navigate('/hq/growth/journeys/new/canvas')}
            style={{
              padding: '8px 18px', borderRadius: 8, border: 'none', cursor: 'pointer',
              background: BRAND, color: '#fff', fontSize: 13, fontWeight: 700,
            }}
          >+ 新建旅程</button>
        </div>
      </div>

      {/* 状态筛选 Tabs */}
      <div style={{
        display: 'flex', gap: 4, marginBottom: 16, padding: '4px',
        background: BG_1, borderRadius: 8, border: `1px solid ${BG_2}`,
        width: 'fit-content',
      }}>
        {(['全部', '运行中', '草稿', '已暂停', '已结束'] as const).map(st => (
          <button
            key={st}
            onClick={() => setFilterStatus(st)}
            style={{
              padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
              background: filterStatus === st ? BG_2 : 'transparent',
              color: filterStatus === st ? TEXT_1 : TEXT_4,
              fontSize: 12, fontWeight: 600, transition: 'all .15s',
            }}
          >
            {st} <span style={{ fontSize: 10, opacity: 0.7 }}>({statusCounts[st]})</span>
          </button>
        ))}
      </div>

      {/* 统计卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
        <div style={{ background: BG_1, borderRadius: 10, padding: '14px 18px', border: `1px solid ${BG_2}` }}>
          <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 4 }}>运行中旅程</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: GREEN }}>{statusCounts['运行中']}</div>
        </div>
        <div style={{ background: BG_1, borderRadius: 10, padding: '14px 18px', border: `1px solid ${BG_2}` }}>
          <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 4 }}>总触达人次</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: TEXT_1 }}>
            {MOCK_JOURNEYS.reduce((s, j) => s + j.executedCount, 0).toLocaleString()}
          </div>
        </div>
        <div style={{ background: BG_1, borderRadius: 10, padding: '14px 18px', border: `1px solid ${BG_2}` }}>
          <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 4 }}>平均转化率</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: BRAND }}>
            {(MOCK_JOURNEYS.filter(j => j.conversionRate > 0).reduce((s, j) => s + j.conversionRate, 0) /
              MOCK_JOURNEYS.filter(j => j.conversionRate > 0).length).toFixed(1)}%
          </div>
        </div>
        <div style={{ background: BG_1, borderRadius: 10, padding: '14px 18px', border: `1px solid ${BG_2}` }}>
          <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 4 }}>待发布草稿</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: YELLOW }}>{statusCounts['草稿']}</div>
        </div>
      </div>

      {/* 旅程列表 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {filteredJourneys.map(j => (
          <div
            key={j.id}
            style={{
              background: BG_1, borderRadius: 10, padding: '18px 20px',
              border: `1px solid ${BG_2}`, cursor: 'pointer',
              transition: 'border-color .15s',
            }}
            onClick={() => navigate(`/hq/growth/journeys/${j.id}/canvas`)}
          >
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 10 }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
                  <span style={{ fontSize: 16, fontWeight: 700, color: TEXT_1 }}>{j.name}</span>
                  <span style={{
                    fontSize: 10, padding: '2px 8px', borderRadius: 10,
                    background: statusColors[j.status] + '22',
                    color: statusColors[j.status], fontWeight: 600,
                  }}>{j.status}</span>
                </div>
                <div style={{ fontSize: 12, color: TEXT_3 }}>{j.description}</div>
              </div>
              <button
                onClick={e => { e.stopPropagation(); navigate(`/hq/growth/journeys/${j.id}/canvas`); }}
                style={{
                  padding: '6px 14px', borderRadius: 6, border: `1px solid ${BG_2}`,
                  background: BG_2, color: TEXT_2, fontSize: 12, cursor: 'pointer',
                }}
              >编辑画布</button>
            </div>
            <div style={{
              display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 12,
              fontSize: 12,
            }}>
              <div>
                <span style={{ color: TEXT_4 }}>目标人群: </span>
                <span style={{ color: BRAND, fontWeight: 500 }}>{j.targetSegment}</span>
              </div>
              <div>
                <span style={{ color: TEXT_4 }}>目标人数: </span>
                <span style={{ color: TEXT_2 }}>{j.targetCount.toLocaleString()}</span>
              </div>
              <div>
                <span style={{ color: TEXT_4 }}>已执行: </span>
                <span style={{ color: TEXT_2 }}>{j.executedCount.toLocaleString()}</span>
              </div>
              <div>
                <span style={{ color: TEXT_4 }}>转化率: </span>
                <span style={{ color: j.conversionRate >= 15 ? GREEN : j.conversionRate > 0 ? YELLOW : TEXT_4, fontWeight: 600 }}>
                  {j.conversionRate > 0 ? `${j.conversionRate}%` : '-'}
                </span>
              </div>
              <div>
                <span style={{ color: TEXT_4 }}>节点数: </span>
                <span style={{ color: TEXT_2 }}>{j.nodeCount}</span>
              </div>
              <div>
                <span style={{ color: TEXT_4 }}>更新: </span>
                <span style={{ color: TEXT_3 }}>{j.updatedAt}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
