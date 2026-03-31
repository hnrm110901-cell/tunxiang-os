/**
 * JourneyDetailPage — 旅程详情页
 * 路由: /hq/growth/journeys/:journeyId
 * 旅程步骤可视化（流程图）+ 每步骤指标 + 近期执行记录表格
 */
import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

// ---- 颜色常量（与 JourneyListPage 保持一致） ----
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

type JourneyStatus = '运行中' | '已暂停' | '草稿' | '已结束';
type StepType = '触发条件' | '等待' | '发送消息' | '人群分支' | '优惠券' | '结束';
type ChannelType = '企业微信' | '短信' | '小程序推送' | '无';

interface JourneyStep {
  id: string;
  type: StepType;
  title: string;
  description: string;
  channel: ChannelType;
  executedCount: number;
  completionRate: number;   // 0-100
  avgWaitHours: number | null;  // null = 触发条件节点无等待
  dropOffCount: number;
}

interface ExecutionRecord {
  id: string;
  customerId: string;
  customerName: string;
  currentStep: string;
  enteredAt: string;
  lastActionAt: string;
  status: '进行中' | '已完成' | '已退出';
  convertedValue: number | null;
}

interface JourneyMeta {
  id: string;
  name: string;
  status: JourneyStatus;
  targetSegment: string;
  targetCount: number;
  executedCount: number;
  conversionRate: number;
  totalRevenue: number;
  roi: number;
  createdAt: string;
  creator: string;
}

// ---- Mock 数据 ----

const MOCK_META: JourneyMeta = {
  id: 'j1',
  name: '新客首单转复购旅程',
  status: '运行中',
  targetSegment: '首单未复购',
  targetCount: 4231,
  executedCount: 3876,
  conversionRate: 18.4,
  totalRevenue: 187400,
  roi: 4.8,
  createdAt: '2026-03-10',
  creator: '运营小王',
};

const MOCK_STEPS: JourneyStep[] = [
  {
    id: 's0', type: '触发条件', title: '首单完成触发', channel: '无',
    description: '客户完成首次消费后 24 小时内进入旅程',
    executedCount: 3876, completionRate: 100, avgWaitHours: null, dropOffCount: 0,
  },
  {
    id: 's1', type: '发送消息', title: '感谢首单消息', channel: '企业微信',
    description: '发送欢迎语 + 品牌介绍 + 新客专属优惠提醒',
    executedCount: 3876, completionRate: 96.2, avgWaitHours: 0.5, dropOffCount: 148,
  },
  {
    id: 's2', type: '等待', title: '等待 3 天', channel: '无',
    description: '等待客户自然回访，3天内到店则进入"自然复购"分支',
    executedCount: 3728, completionRate: 88.1, avgWaitHours: 72, dropOffCount: 128,
  },
  {
    id: 's3', type: '人群分支', title: '3 天内是否到店', channel: '无',
    description: '是 → 高意向分支（复购激励）；否 → 未回访分支（优惠催促）',
    executedCount: 3600, completionRate: 100, avgWaitHours: null, dropOffCount: 0,
  },
  {
    id: 's4', type: '优惠券', title: '发送复购优惠券', channel: '小程序推送',
    description: '发放满 80 减 15 元券，有效期 7 天，限首次复购使用',
    executedCount: 2874, completionRate: 94.5, avgWaitHours: 0.2, dropOffCount: 158,
  },
  {
    id: 's5', type: '发送消息', title: '优惠到期提醒', channel: '短信',
    description: '券到期前 24 小时发送短信提醒，附上门店地址',
    executedCount: 2716, completionRate: 89.3, avgWaitHours: 144, dropOffCount: 290,
  },
  {
    id: 's6', type: '结束', title: '旅程结束节点', channel: '无',
    description: '完成复购或优惠过期后退出旅程，标记转化结果',
    executedCount: 2426, completionRate: 100, avgWaitHours: null, dropOffCount: 0,
  },
];

