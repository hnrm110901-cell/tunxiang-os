/**
 * 区域追踪整改页 -- E8 总部端
 * 功能: 区域门店评分卡(红黄绿) + 整改任务列表(状态筛选) + 整改详情(时间线) + 跨店对标排行
 * 调用 GET /api/v1/regional/*
 */
import { useState } from 'react';
import { ChartPlaceholder } from '../../../components/ChartPlaceholder';

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

// ---------- 评分配色 ----------
const LEVEL_CONFIG: Record<ScoreLevel, { label: string; color: string; bg: string }> = {
  green:  { label: '达标', color: '#0F6E56', bg: '#0F6E5625' },
  yellow: { label: '预警', color: '#BA7517', bg: '#BA751725' },
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

// ---------- Mock 数据 ----------
const MOCK_STORES: StoreScoreCard[] = [
  { id: 's1', name: '芙蓉路店', region: '长沙', score: 92, level: 'green', issues: 0, lastInspect: '2026-03-26' },
  { id: 's2', name: '岳麓店', region: '长沙', score: 78, level: 'yellow', issues: 3, lastInspect: '2026-03-25' },
  { id: 's3', name: '星沙店', region: '长沙', score: 65, level: 'yellow', issues: 5, lastInspect: '2026-03-24' },
  { id: 's4', name: '河西店', region: '长沙', score: 42, level: 'red', issues: 8, lastInspect: '2026-03-23' },
  { id: 's5', name: '开福店', region: '长沙', score: 85, level: 'green', issues: 1, lastInspect: '2026-03-26' },
  { id: 's6', name: '天心店', region: '长沙', score: 58, level: 'red', issues: 6, lastInspect: '2026-03-22' },
  { id: 's7', name: '雨花店', region: '长沙', score: 74, level: 'yellow', issues: 4, lastInspect: '2026-03-25' },
  { id: 's8', name: '望城店', region: '长沙', score: 88, level: 'green', issues: 1, lastInspect: '2026-03-26' },
];

const MOCK_TASKS: RectifyTask[] = [
  { id: 't1', store: '河西店', title: '厨房卫生不达标整改', status: '已超期', priority: 'high', deadline: '2026-03-20', assignee: '张店长' },
  { id: 't2', store: '天心店', title: '前厅服务流程规范', status: '进行中', priority: 'high', deadline: '2026-03-28', assignee: '李店长' },
  { id: 't3', store: '星沙店', title: '出品稳定性改善', status: '进行中', priority: 'medium', deadline: '2026-03-30', assignee: '王店长' },
  { id: 't4', store: '岳麓店', title: '仓库管理整改', status: '待处理', priority: 'medium', deadline: '2026-04-01', assignee: '赵店长' },
  { id: 't5', store: '河西店', title: '员工仪容仪表规范', status: '已完成', priority: 'low', deadline: '2026-03-18', assignee: '张店长' },
  { id: 't6', store: '雨花店', title: '餐具破损率整改', status: '待处理', priority: 'low', deadline: '2026-04-05', assignee: '周店长' },
  { id: 't7', store: '天心店', title: '食材存储温控整改', status: '已超期', priority: 'high', deadline: '2026-03-15', assignee: '李店长' },
];

const MOCK_TIMELINE: TimelineItem[] = [
  { time: '03-26 16:30', action: '提交整改报告', operator: '李店长', detail: '前厅服务流程已完成培训，附上培训签到表和考核结果' },
  { time: '03-25 10:00', action: '现场复查', operator: '区域经理·陈', detail: '厨房卫生有所改善，仍有3项未达标' },
  { time: '03-23 09:00', action: '下发整改通知', operator: '总部运营', detail: '要求3月28日前完成前厅服务流程整改' },
  { time: '03-20 14:30', action: '巡检发现问题', operator: '巡检员·刘', detail: '前厅服务流程不规范：迎宾话术缺失、上菜顺序混乱' },
];

const RANK_STORES = [
  { rank: 1, name: '芙蓉路店', score: 92, trend: '+3' },
  { rank: 2, name: '望城店', score: 88, trend: '+5' },
  { rank: 3, name: '开福店', score: 85, trend: '-2' },
  { rank: 4, name: '岳麓店', score: 78, trend: '+1' },
  { rank: 5, name: '雨花店', score: 74, trend: '-4' },
  { rank: 6, name: '星沙店', score: 65, trend: '-3' },
  { rank: 7, name: '天心店', score: 58, trend: '-6' },
  { rank: 8, name: '河西店', score: 42, trend: '-8' },
];

// ---------- 组件 ----------
export function RegionalPage() {
  const [statusFilter, setStatusFilter] = useState<TaskStatus>('全部');
  const [selectedTask, setSelectedTask] = useState<string | null>('t2');

  const filteredTasks = statusFilter === '全部'
    ? MOCK_TASKS
    : MOCK_TASKS.filter((t) => t.status === statusFilter);

  const statusCounts = {
    '全部': MOCK_TASKS.length,
    '待处理': MOCK_TASKS.filter((t) => t.status === '待处理').length,
    '进行中': MOCK_TASKS.filter((t) => t.status === '进行中').length,
    '已完成': MOCK_TASKS.filter((t) => t.status === '已完成').length,
    '已超期': MOCK_TASKS.filter((t) => t.status === '已超期').length,
  };

  return (
    <div>
      {/* 标题行 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>区域追踪整改</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: '#999' }}>长沙区域 | 8 家门店</span>
        </div>
      </div>

      {/* 区域门店评分卡网格 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 24 }}>
        {MOCK_STORES.map((store) => {
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
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {filteredTasks.map((task) => {
              const sCfg = STATUS_CONFIG[task.status];
              const pCfg = PRIORITY_LABEL[task.priority];
              const isSelected = selectedTask === task.id;
              return (
                <div
                  key={task.id}
                  onClick={() => setSelectedTask(task.id)}
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
        </div>

        {/* 整改详情 - 时间线 */}
        <div style={{ background: '#112228', borderRadius: 8, padding: 20 }}>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>整改详情 - 操作记录</h3>
          {selectedTask ? (
            <div style={{ position: 'relative', paddingLeft: 20 }}>
              {/* 时间轴线 */}
              <div style={{
                position: 'absolute', left: 6, top: 8, bottom: 8, width: 2,
                background: '#1a2a33',
              }} />
              {MOCK_TIMELINE.map((item, i) => (
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
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {RANK_STORES.map((s) => {
              const barColor = s.score >= 80 ? '#0F6E56' : s.score >= 60 ? '#BA7517' : '#A32D2D';
              const trendUp = s.trend.startsWith('+');
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
                  <span style={{
                    width: 32, textAlign: 'right', fontSize: 11,
                    color: trendUp ? '#0F6E56' : '#A32D2D',
                  }}>
                    {trendUp ? '\u2191' : '\u2193'}{s.trend}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* 图表占位: 评分趋势 */}
        <div>
          <ChartPlaceholder
            title="区域评分趋势"
            chartType="Line"
            apiEndpoint="GET /api/v1/regional/score-trend"
            height={360}
          />
        </div>
      </div>
    </div>
  );
}
