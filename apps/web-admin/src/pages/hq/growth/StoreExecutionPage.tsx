/**
 * StoreExecutionPage — 门店执行中心
 * 路由: /hq/growth/execution
 * 任务总览 + 日历视图 + 门店进度 + 问题升级看板
 */
import { useState } from 'react';

const BG_0 = '#0B1A20';
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

type TabKey = 'overview' | 'calendar' | 'progress' | 'issues';

interface TaskSummary {
  total: number;
  completed: number;
  pending: number;
  overdue: number;
}

interface StoreTask {
  id: string;
  taskName: string;
  type: '物料布置' | '活动执行' | '话术培训' | '数据录入' | '顾客回访';
  storeName: string;
  assignee: string;
  dueDate: string;
  status: '已完成' | '进行中' | '待开始' | '已逾期';
  completionRate: number;
}

interface CalendarEvent {
  id: string;
  date: string;
  title: string;
  type: string;
  storeCount: number;
  status: '已完成' | '进行中' | '待启动';
}

interface StoreProgress {
  storeName: string;
  region: string;
  totalTasks: number;
  completedTasks: number;
  overdueTasks: number;
  avgCompletionTime: number;
  score: number;
}

interface IssueItem {
  id: string;
  title: string;
  storeName: string;
  reporter: string;
  severity: 'high' | 'medium' | 'low';
  category: string;
  reportedAt: string;
  status: '待处理' | '处理中' | '已解决';
  description: string;
}

const MOCK_SUMMARY: TaskSummary = { total: 248, completed: 186, pending: 42, overdue: 20 };

const MOCK_TASKS: StoreTask[] = [
  { id: 'st1', taskName: '春季海报张贴', type: '物料布置', storeName: '芙蓉路店', assignee: '张伟', dueDate: '2026-03-26', status: '已完成', completionRate: 100 },
  { id: 'st2', taskName: '新品话术培训', type: '话术培训', storeName: '万达广场店', assignee: '李敏', dueDate: '2026-03-26', status: '进行中', completionRate: 60 },
  { id: 'st3', taskName: '会员日活动执行', type: '活动执行', storeName: '梅溪湖店', assignee: '王芳', dueDate: '2026-03-27', status: '待开始', completionRate: 0 },
  { id: 'st4', taskName: '顾客满意度回访', type: '顾客回访', storeName: '五一广场店', assignee: '陈思', dueDate: '2026-03-25', status: '已逾期', completionRate: 30 },
  { id: 'st5', taskName: '储值卡推广物料', type: '物料布置', storeName: '星沙店', assignee: '赵磊', dueDate: '2026-03-26', status: '已完成', completionRate: 100 },
  { id: 'st6', taskName: '裂变活动推广', type: '活动执行', storeName: '河西大学城店', assignee: '周晓', dueDate: '2026-03-26', status: '进行中', completionRate: 45 },
  { id: 'st7', taskName: '新品销量录入', type: '数据录入', storeName: '开福寺店', assignee: '吴刚', dueDate: '2026-03-24', status: '已逾期', completionRate: 0 },
  { id: 'st8', taskName: '清明节活动准备', type: '活动执行', storeName: '芙蓉路店', assignee: '张伟', dueDate: '2026-04-02', status: '待开始', completionRate: 0 },
];

const MOCK_CALENDAR: CalendarEvent[] = [
  { id: 'ce1', date: '2026-03-20', title: '春季海报更换', type: '物料布置', storeCount: 12, status: '已完成' },
  { id: 'ce2', date: '2026-03-22', title: '新品上线培训', type: '话术培训', storeCount: 12, status: '已完成' },
  { id: 'ce3', date: '2026-03-24', title: '会员日准备', type: '活动执行', storeCount: 12, status: '已完成' },
  { id: 'ce4', date: '2026-03-25', title: '会员日执行', type: '活动执行', storeCount: 12, status: '已完成' },
  { id: 'ce5', date: '2026-03-26', title: '裂变推广启动', type: '活动执行', storeCount: 8, status: '进行中' },
  { id: 'ce6', date: '2026-03-27', title: '顾客回访', type: '顾客回访', storeCount: 6, status: '待启动' },
  { id: 'ce7', date: '2026-03-28', title: '周末促销布置', type: '物料布置', storeCount: 12, status: '待启动' },
  { id: 'ce8', date: '2026-03-31', title: '月末数据汇总', type: '数据录入', storeCount: 12, status: '待启动' },
  { id: 'ce9', date: '2026-04-02', title: '清明节准备', type: '活动执行', storeCount: 12, status: '待启动' },
  { id: 'ce10', date: '2026-04-04', title: '清明节执行', type: '活动执行', storeCount: 12, status: '待启动' },
];