const MOCK_RECORDS: ExecutionRecord[] = [
  { id: 'r1', customerId: 'C00823', customerName: '张*', currentStep: '优惠到期提醒', enteredAt: '2026-03-25 14:22', lastActionAt: '2026-03-26 09:15', status: '进行中', convertedValue: null },
  { id: 'r2', customerId: 'C00817', customerName: '李*红', currentStep: '旅程结束节点', enteredAt: '2026-03-24 18:05', lastActionAt: '2026-03-26 12:30', status: '已完成', convertedValue: 136 },
  { id: 'r3', customerId: 'C00809', customerName: '王*明', currentStep: '旅程结束节点', enteredAt: '2026-03-23 11:40', lastActionAt: '2026-03-25 19:22', status: '已完成', convertedValue: 98 },
  { id: 'r4', customerId: 'C00801', customerName: '刘*', currentStep: '发送复购优惠券', enteredAt: '2026-03-22 20:11', lastActionAt: '2026-03-24 08:00', status: '进行中', convertedValue: null },
  { id: 'r5', customerId: 'C00795', customerName: '陈*华', currentStep: '旅程结束节点', enteredAt: '2026-03-21 09:33', lastActionAt: '2026-03-23 14:55', status: '已退出', convertedValue: null },
  { id: 'r6', customerId: 'C00788', customerName: '赵*', currentStep: '旅程结束节点', enteredAt: '2026-03-20 16:00', lastActionAt: '2026-03-22 18:40', status: '已完成', convertedValue: 152 },
  { id: 'r7', customerId: 'C00780', customerName: '孙*文', currentStep: '旅程结束节点', enteredAt: '2026-03-19 13:15', lastActionAt: '2026-03-21 10:05', status: '已完成', convertedValue: 88 },
  { id: 'r8', customerId: 'C00773', customerName: '周*', currentStep: '旅程结束节点', enteredAt: '2026-03-18 17:48', lastActionAt: '2026-03-20 20:20', status: '已退出', convertedValue: null },
  { id: 'r9', customerId: 'C00765', customerName: '吴*芳', currentStep: '旅程结束节点', enteredAt: '2026-03-17 10:02', lastActionAt: '2026-03-19 09:30', status: '已完成', convertedValue: 124 },
  { id: 'r10', customerId: 'C00758', customerName: '郑*', currentStep: '旅程结束节点', enteredAt: '2026-03-16 15:20', lastActionAt: '2026-03-18 11:50', status: '已完成', convertedValue: 108 },
];

// ---- 子组件 ----

const stepTypeColors: Record<StepType, string> = {
  '触发条件': BRAND,
  '等待': TEXT_4,
  '发送消息': BLUE,
  '人群分支': PURPLE,
  '优惠券': GREEN,
  '结束': RED,
};

const channelColors: Record<ChannelType, string> = {
  '企业微信': GREEN,
  '短信': YELLOW,
  '小程序推送': BLUE,
  '无': TEXT_4,
};

