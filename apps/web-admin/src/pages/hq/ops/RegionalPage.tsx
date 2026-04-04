/**
 * 区域追踪整改页 -- E8 总部端
 * 功能: 区域门店评分卡(红黄绿) + 整改任务列表(状态筛选) + 整改详情(时间线) + 跨店对标排行
 * 调用 GET /api/v1/ops/regional/*
 */
import { useState, useEffect } from 'react';
import { ChartPlaceholder } from '../../../components/ChartPlaceholder';
import { apiGet } from '../../../api/client';

// ---------- 类型 ----------
type ScoreLevel = 'green' | 'yellow' | 'red';
type TaskStatus = '全部' | '待处理' | '进行中' | '已完成' | '已超期';

interface StoreScoreCard {
  id: string;
  name: string;
  region: string;
  score: number;
  level: ScoreLevel;
  issues: number;
  lastInspect: string;
}

interface RectifyTask {
  id: string;
  store: string;
  title: string;
  status: '待处理' | '进行中' | '已完成' | '已超期';
  priority: 'high' | 'medium' | 'low';
  deadline: string;
  assignee: string;
}

interface TimelineItem {
  time: string;
  action: string;
  operator: string;
  detail: string;
}

interface RegionalKpi {
  stores: StoreScoreCard[];
  total: number;
  region_name: string;
}

interface InspectionRecord {
  task_id: string;
  store: string;
  title: string;
  status: '待处理' | '进行中' | '已完成' | '已超期';
  priority: 'high' | 'medium' | 'low';
  deadline: string;
  assignee: string;
  timeline: TimelineItem[];
}

// ---------- 评分配色 ----------
const LEVEL_CONFIG: Record<ScoreLevel, { label: string; color: string; bg: string }> = {
  green:  { label: '达标',   color: '#0F6E56', bg: '#0F6E5625' },
  yellow: { label: '预警',   color: '#BA7517', bg: '#BA751725' },
  red:    { label: '不达标', color: '#A32D2D', bg: '#A32D2D25' },
};

const STATUS_CONFIG: Record<string, { color: string; bg: string }> = {
  '待处理': { color: '#BA7517', bg: '#BA751720' },
  '进行中': { color: '#185FA5', bg: '#185FA520' },
  '已完成': { color: '#0F6E56', bg: '#0F6E5620' },
  '已超期': { color: '#A32D2D', bg: '#A32D2D20' },
};

const PRIORITY_LABEL: Record<string, { text: string; color: string }> = {
  high:   { text: '高', color: '#A32D2D' },
  medium: { text: '中', color: '#BA7517' },
  low:    { text: '低', color: '#185FA5' },
};