const MOCK_PROGRESS: StoreProgress[] = [
  { storeName: '芙蓉路店', region: '华中区', totalTasks: 32, completedTasks: 30, overdueTasks: 0, avgCompletionTime: 1.2, score: 95 },
  { storeName: '万达广场店', region: '华中区', totalTasks: 32, completedTasks: 28, overdueTasks: 1, avgCompletionTime: 1.5, score: 88 },
  { storeName: '梅溪湖店', region: '华中区', totalTasks: 32, completedTasks: 26, overdueTasks: 2, avgCompletionTime: 1.8, score: 82 },
  { storeName: '五一广场店', region: '华中区', totalTasks: 32, completedTasks: 22, overdueTasks: 5, avgCompletionTime: 2.3, score: 72 },
  { storeName: '星沙店', region: '华中区', totalTasks: 32, completedTasks: 27, overdueTasks: 1, avgCompletionTime: 1.6, score: 85 },
  { storeName: '河西大学城店', region: '华中区', totalTasks: 32, completedTasks: 24, overdueTasks: 3, avgCompletionTime: 2.0, score: 76 },
  { storeName: '开福寺店', region: '华中区', totalTasks: 32, completedTasks: 20, overdueTasks: 6, avgCompletionTime: 2.8, score: 65 },
];

const MOCK_ISSUES: IssueItem[] = [
  { id: 'is1', title: '新品物料未到货', storeName: '五一广场店', reporter: '陈思', severity: 'high', category: '物料问题', reportedAt: '2026-03-26 09:30', status: '待处理', description: '酸汤系列推广海报和桌贴未到货，影响新品推广执行' },
  { id: 'is2', title: '收银系统券核销异常', storeName: '开福寺店', reporter: '吴刚', severity: 'high', category: '系统问题', reportedAt: '2026-03-26 10:15', status: '处理中', description: 'POS系统无法正确核销老带新邀请券，多位顾客投诉' },
  { id: 'is3', title: '培训人员不足', storeName: '河西大学城店', reporter: '周晓', severity: 'medium', category: '人员问题', reportedAt: '2026-03-25 16:00', status: '待处理', description: '新品话术培训需要全员参与，但当天排班人手不够' },
  { id: 'is4', title: '活动海报破损', storeName: '梅溪湖店', reporter: '王芳', severity: 'low', category: '物料问题', reportedAt: '2026-03-25 14:20', status: '已解决', description: '门口展架海报因风雨破损，需要补发' },
  { id: 'is5', title: '储值活动规则不清', storeName: '万达广场店', reporter: '李敏', severity: 'medium', category: '流程问题', reportedAt: '2026-03-24 11:30', status: '已解决', description: '员工对储值赠送规则理解不一致，需重新培训' },
];