function JourneyMetaCard({ meta }: { meta: JourneyMeta }) {
  const statusColors: Record<JourneyStatus, string> = {
    '运行中': GREEN, '已暂停': YELLOW, '草稿': TEXT_4, '已结束': BLUE,
  };
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '16px 20px',
      border: `1px solid ${BG_2}`, marginBottom: 16,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: TEXT_1 }}>{meta.name}</span>
        <span style={{
          fontSize: 11, padding: '2px 10px', borderRadius: 10,
          background: statusColors[meta.status] + '22',
          color: statusColors[meta.status], fontWeight: 700,
        }}>{meta.status}</span>
        <span style={{ fontSize: 12, color: TEXT_4 }}>创建于 {meta.createdAt} · {meta.creator}</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 12 }}>
        {[
          { label: '目标人群', value: meta.targetSegment, color: BRAND },
          { label: '目标人数', value: meta.targetCount.toLocaleString(), color: TEXT_1 },
          { label: '已执行', value: meta.executedCount.toLocaleString(), color: TEXT_1 },
          { label: '转化率', value: `${meta.conversionRate}%`, color: meta.conversionRate >= 15 ? GREEN : YELLOW },
          { label: '归因收益', value: `¥${(meta.totalRevenue / 10000).toFixed(1)}万`, color: GREEN },
          { label: 'ROI', value: `${meta.roi}x`, color: meta.roi >= 3 ? GREEN : YELLOW },
        ].map(item => (
          <div key={item.label}>
            <div style={{ fontSize: 11, color: TEXT_4, marginBottom: 4 }}>{item.label}</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: item.color }}>{item.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function JourneyFlowChart({ steps }: { steps: JourneyStep[] }) {
  const [hoveredStep, setHoveredStep] = useState<string | null>(null);

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '20px 24px',
      border: `1px solid ${BG_2}`, flex: '0 0 380px', minWidth: 340,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 20 }}>旅程步骤流程</div>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        {steps.map((step, idx) => {
          const color = stepTypeColors[step.type];
          const isHovered = hoveredStep === step.id;
          const completionPct = step.completionRate;

          return (
            <div key={step.id} style={{ width: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              {/* 连接线 */}
              {idx > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', margin: '4px 0' }}>
                  <div style={{ width: 2, height: 20, background: BG_2 }} />
                  <div style={{
                    width: 0, height: 0,
                    borderLeft: '5px solid transparent', borderRight: '5px solid transparent',
                    borderTop: `6px solid ${BG_2}`,
                  }} />
                </div>
              )}
              {/* 步骤卡片 */}
              <div
                style={{
                  width: '100%', padding: '12px 14px', borderRadius: 8,
                  background: isHovered ? BG_2 : `${color}11`,
                  border: `1px solid ${color}44`,
                  cursor: 'pointer', transition: 'all .15s',
                  borderLeft: `3px solid ${color}`,
                }}
                onMouseEnter={() => setHoveredStep(step.id)}
                onMouseLeave={() => setHoveredStep(null)}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{
                      fontSize: 10, padding: '1px 6px', borderRadius: 4,
                      background: color + '22', color, fontWeight: 600,
                    }}>{step.type}</span>
                    {step.channel !== '无' && (
                      <span style={{
                        fontSize: 10, padding: '1px 6px', borderRadius: 4,
                        background: channelColors[step.channel] + '22',
                        color: channelColors[step.channel],
                      }}>{step.channel}</span>
                    )}
                  </div>
                  <span style={{ fontSize: 11, color: TEXT_4 }}>#{idx + 1}</span>
                </div>
                <div style={{ fontSize: 13, fontWeight: 600, color: TEXT_1, marginBottom: 2 }}>{step.title}</div>
                <div style={{ fontSize: 11, color: TEXT_3, marginBottom: 8 }}>{step.description}</div>
                {/* 执行进度条 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{ flex: 1, height: 4, borderRadius: 2, background: BG_2 }}>
                    <div style={{
                      width: `${completionPct}%`, height: '100%', borderRadius: 2,
                      background: completionPct >= 90 ? GREEN : completionPct >= 70 ? YELLOW : RED,
                    }} />
                  </div>
                  <span style={{ fontSize: 11, color: TEXT_3, minWidth: 34, textAlign: 'right' }}>
                    {completionPct.toFixed(0)}%
                  </span>
                </div>
                {/* 指标行 */}
                <div style={{ display: 'flex', gap: 14, marginTop: 6, fontSize: 11, color: TEXT_4 }}>
                  <span>执行 <span style={{ color: TEXT_2 }}>{step.executedCount.toLocaleString()}</span></span>
                  {step.dropOffCount > 0 && (
                    <span>流失 <span style={{ color: RED }}>{step.dropOffCount.toLocaleString()}</span></span>
                  )}
                  {step.avgWaitHours !== null && (
                    <span>
                      均等待 <span style={{ color: TEXT_2 }}>
                        {step.avgWaitHours < 24
                          ? `${step.avgWaitHours}h`
                          : `${(step.avgWaitHours / 24).toFixed(0)}天`}
                      </span>
                    </span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function StepFunnelChart({ steps }: { steps: JourneyStep[] }) {
  const maxCount = steps[0]?.executedCount ?? 1;
  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '20px 24px',
      border: `1px solid ${BG_2}`, flex: 1, minWidth: 0,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 20 }}>漏斗分析</div>
      {steps.map((step, idx) => {
        const barWidth = (step.executedCount / maxCount) * 100;
        const color = stepTypeColors[step.type];
        return (
          <div key={step.id} style={{ marginBottom: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
              <span style={{ fontSize: 11, color: TEXT_4, minWidth: 18 }}>S{idx + 1}</span>
              <span style={{ fontSize: 12, color: TEXT_2, minWidth: 120, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {step.title}
              </span>
              <div style={{ flex: 1, height: 20, borderRadius: 4, background: BG_2, position: 'relative' }}>
                <div style={{
                  width: `${barWidth}%`, height: '100%', borderRadius: 4,
                  background: `linear-gradient(90deg, ${color}88, ${color}44)`,
                  display: 'flex', alignItems: 'center', paddingLeft: 6,
                }}>
                  {barWidth > 20 && (
                    <span style={{ fontSize: 10, color: '#fff', fontWeight: 600 }}>
                      {step.executedCount.toLocaleString()}人
                    </span>
                  )}
                </div>
              </div>
              <span style={{ fontSize: 11, color: TEXT_3, minWidth: 36, textAlign: 'right' }}>
                {((step.executedCount / maxCount) * 100).toFixed(0)}%
              </span>
            </div>
            {/* 转化率指示 */}
            {idx > 0 && steps[idx - 1].executedCount > 0 && (
              <div style={{ paddingLeft: 28, fontSize: 10, color: TEXT_4 }}>
                环节转化率:
                <span style={{ color: step.executedCount / steps[idx - 1].executedCount >= 0.9 ? GREEN : YELLOW, marginLeft: 4 }}>
                  {((step.executedCount / steps[idx - 1].executedCount) * 100).toFixed(1)}%
                </span>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function ExecutionRecordTable({ records }: { records: ExecutionRecord[] }) {
  const [page, setPage] = useState(1);
  const pageSize = 10;
  const totalPages = Math.ceil(records.length / pageSize);
  const pagedRecords = records.slice((page - 1) * pageSize, page * pageSize);

  const statusColors: Record<ExecutionRecord['status'], string> = {
    '进行中': BLUE,
    '已完成': GREEN,
    '已退出': TEXT_4,
  };

  return (
    <div style={{
      background: BG_1, borderRadius: 10, padding: '16px 20px',
      border: `1px solid ${BG_2}`,
    }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: TEXT_1, marginBottom: 14 }}>近期执行记录</div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${BG_2}` }}>
              {['客户ID', '姓名', '当前步骤', '进入时间', '最后操作', '状态', '转化金额'].map(h => (
                <th key={h} style={{
                  textAlign: 'left', padding: '8px 12px',
                  color: TEXT_4, fontWeight: 600, fontSize: 11, whiteSpace: 'nowrap',
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pagedRecords.map(r => (
              <tr key={r.id} style={{ borderBottom: `1px solid ${BG_2}` }}>
                <td style={{ padding: '10px 12px', color: TEXT_3 }}>{r.customerId}</td>
                <td style={{ padding: '10px 12px', color: TEXT_1, fontWeight: 500 }}>{r.customerName}</td>
                <td style={{ padding: '10px 12px', color: TEXT_2 }}>{r.currentStep}</td>
                <td style={{ padding: '10px 12px', color: TEXT_3, whiteSpace: 'nowrap' }}>{r.enteredAt}</td>
                <td style={{ padding: '10px 12px', color: TEXT_3, whiteSpace: 'nowrap' }}>{r.lastActionAt}</td>
                <td style={{ padding: '10px 12px' }}>
                  <span style={{
                    fontSize: 11, padding: '2px 8px', borderRadius: 10,
                    background: statusColors[r.status] + '22',
                    color: statusColors[r.status], fontWeight: 600,
                  }}>{r.status}</span>
                </td>
                <td style={{ padding: '10px 12px' }}>
                  {r.convertedValue != null
                    ? <span style={{ color: GREEN, fontWeight: 600 }}>¥{r.convertedValue}</span>
                    : <span style={{ color: TEXT_4 }}>-</span>
                  }
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {/* 分页 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}>
        <span style={{ fontSize: 12, color: TEXT_4 }}>共 {records.length} 条</span>
        <button
          disabled={page === 1}
          onClick={() => setPage(p => p - 1)}
          style={{
            padding: '4px 10px', borderRadius: 6, border: `1px solid ${BG_2}`,
            background: BG_2, color: page === 1 ? TEXT_4 : TEXT_2,
            fontSize: 12, cursor: page === 1 ? 'default' : 'pointer',
          }}
        >上一页</button>
        <span style={{ fontSize: 12, color: TEXT_3 }}>{page} / {totalPages}</span>
        <button
          disabled={page === totalPages}
          onClick={() => setPage(p => p + 1)}
          style={{
            padding: '4px 10px', borderRadius: 6, border: `1px solid ${BG_2}`,
            background: BG_2, color: page === totalPages ? TEXT_4 : TEXT_2,
            fontSize: 12, cursor: page === totalPages ? 'default' : 'pointer',
          }}
        >下一页</button>
      </div>
    </div>
  );
}

// ---- 主页面 ----

export function JourneyDetailPage() {
  const { journeyId } = useParams<{ journeyId: string }>();
  const navigate = useNavigate();

  // 实际项目中根据 journeyId 请求对应旅程数据，此处使用 Mock
  const meta = { ...MOCK_META, id: journeyId ?? MOCK_META.id };

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      {/* 顶部导航 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <button
          onClick={() => navigate('/hq/growth/journeys')}
          style={{
            padding: '6px 14px', borderRadius: 6, border: `1px solid ${BG_2}`,
            background: 'transparent', color: TEXT_3, fontSize: 12, cursor: 'pointer',
          }}
        >← 返回列表</button>
        <span style={{ color: TEXT_4 }}>/</span>
        <span style={{ fontSize: 20, fontWeight: 700, color: TEXT_1 }}>旅程详情</span>
        <div style={{ flex: 1 }} />
        <button
          onClick={() => navigate(`/hq/growth/journeys/${journeyId}/canvas`)}
          style={{
            padding: '8px 18px', borderRadius: 8, border: 'none',
            background: BRAND, color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer',
          }}
        >编辑画布</button>
        <button
          style={{
            padding: '8px 18px', borderRadius: 8, border: `1px solid ${YELLOW}44`,
            background: YELLOW + '11', color: YELLOW, fontSize: 13, fontWeight: 600, cursor: 'pointer',
          }}
        >暂停旅程</button>
      </div>

      {/* 元信息卡片 */}
      <JourneyMetaCard meta={meta} />

      {/* 中部：流程图 + 漏斗图 */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 16, alignItems: 'flex-start' }}>
        <JourneyFlowChart steps={MOCK_STEPS} />
        <StepFunnelChart steps={MOCK_STEPS} />
      </div>

      {/* 执行记录 */}
      <ExecutionRecordTable records={MOCK_RECORDS} />
    </div>
  );
}
