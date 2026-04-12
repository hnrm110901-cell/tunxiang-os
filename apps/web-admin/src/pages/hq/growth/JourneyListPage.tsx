/**
 * JourneyListPage — 客户旅程列表
 * 展示所有旅程的状态、数据和管理操作
 * API: GET /api/v1/growth/journeys
 *      PATCH /api/v1/growth/journeys/{id}  { status }
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { txFetchData } from '../../../api';

// ---- 颜色常量 ----
const BG_1 = '#112228';
const BG_2 = '#1a2a33';
const BRAND = '#FF6B2C';
const GREEN = '#52c41a';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
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

// ---- API ----

async function apiFetchJourneys(): Promise<Journey[]> {
  try {
    const res = await txFetchData<{ items: Journey[] }>('/api/v1/growth/journeys');
    return res?.items ?? [];
  } catch {
    return [];
  }
}

async function apiPatchJourney(id: string, status: JourneyStatus): Promise<void> {
  await txFetchData(`/api/v1/growth/journeys/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  });
}

// ---- 主页面 ----

export function JourneyListPage() {
  const navigate = useNavigate();
  const [filterStatus, setFilterStatus] = useState<JourneyStatus | '全部'>('全部');
  const [searchQuery, setSearchQuery] = useState('');
  const [journeys, setJourneys] = useState<Journey[]>([]);
  const [loading, setLoading] = useState(false);

  const loadJourneys = useCallback(async () => {
    setLoading(true);
    const list = await apiFetchJourneys();
    setJourneys(list);
    setLoading(false);
  }, []);

  useEffect(() => { loadJourneys(); }, [loadJourneys]);

  const handleToggleStatus = useCallback(async (j: Journey, e: React.MouseEvent) => {
    e.stopPropagation();
    const newStatus: JourneyStatus = j.status === '运行中' ? '已暂停' : '运行中';
    // 乐观更新
    setJourneys((prev) => prev.map((item) => item.id === j.id ? { ...item, status: newStatus } : item));
    try {
      await apiPatchJourney(j.id, newStatus);
    } catch {
      // 回滚
      setJourneys((prev) => prev.map((item) => item.id === j.id ? { ...item, status: j.status } : item));
    }
  }, []);

  const filteredJourneys = journeys.filter(j => {
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
    '全部': journeys.length,
    '运行中': journeys.filter(j => j.status === '运行中').length,
    '草稿': journeys.filter(j => j.status === '草稿').length,
    '已暂停': journeys.filter(j => j.status === '已暂停').length,
    '已结束': journeys.filter(j => j.status === '已结束').length,
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
            {journeys.reduce((s, j) => s + j.executedCount, 0).toLocaleString()}
          </div>
        </div>
        <div style={{ background: BG_1, borderRadius: 10, padding: '14px 18px', border: `1px solid ${BG_2}` }}>
          <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 4 }}>平均转化率</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: BRAND }}>
            {(journeys.filter(j => j.conversionRate > 0).reduce((s, j) => s + j.conversionRate, 0) /
              journeys.filter(j => j.conversionRate > 0).length).toFixed(1)}%
          </div>
        </div>
        <div style={{ background: BG_1, borderRadius: 10, padding: '14px 18px', border: `1px solid ${BG_2}` }}>
          <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 4 }}>待发布草稿</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: YELLOW }}>{statusCounts['草稿']}</div>
        </div>
      </div>

      {/* 旅程列表 */}
      {loading && (
        <div style={{ textAlign: 'center', color: TEXT_4, padding: 24, fontSize: 13 }}>加载中...</div>
      )}
      {!loading && filteredJourneys.length === 0 && (
        <div style={{ textAlign: 'center', color: TEXT_4, padding: 40, fontSize: 13, background: BG_1, borderRadius: 10 }}>
          暂无旅程数据
        </div>
      )}
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
              <div style={{ display: 'flex', gap: 8 }}>
                {(j.status === '运行中' || j.status === '已暂停') && (
                  <button
                    onClick={e => handleToggleStatus(j, e)}
                    style={{
                      padding: '6px 14px', borderRadius: 6, border: `1px solid ${j.status === '运行中' ? YELLOW : GREEN}`,
                      background: 'transparent',
                      color: j.status === '运行中' ? YELLOW : GREEN,
                      fontSize: 12, cursor: 'pointer',
                    }}
                  >{j.status === '运行中' ? '暂停' : '激活'}</button>
                )}
                <button
                  onClick={e => { e.stopPropagation(); navigate(`/hq/growth/journeys/${j.id}/canvas`); }}
                  style={{
                    padding: '6px 14px', borderRadius: 6, border: `1px solid ${BG_2}`,
                    background: BG_2, color: TEXT_2, fontSize: 12, cursor: 'pointer',
                  }}
                >编辑画布</button>
              </div>
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