function TaskOverview({ summary, tasks }: { summary: TaskSummary; tasks: StoreTask[] }) {
  const statusColors: Record<string, string> = { '已完成': GREEN, '进行中': BLUE, '待开始': TEXT_4, '已逾期': RED };
  const typeColors: Record<string, string> = { '物料布置': BRAND, '活动执行': BLUE, '话术培训': PURPLE, '数据录入': TEXT_3, '顾客回访': GREEN };

  return (
    <div>
      {/* Summary cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16 }}>
        {[
          { label: '总任务', value: summary.total, color: TEXT_1 },
          { label: '已完成', value: summary.completed, color: GREEN },
          { label: '待完成', value: summary.pending, color: YELLOW },
          { label: '已逾期', value: summary.overdue, color: RED },
        ].map((c, i) => (
          <div key={i} style={{
            background: BG_1, borderRadius: 10, padding: '16px 18px',
            border: `1px solid ${BG_2}`,
          }}>
            <div style={{ fontSize: 12, color: TEXT_3, marginBottom: 6 }}>{c.label}</div>
            <div style={{ fontSize: 30, fontWeight: 700, color: c.color }}>{c.value}</div>
            <div style={{
              width: '100%', height: 4, borderRadius: 2, background: BG_2, marginTop: 8,
            }}>
              <div style={{
                width: `${(c.value / summary.total) * 100}%`, height: '100%',
                borderRadius: 2, background: c.color,
              }} />
            </div>
          </div>
        ))}
      </div>

      {/* Task list */}
      <div style={{
        background: BG_1, borderRadius: 10, padding: 16,
        border: `1px solid ${BG_2}`,
      }}>
        <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>任务列表</h3>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${BG_2}` }}>
              {['任务名称', '类型', '门店', '负责人', '截止日期', '完成度', '状态'].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '8px 10px', color: TEXT_4, fontWeight: 600, fontSize: 11 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tasks.map(t => (
              <tr key={t.id} style={{ borderBottom: `1px solid ${BG_2}` }}>
                <td style={{ padding: '10px', color: TEXT_1, fontWeight: 500 }}>{t.taskName}</td>
                <td style={{ padding: '10px' }}>
                  <span style={{
                    fontSize: 10, padding: '2px 8px', borderRadius: 4,
                    background: (typeColors[t.type] || TEXT_4) + '22', color: typeColors[t.type] || TEXT_4, fontWeight: 600,
                  }}>{t.type}</span>
                </td>
                <td style={{ padding: '10px', color: TEXT_2 }}>{t.storeName}</td>
                <td style={{ padding: '10px', color: TEXT_3 }}>{t.assignee}</td>
                <td style={{ padding: '10px', color: t.status === '已逾期' ? RED : TEXT_3 }}>{t.dueDate}</td>
                <td style={{ padding: '10px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <div style={{ width: 60, height: 4, borderRadius: 2, background: BG_2 }}>
                      <div style={{
                        width: `${t.completionRate}%`, height: '100%', borderRadius: 2,
                        background: t.completionRate === 100 ? GREEN : t.completionRate > 0 ? BLUE : TEXT_4,
                      }} />
                    </div>
                    <span style={{ fontSize: 11, color: TEXT_3 }}>{t.completionRate}%</span>
                  </div>
                </td>
                <td style={{ padding: '10px' }}>
                  <span style={{
                    fontSize: 10, padding: '2px 8px', borderRadius: 4,
                    background: statusColors[t.status] + '22', color: statusColors[t.status], fontWeight: 600,
                  }}>{t.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CalendarView({ events }: { events: CalendarEvent[] }) {
  const statusColors: Record<string, string> = { '已完成': GREEN, '进行中': BLUE, '待启动': TEXT_4 };
  // Group by week
  const weeks = ['第12周 (3/20-3/26)', '第13周 (3/27-3/31)', '第14周 (4/1-4/6)'];
  const weekEvents = [
    events.filter(e => e.date >= '2026-03-20' && e.date <= '2026-03-26'),
    events.filter(e => e.date >= '2026-03-27' && e.date <= '2026-03-31'),
    events.filter(e => e.date >= '2026-04-01' && e.date <= '2026-04-06'),
  ];

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 20,
      border: `1px solid ${BG_2}`,
    }}>
      <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>活动日历</h3>
      {weeks.map((week, wi) => (
        <div key={wi} style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: TEXT_2, marginBottom: 10, padding: '4px 0', borderBottom: `1px solid ${BG_2}` }}>
            {week}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {weekEvents[wi].map(e => (
              <div key={e.id} style={{
                display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px',
                background: BG_2, borderRadius: 8,
                borderLeft: `3px solid ${statusColors[e.status]}`,
              }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: BRAND, minWidth: 70 }}>{e.date.slice(5)}</span>
                <span style={{ fontSize: 13, fontWeight: 600, color: TEXT_1, flex: 1 }}>{e.title}</span>
                <span style={{
                  fontSize: 10, padding: '2px 8px', borderRadius: 4,
                  background: BG_1, color: TEXT_3, fontWeight: 600,
                }}>{e.type}</span>
                <span style={{ fontSize: 11, color: TEXT_3 }}>{e.storeCount} 门店</span>
                <span style={{
                  fontSize: 10, padding: '2px 8px', borderRadius: 4,
                  background: statusColors[e.status] + '22', color: statusColors[e.status], fontWeight: 600,
                }}>{e.status}</span>
              </div>
            ))}
            {weekEvents[wi].length === 0 && (
              <div style={{ padding: 14, textAlign: 'center', fontSize: 12, color: TEXT_4 }}>暂无活动安排</div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function StoreProgressTable({ stores }: { stores: StoreProgress[] }) {
  const sorted = [...stores].sort((a, b) => b.score - a.score);

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 16,
      border: `1px solid ${BG_2}`,
    }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>门店执行进度</h3>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${BG_2}` }}>
            {['排名', '门店', '区域', '总任务', '已完成', '已逾期', '平均耗时(天)', '完成率', '评分'].map(h => (
              <th key={h} style={{ textAlign: 'left', padding: '8px 10px', color: TEXT_4, fontWeight: 600, fontSize: 11 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((s, i) => {
            const completionRate = (s.completedTasks / s.totalTasks * 100).toFixed(0);
            return (
              <tr key={s.storeName} style={{ borderBottom: `1px solid ${BG_2}` }}>
                <td style={{ padding: '10px' }}>
                  <span style={{
                    width: 24, height: 24, borderRadius: 12, display: 'inline-flex',
                    alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700,
                    background: i < 3 ? BRAND + '22' : BG_2, color: i < 3 ? BRAND : TEXT_4,
                  }}>{i + 1}</span>
                </td>
                <td style={{ padding: '10px', color: TEXT_1, fontWeight: 500 }}>{s.storeName}</td>
                <td style={{ padding: '10px', color: TEXT_3 }}>{s.region}</td>
                <td style={{ padding: '10px', color: TEXT_2 }}>{s.totalTasks}</td>
                <td style={{ padding: '10px', color: GREEN }}>{s.completedTasks}</td>
                <td style={{ padding: '10px', color: s.overdueTasks > 0 ? RED : TEXT_4 }}>{s.overdueTasks}</td>
                <td style={{ padding: '10px', color: s.avgCompletionTime > 2 ? YELLOW : TEXT_2 }}>{s.avgCompletionTime}</td>
                <td style={{ padding: '10px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <div style={{ width: 60, height: 4, borderRadius: 2, background: BG_2 }}>
                      <div style={{
                        width: `${completionRate}%`, height: '100%', borderRadius: 2,
                        background: Number(completionRate) > 85 ? GREEN : Number(completionRate) > 70 ? YELLOW : RED,
                      }} />
                    </div>
                    <span style={{ fontSize: 11, color: TEXT_3 }}>{completionRate}%</span>
                  </div>
                </td>
                <td style={{ padding: '10px' }}>
                  <span style={{
                    fontSize: 14, fontWeight: 700,
                    color: s.score >= 85 ? GREEN : s.score >= 70 ? YELLOW : RED,
                  }}>{s.score}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function IssueBoard({ issues }: { issues: IssueItem[] }) {
  const sevColors: Record<string, string> = { high: RED, medium: YELLOW, low: BLUE };
  const sevLabels: Record<string, string> = { high: '紧急', medium: '一般', low: '低' };
  const statusColors: Record<string, string> = { '待处理': RED, '处理中': YELLOW, '已解决': GREEN };

  const columns = ['待处理', '处理中', '已解决'] as const;

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: 16,
      border: `1px solid ${BG_2}`,
    }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 15, fontWeight: 700, color: TEXT_1 }}>问题升级看板</h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
        {columns.map(col => {
          const colIssues = issues.filter(i => i.status === col);
          return (
            <div key={col}>
              <div style={{
                padding: '8px 12px', borderRadius: '8px 8px 0 0',
                background: statusColors[col] + '22', textAlign: 'center',
                fontSize: 13, fontWeight: 600, color: statusColors[col],
              }}>
                {col} ({colIssues.length})
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, paddingTop: 8 }}>
                {colIssues.map(issue => (
                  <div key={issue.id} style={{
                    padding: '12px 14px', background: BG_2, borderRadius: 8,
                    borderLeft: `3px solid ${sevColors[issue.severity]}`,
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                      <span style={{
                        fontSize: 10, padding: '1px 6px', borderRadius: 4,
                        background: sevColors[issue.severity] + '22', color: sevColors[issue.severity], fontWeight: 700,
                      }}>{sevLabels[issue.severity]}</span>
                      <span style={{
                        fontSize: 10, padding: '1px 6px', borderRadius: 4,
                        background: BG_1, color: TEXT_3, fontWeight: 600,
                      }}>{issue.category}</span>
                    </div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: TEXT_1, marginBottom: 4 }}>{issue.title}</div>
                    <div style={{ fontSize: 11, color: TEXT_3, lineHeight: 1.5, marginBottom: 6 }}>{issue.description}</div>
                    <div style={{ fontSize: 10, color: TEXT_4 }}>
                      {issue.storeName} | {issue.reporter} | {issue.reportedAt}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---- 主页面 ----

export function StoreExecutionPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('overview');
  const tabs: { key: TabKey; label: string }[] = [
    { key: 'overview', label: '任务总览' },
    { key: 'calendar', label: '活动日历' },
    { key: 'progress', label: '门店进度' },
    { key: 'issues', label: '问题升级' },
  ];

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      <h2 style={{ margin: '0 0 16px', fontSize: 22, fontWeight: 700 }}>门店执行中心</h2>

      <div style={{ display: 'flex', gap: 4, marginBottom: 16 }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => setActiveTab(t.key)} style={{
            padding: '8px 18px', borderRadius: 8, border: 'none', cursor: 'pointer',
            background: activeTab === t.key ? BRAND : BG_1,
            color: activeTab === t.key ? '#fff' : TEXT_3,
            fontSize: 13, fontWeight: 600,
          }}>{t.label}</button>
        ))}
      </div>

      {activeTab === 'overview' && <TaskOverview summary={MOCK_SUMMARY} tasks={MOCK_TASKS} />}
      {activeTab === 'calendar' && <CalendarView events={MOCK_CALENDAR} />}
      {activeTab === 'progress' && <StoreProgressTable stores={MOCK_PROGRESS} />}
      {activeTab === 'issues' && <IssueBoard issues={MOCK_ISSUES} />}
    </div>
  );
}