// ---------- 组件 ----------
export function RegionalPage() {
  // 当前区域 ID（实际项目从路由/全局状态读取）
  const regionId = 'changsha';

  const [stores, setStores] = useState<StoreScoreCard[]>([]);
  const [tasks, setTasks] = useState<RectifyTask[]>([]);
  const [regionName, setRegionName] = useState('');
  const [timeline, setTimeline] = useState<TimelineItem[]>([]);
  const [loading, setLoading] = useState(true);

  const [statusFilter, setStatusFilter] = useState<TaskStatus>('全部');
  const [selectedTask, setSelectedTask] = useState<string | null>(null);

  // 加载门店列表 + KPI + 巡店记录
  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    Promise.all([
      apiGet<RegionalKpi>(`/api/v1/ops/regional/kpi?region_id=${regionId}`).catch(() => null),
      apiGet<InspectionRecord[]>(`/api/v1/ops/regional/inspections?region_id=${regionId}`).catch(() => [] as InspectionRecord[]),
    ]).then(([kpiData, inspections]) => {
      if (cancelled) return;

      if (kpiData) {
        setStores(kpiData.stores ?? []);
        setRegionName(kpiData.region_name ?? '');
      }

      if (inspections && inspections.length > 0) {
        const rectifyTasks: RectifyTask[] = inspections.map((ins) => ({
          id: ins.task_id,
          store: ins.store,
          title: ins.title,
          status: ins.status,
          priority: ins.priority,
          deadline: ins.deadline,
          assignee: ins.assignee,
        }));
        setTasks(rectifyTasks);
        // 默认选中第一条
        if (selectedTask === null) {
          setSelectedTask(rectifyTasks[0]?.id ?? null);
          setTimeline(inspections[0]?.timeline ?? []);
        }
      }

      setLoading(false);
    });

    return () => { cancelled = true; };
  }, [regionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // 点击任务时加载对应时间线（从已加载数据中取）
  const handleSelectTask = async (taskId: string) => {
    setSelectedTask(taskId);
    try {
      const records = await apiGet<InspectionRecord[]>(
        `/api/v1/ops/regional/inspections?region_id=${regionId}`
      );
      const found = records.find((r) => r.task_id === taskId);
      setTimeline(found?.timeline ?? []);
    } catch {
      setTimeline([]);
    }
  };

  const filteredTasks = statusFilter === '全部'
    ? tasks
    : tasks.filter((t) => t.status === statusFilter);

  const statusCounts = {
    '全部': tasks.length,
    '待处理': tasks.filter((t) => t.status === '待处理').length,
    '进行中': tasks.filter((t) => t.status === '进行中').length,
    '已完成': tasks.filter((t) => t.status === '已完成').length,
    '已超期': tasks.filter((t) => t.status === '已超期').length,
  };

  // 跨店排行（按 score 排序）
  const rankStores = [...stores]
    .sort((a, b) => b.score - a.score)
    .map((s, i) => ({ ...s, rank: i + 1 }));

  return (
    <div>
      {/* 标题行 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>区域追踪整改</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: '#999' }}>
            {regionName || '加载中...'} | {stores.length} 家门店
          </span>
        </div>
      </div>

      {/* 区域门店评分卡网格 */}
      {loading ? (
        <div style={{ textAlign: 'center', color: '#666', padding: 40 }}>加载中...</div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 24 }}>
          {stores.map((store) => {
            const cfg = LEVEL_CONFIG[store.level];
            return (
              <div
                key={store.id}
                style={{
                  background: '#112228',
                  borderRadius: 8,
                  padding: 16,
                  borderLeft: `4px solid ${cfg.color}`,
                  cursor: 'pointer',
                  transition: 'transform 0.15s ease',
                }}
                onMouseEnter={(e) => { e.currentTarget.style.transform = 'translateY(-2px)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.transform = 'translateY(0)'; }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <span style={{ fontSize: 14, fontWeight: 600, color: '#fff' }}>{store.name}</span>
                  <span style={{
                    fontSize: 10, padding: '2px 8px', borderRadius: 4, fontWeight: 600,
                    background: cfg.bg, color: cfg.color,
                  }}>
                    {cfg.label}
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 4, marginBottom: 6 }}>
                  <span style={{ fontSize: 28, fontWeight: 'bold', color: cfg.color }}>{store.score}</span>
                  <span style={{ fontSize: 12, color: '#999' }}>分</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#999' }}>
                  <span>待整改 {store.issues} 项</span>
                  <span>巡检 {store.lastInspect.slice(5)}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        {/* 整改任务列表 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={{ margin: 0, fontSize: 16 }}>整改任务</h3>
          </div>

          {/* 状态筛选 */}
          <div style={{ display: 'flex', gap: 6, marginBottom: 16, flexWrap: 'wrap' }}>
            {(['全部', '待处理', '进行中', '已完成', '已超期'] as TaskStatus[]).map((s) => (
              <button
                key={s}
                onClick={() => setStatusFilter(s)}
                style={{
                  padding: '4px 12px', borderRadius: 6, border: 'none', cursor: 'pointer',
                  fontSize: 12, fontWeight: 600,
                  background: statusFilter === s ? '#FF6B2C' : '#0B1A20',
                  color: statusFilter === s ? '#fff' : '#999',
                }}
              >
                {s} ({statusCounts[s]})
              </button>
            ))}
          </div>

          {/* 任务列表 */}
          {filteredTasks.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#666', padding: 24 }}>暂无整改任务</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {filteredTasks.map((task) => {
                const sCfg = STATUS_CONFIG[task.status];
                const pCfg = PRIORITY_LABEL[task.priority];
                const isSelected = selectedTask === task.id;
                return (
                  <div
                    key={task.id}
                    onClick={() => handleSelectTask(task.id)}
                    style={{
                      padding: 12, borderRadius: 8, cursor: 'pointer',
                      background: isSelected ? '#1a2a33' : '#0B1A20',
                      border: isSelected ? '1px solid #FF6B2C40' : '1px solid transparent',
                      transition: 'all 0.15s ease',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{
                          fontSize: 10, padding: '2px 6px', borderRadius: 4, fontWeight: 600,
                          background: pCfg.color + '20', color: pCfg.color,
                        }}>
                          {pCfg.text}
                        </span>
                        <span style={{ fontSize: 13, fontWeight: 600, color: '#fff' }}>{task.title}</span>
                      </div>
                      <span style={{
                        fontSize: 10, padding: '2px 8px', borderRadius: 4, fontWeight: 600,
                        background: sCfg.bg, color: sCfg.color,
                      }}>
                        {task.status}
                      </span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#999' }}>
                      <span>{task.store} | {task.assignee}</span>
                      <span>截止 {task.deadline.slice(5)}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* 整改详情 - 时间线 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>整改详情 - 操作记录</h3>
          {selectedTask && timeline.length > 0 ? (
            <div style={{ position: 'relative', paddingLeft: 20 }}>
              {/* 时间轴线 */}
              <div style={{
                position: 'absolute', left: 6, top: 8, bottom: 8, width: 2,
                background: '#1a2a33',
              }} />
              {timeline.map((item, i) => (
                <div key={i} style={{ marginBottom: 20, position: 'relative' }}>
                  {/* 节点 */}
                  <div style={{
                    position: 'absolute', left: -17, top: 6,
                    width: 10, height: 10, borderRadius: '50%',
                    background: i === 0 ? '#FF6B2C' : '#1a2a33',
                    border: `2px solid ${i === 0 ? '#FF6B2C' : '#555'}`,
                  }} />
                  <div style={{ fontSize: 11, color: '#999', marginBottom: 4 }}>
                    {item.time} | {item.operator}
                  </div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#fff', marginBottom: 4 }}>
                    {item.action}
                  </div>
                  <div style={{
                    fontSize: 12, color: '#ccc', padding: 10, borderRadius: 6,
                    background: '#0B1A20',
                  }}>
                    {item.detail}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ textAlign: 'center', color: '#666', padding: 40 }}>
              <div style={{ fontSize: 32, marginBottom: 8 }}>&#x1F4CB;</div>
              <div>选择左侧整改任务查看详情</div>
            </div>
          )}
        </div>
      </div>

      {/* 跨店对标排行 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>跨店对标排行</h3>
          {rankStores.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#666', padding: 24 }}>暂无排行数据</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {rankStores.map((s) => {
                const barColor = s.score >= 80 ? '#0F6E56' : s.score >= 60 ? '#BA7517' : '#A32D2D';
                return (
                  <div key={s.rank} style={{
                    display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0',
                    borderBottom: '1px solid #1a2a33',
                  }}>
                    <span style={{
                      width: 24, textAlign: 'center', fontSize: 14, fontWeight: 'bold',
                      color: s.rank <= 3 ? '#FF6B2C' : '#666',
                    }}>
                      {s.rank}
                    </span>
                    <span style={{ flex: 1, fontSize: 13, color: '#fff' }}>{s.name}</span>
                    <div style={{ width: 120, height: 8, borderRadius: 4, background: '#0B1A20', overflow: 'hidden' }}>
                      <div style={{
                        width: `${s.score}%`, height: '100%', borderRadius: 4,
                        background: barColor, transition: 'width 0.6s ease',
                      }} />
                    </div>
                    <span style={{ width: 36, textAlign: 'right', fontSize: 14, fontWeight: 'bold', color: barColor }}>
                      {s.score}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* 图表占位: 评分趋势 */}
        <div>
          <ChartPlaceholder
            title="区域评分趋势"
            chartType="Line"
            apiEndpoint="GET /api/v1/ops/regional/score-trend"
            height={360}
          />
        </div>
      </div>
    </div>
  );
}
