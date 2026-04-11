/**
 * AgentActionLog — Agent 决策行动日志组件
 * Sprint 1: 运营指挥官基础层
 * Sprint 2: 扩展三条硬约束校验字段 + 置信度(0-1)
 */
import { useCallback, useEffect, useState } from 'react';
import { Button, Collapse, ConfigProvider, Progress, Tag, Timeline } from 'antd';

/* ─── Props ─── */
interface AgentActionLogProps {
  limit?: number;
  agentId?: string;
}

/* ─── Sprint 2 — 结构化决策留痕类型 ─── */
export interface ActionLogItem {
  id: string;
  time: string;
  agent: string;
  agentColor: string;
  actionType: string;
  inputSummary: string;
  reasoning: string;
  constraints: { margin: boolean; safety: boolean; experience: boolean };
  confidence: number;  // 0-1
  result: '已执行' | '已忽略' | '待确认';
}

/* ─── Sprint 1 — 行动日志数据结构 ─── */
interface ActionLogEntry {
  id: string;
  time: string;
  agent: string;
  agentId: string;
  actionType: string;
  summary: string;
  inputContext: string;
  reasoning: string;
  confidence: number;
  result: string;
}

/* ─── Mock 数据 ─── */
const MOCK_ACTION_LOGS: ActionLogEntry[] = [
  {
    id: '1', time: '14:32:05', agent: '运营指挥官', agentId: 'tx-ops',
    actionType: '超时催单', summary: 'B01桌剁椒鱼头超时8分钟，自动触发催单通知',
    inputContext: '桌台B01，菜品：剁椒鱼头，下单时间14:24，当前时间14:32，超时阈值8分钟',
    reasoning: '检测到B01桌剁椒鱼头已超出标准出餐时间8分钟。根据历史数据，此菜品平均出餐时间为12分钟，当前已达20分钟。触发第一次自动催单，同时准备告知客人预计等待时间。',
    confidence: 94, result: '已执行',
  },
  {
    id: '2', time: '14:28:41', agent: '运营指挥官', agentId: 'tx-ops',
    actionType: 'AI叫号', summary: 'A07空台就绪，推荐叫A027号赵先生(4人)',
    inputContext: 'A07台状态：空闲，容纳4人；A027号：赵先生，4人桌，等待38分钟',
    reasoning: 'A07台(4人台)刚刚完成清台，A027号赵先生一行4人已等待38分钟，桌位需求完美匹配。综合等待时长、人数匹配度、台位就绪状态，建议立即叫号。',
    confidence: 91, result: '待确认',
  },
  {
    id: '3', time: '14:15:22', agent: '客户大脑', agentId: 'tx-growth',
    actionType: '会员识别', summary: 'D04桌识别钻石会员王总，建议推荐存酒续存',
    inputContext: '扫码入座：王先生，会员级别：钻石，累计消费：¥68,000，最近消费记录：存有2瓶茅台',
    reasoning: '识别到钻石会员王总到店，其存有2瓶茅台尚未取用。当前用餐场景适合推荐续存服务或预约下次用餐。钻石会员的存酒续存转化率历史达73%，建议主动推荐。',
    confidence: 98, result: '已执行',
  },
  {
    id: '4', time: '14:10:07', agent: '运营指挥官', agentId: 'tx-ops',
    actionType: '自动接单', summary: '美团外卖MT-5891自动接单，金额¥128',
    inputContext: '外卖平台：美团，订单号：MT-5891，金额：¥128，菜品3项，当前厨房负载：60%',
    reasoning: '当前厨房负载处于60%正常区间，历史同时段外卖处理能力充裕。订单菜品均为常规品，无特殊定制要求。自动接单并分配至区域厨房，预计出餐时间25分钟，符合平台配送时效要求。',
    confidence: 99, result: '已执行',
  },
  {
    id: '5', time: '13:58:33', agent: '供应链卫士', agentId: 'tx-supply',
    actionType: '沽清同步', summary: '椒盐皮皮虾库存仅剩2份，建议临时沽清',
    inputContext: '菜品：椒盐皮皮虾，当前库存：2份，今日已售：18份，预计剩余订单：3-4份',
    reasoning: '当前椒盐皮皮虾库存仅余2份，而今日剩余营业时间预计还会产生3-4份需求。为避免超卖导致客诉，建议立即执行沽清操作，同步更新所有点餐终端和外卖平台菜单状态。',
    confidence: 87, result: '待确认',
  },
  {
    id: '6', time: '13:45:18', agent: '收益优化师', agentId: 'tx-analytics',
    actionType: '定价建议', summary: '周末晚市人均消费低于目标，建议增加套餐曝光',
    inputContext: '当前人均消费：¥158，目标人均：¥180，差距：¥22；套餐命中率：32%',
    reasoning: '今日晚市截至目前人均消费¥158，低于周末目标¥180。分析显示，加单套餐在当前菜单展示中排名靠后，导致推荐命中率仅32%。建议将2-3人精品套餐调至POS点餐界面首屏。',
    confidence: 82, result: '已确认',
  },
  {
    id: '7', time: '13:30:55', agent: '菜品智能体', agentId: 'tx-menu',
    actionType: '排菜优化', summary: '今日特供：佛跳墙毛利率最高，建议加大推荐力度',
    inputContext: '今日特供菜品：佛跳墙，毛利率：72%，今日已售：8份，昨日同期：5份',
    reasoning: '佛跳墙今日毛利率达72%，远高于门店平均58%。今日已售8份，销售势头良好。建议服务员主动推荐，并在自助点餐界面置顶展示，目标今日销售量达15份。',
    confidence: 89, result: '已执行',
  },
  {
    id: '8', time: '13:22:10', agent: '经营分析师', agentId: 'tx-brain',
    actionType: '异常检测', summary: '午市翻台率较上周同期下降12%，触发经营异常预警',
    inputContext: '今日午市翻台率：1.8次，上周同期：2.05次，下降幅度：12.2%',
    reasoning: '今日午市翻台率1.8次低于上周同期2.05次，降幅12.2%超过预警阈值10%。结合天气（晴天）和无特殊活动因素，初步判断为桌位周转效率下降。建议管理层关注点单到出餐全流程时效。',
    confidence: 95, result: '已通知',
  },
  {
    id: '9', time: '12:55:44', agent: '客户大脑', agentId: 'tx-growth',
    actionType: '复购提醒', summary: 'VIP客户陈女士30天未到店，触发召回旅程',
    inputContext: '客户：陈女士，等级：金卡，上次到店：30天前，历史月均消费：¥420',
    reasoning: '陈女士为金卡会员，历史月均消费¥420，已30天未到店，超过该用户群体的平均回店周期23天。根据流失预测模型，当前流失风险得分78分(高风险)。触发标准召回旅程，发送专属8折优惠。',
    confidence: 76, result: '已执行',
  },
  {
    id: '10', time: '12:40:29', agent: '供应链卫士', agentId: 'tx-supply',
    actionType: '库存预警', summary: '生蚝库存低于安全阈值，建议今日下午补货',
    inputContext: '菜品：生蚝，当前库存：15只，安全阈值：20只，明日预订需求：约30只',
    reasoning: '生蚝当前库存15只，已低于安全阈值20只。结合明日预订情况（已有3桌包含生蚝菜品），预计明日需求约30只。建议今日下午联系供应商，采购30-40只以保障明日供应。',
    confidence: 93, result: '已确认',
  },
];

/* ─── Sprint 2 Mock 数据（含三条硬约束字段） ─── */
const SPRINT2_MOCK_LOGS: ActionLogItem[] = [
  {
    id: 's2-001', time: '14:32:05', agent: '折扣守护', agentColor: '#FF6B35',
    actionType: 'DISCOUNT.RISK_CHECK',
    inputSummary: '员工E-0023申请对订单#TXO-4421执行免单（¥488）',
    reasoning: '该员工本月已执行3次免单，超出阈值2次。单笔毛利将降至-¥58，违反毛利底线约束。建议拒绝并升级审批。',
    constraints: { margin: false, safety: true, experience: true },
    confidence: 0.97, result: '已执行',
  },
  {
    id: 's2-002', time: '14:28:17', agent: '客户大脑', agentColor: '#6D3EA8',
    actionType: 'MEMBER.INSIGHT_GENERATED',
    inputSummary: '会员M-00412（王总）开台，6人包间，历史消费¥48,600',
    reasoning: '王总偏好包间和清蒸系菜品，有国窖1573存酒余800ml。距上次到店16天，符合主动推荐存酒续存条件。',
    constraints: { margin: true, safety: true, experience: true },
    confidence: 0.91, result: '已执行',
  },
  {
    id: 's2-003', time: '14:15:44', agent: '出餐调度', agentColor: '#0F6E56',
    actionType: 'DISH.TIME_PREDICTED',
    inputSummary: '桌台A08下单蒜蓉蒸鲍鱼×2，当前厨房负载78%',
    reasoning: '当前厨房蒸台占用率高（78%），预计出餐时间从标准12分钟延长至18分钟。已向前台服务员推送预警。',
    constraints: { margin: true, safety: true, experience: true },
    confidence: 0.84, result: '已执行',
  },
  {
    id: 's2-004', time: '14:02:11', agent: '库存预警', agentColor: '#BA7517',
    actionType: 'INVENTORY.LOW_STOCK_ALERT',
    inputSummary: '皮皮虾库存降至2.3kg，低于安全库存线5kg',
    reasoning: '按当前消耗速率（约1.5kg/小时），预计1.5小时内耗尽。建议立即标记沽清并推送替代菜品「椒盐濑尿虾」。',
    constraints: { margin: true, safety: true, experience: true },
    confidence: 0.96, result: '已执行',
  },
  {
    id: 's2-005', time: '13:55:30', agent: '运营指挥官', agentColor: '#1677FF',
    actionType: 'OMNI.AUTO_ACCEPT',
    inputSummary: '美团平台新订单#MT-8812，金额¥156，预计出餐20分钟',
    reasoning: '当前处于午高峰期，autoAccept开关已启用。厨房负载65%，出餐可行性评估通过。自动接单并设置预计出餐时间25分钟。',
    constraints: { margin: true, safety: true, experience: true },
    confidence: 0.88, result: '已执行',
  },
  {
    id: 's2-006', time: '13:41:08', agent: '财务稽核', agentColor: '#722ed1',
    actionType: 'FINANCE.ANOMALY_DETECTED',
    inputSummary: '检测到桌台B12结账金额¥0，操作员E-0031',
    reasoning: '订单含5道菜，总额应为¥312。免单操作无审批记录，操作员权限不足。已冻结该操作并通知店长审批。',
    constraints: { margin: false, safety: true, experience: true },
    confidence: 0.99, result: '待确认',
  },
  {
    id: 's2-007', time: '13:28:55', agent: '食安合规', agentColor: '#ef4444',
    actionType: 'SAFETY.INGREDIENT_CHECK',
    inputSummary: '批次BAT-20260404-023草鱼库存，到期日2026-04-06',
    reasoning: '今日为到期日，该批次草鱼仍有8.2kg库存。已触发食安合规约束，自动阻止领用并发送处置提醒给采购主管。',
    constraints: { margin: true, safety: false, experience: true },
    confidence: 1.0, result: '已执行',
  },
  {
    id: 's2-008', time: '12:59:22', agent: '智能排菜', agentColor: '#13c2c2',
    actionType: 'MENU.FOUR_QUADRANT_UPDATED',
    inputSummary: '基于近7天销售数据，重新计算菜品四象限分类',
    reasoning: '蒜蓉粉丝扇贝近7天销量+23%，毛利率42%，晋升为「明星菜品」。水煮鱼销量下滑18%，毛利率仅28%，降级为「问题菜品」。',
    constraints: { margin: true, safety: true, experience: true },
    confidence: 0.87, result: '已执行',
  },
  {
    id: 's2-009', time: '12:44:10', agent: '客户大脑', agentColor: '#6D3EA8',
    actionType: 'MEMBER.CHURN_RISK',
    inputSummary: '会员M-00187（李女士），上次到店距今42天，历史消费频率15天/次',
    reasoning: '消费间隔已达历史均值2.8倍，判定为高流失风险。已触发私域运营Agent，自动生成专属回访优惠券并推送企业微信消息。',
    constraints: { margin: true, safety: true, experience: true },
    confidence: 0.82, result: '已执行',
  },
  {
    id: 's2-010', time: '11:30:00', agent: '折扣守护', agentColor: '#FF6B35',
    actionType: 'DISCOUNT.APPROVED',
    inputSummary: '店长M-Manager申请对VIP桌台#TXO-4398执行九折优惠（优惠¥44）',
    reasoning: '店长权限允许九折以内优惠。优惠后毛利率39.2%，高于毛利底线35%。客户为钻石会员，符合体验优化条件。批准执行。',
    constraints: { margin: true, safety: true, experience: true },
    confidence: 0.95, result: '已执行',
  },
];

function getResultColor(result: ActionLogItem['result']): string {
  switch (result) {
    case '已执行': return '#0F6E56';
    case '已忽略': return '#8A94A4';
    case '待确认': return '#BA7517';
  }
}

function getResultBg(result: ActionLogItem['result']): string {
  switch (result) {
    case '已执行': return 'rgba(15,110,86,.12)';
    case '已忽略': return 'rgba(138,148,164,.12)';
    case '待确认': return 'rgba(186,117,23,.12)';
  }
}

function ConstraintBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <Tag color={ok ? 'success' : 'error'} style={{ fontSize: 12, marginBottom: 4 }}>
      {ok ? '✓' : '✗'} {label}
    </Tag>
  );
}

/**
 * Sprint 2 default export — 结构化决策留痕面板
 * 使用 ActionLogItem 含三条硬约束字段 + 0-1 置信度
 */
export default function AgentActionLogV2({ limit, agentId }: AgentActionLogProps) {
  const [logs, setLogs] = useState<ActionLogItem[]>(
    limit ? SPRINT2_MOCK_LOGS.slice(0, limit) : SPRINT2_MOCK_LOGS
  );
  const [fetching, setFetching] = useState(false);

  const fetchLogs = useCallback(async () => {
    setFetching(true);
    const tenantId = localStorage.getItem('tx-tenant-id') || 'default';
    const params = new URLSearchParams({ limit: String(limit ?? 10) });
    if (agentId) params.set('agent_id', agentId);
    try {
      const res = await fetch(`/api/v1/agent-hub/log?${params}`, {
        headers: { 'X-Tenant-ID': tenantId },
      });
      const data = await res.json();
      if (data.ok && data.data.length > 0) setLogs(data.data);
    } catch { /* 保留 mock */ }
    finally { setFetching(false); }
  }, [agentId, limit]);

  useEffect(() => { fetchLogs(); }, [fetchLogs]);

  const handleRefresh = () => {
    fetchLogs();
  };

  const handleExportCsv = () => {
    const header = 'ID,时间,Agent,动作类型,毛利底线,食安合规,客户体验,置信度,结果\n';
    const rows = logs
      .map((l) =>
        [
          l.id, l.time, l.agent, l.actionType,
          l.constraints.margin ? '通过' : '未通过',
          l.constraints.safety ? '通过' : '未通过',
          l.constraints.experience ? '通过' : '未通过',
          `${(l.confidence * 100).toFixed(0)}%`,
          l.result,
        ].join(',')
      )
      .join('\n');
    const blob = new Blob([header + rows], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `agent-action-log-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#FF6B35' } }}>
      <div style={{ padding: '0 0 24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: '#2C2C2A' }}>🤖 Agent 决策留痕</div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button size="small" onClick={handleRefresh}>刷新</Button>
            <Button size="small" onClick={handleExportCsv}>导出 CSV</Button>
          </div>
        </div>
        <Timeline
          items={logs.map((item) => ({
            color: item.agentColor,
            children: (
              <Collapse
                ghost
                size="small"
                items={[{
                  key: item.id,
                  label: (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 12, color: '#8A94A4', minWidth: 56 }}>{item.time}</span>
                      <Tag style={{ fontSize: 12, fontWeight: 700, color: item.agentColor, border: `1px solid ${item.agentColor}44`, background: `${item.agentColor}12` }}>
                        {item.agent}
                      </Tag>
                      <span style={{ fontSize: 13, color: '#5F5E5A', flex: 1 }}>{item.actionType}</span>
                      <Tag style={{ fontSize: 11, color: getResultColor(item.result), background: getResultBg(item.result), border: 'none' }}>
                        {item.result}
                      </Tag>
                    </div>
                  ),
                  children: (
                    <div style={{ paddingLeft: 8 }}>
                      <div style={{ marginBottom: 10 }}>
                        <div style={{ fontSize: 11, color: '#8A94A4', fontWeight: 600, marginBottom: 4 }}>输入摘要</div>
                        <div style={{ fontSize: 13, color: '#374151', background: '#f9fafb', borderRadius: 6, padding: '8px 10px', lineHeight: 1.6 }}>
                          {item.inputSummary}
                        </div>
                      </div>
                      <div style={{ marginBottom: 10 }}>
                        <div style={{ fontSize: 11, color: '#8A94A4', fontWeight: 600, marginBottom: 4 }}>推理过程</div>
                        <div style={{ fontSize: 13, color: '#374151', background: 'rgba(109,62,168,.04)', borderRadius: 6, padding: '8px 10px', lineHeight: 1.6, borderLeft: '3px solid rgba(109,62,168,.3)' }}>
                          {item.reasoning}
                        </div>
                      </div>
                      <div style={{ marginBottom: 10 }}>
                        <div style={{ fontSize: 11, color: '#8A94A4', fontWeight: 600, marginBottom: 6 }}>三条硬约束校验</div>
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                          <ConstraintBadge ok={item.constraints.margin} label="毛利底线" />
                          <ConstraintBadge ok={item.constraints.safety} label="食安合规" />
                          <ConstraintBadge ok={item.constraints.experience} label="客户体验" />
                        </div>
                      </div>
                      <div>
                        <div style={{ fontSize: 11, color: '#8A94A4', fontWeight: 600, marginBottom: 6 }}>
                          决策置信度 {(item.confidence * 100).toFixed(0)}%
                        </div>
                        <Progress
                          percent={Math.round(item.confidence * 100)}
                          size="small"
                          strokeColor={item.confidence >= 0.9 ? '#0F6E56' : item.confidence >= 0.75 ? '#BA7517' : '#A32D2D'}
                          showInfo={false}
                        />
                      </div>
                    </div>
                  ),
                }]}
              />
            ),
          }))}
        />
      </div>
    </ConfigProvider>
  );
}

/* ─── 主组件 ─── */
export function AgentActionLog({ limit, agentId }: AgentActionLogProps) {
  // 过滤
  let logs = MOCK_ACTION_LOGS;
  if (agentId) {
    logs = logs.filter((l) => l.agentId === agentId);
  }
  if (limit) {
    logs = logs.slice(0, limit);
  }

  const handleRefresh = () => {
    // mock 刷新
    console.log('AgentActionLog: refresh triggered');
  };

  const handleExportCSV = () => {
    // mock 导出CSV
    const rows = ['时间,Agent,动作类型,摘要,置信度,结果'];
    logs.forEach((l) => {
      rows.push(`${l.time},${l.agent},${l.actionType},"${l.summary}",${l.confidence}%,${l.result}`);
    });
    const blob = new Blob([rows.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'agent_action_log.csv';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div>
      {/* 头部操作栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <span style={{ fontSize: 16, fontWeight: 700 }}>Agent 行动日志</span>
        <div style={{ display: 'flex', gap: 8 }}>
          <Button size="small" onClick={handleRefresh}>刷新</Button>
          <Button size="small" onClick={handleExportCSV}>导出CSV</Button>
        </div>
      </div>

      {/* Timeline */}
      <Timeline
        items={logs.map((log) => ({
          color: log.result === '待确认' ? 'orange' : log.result === '已执行' || log.result === '已确认' ? 'green' : 'blue',
          children: (
            <div style={{ marginBottom: 4 }}>
              <div style={{ fontSize: 12, color: '#999', marginBottom: 2 }}>
                {log.time} · <span style={{ color: '#1890ff' }}>{log.agent}</span> · {log.actionType}
              </div>
              <Collapse
                size="small"
                ghost
                items={[
                  {
                    key: log.id,
                    label: (
                      <span style={{ fontSize: 13, fontWeight: 600 }}>{log.summary}</span>
                    ),
                    children: (
                      <div style={{ padding: '8px 0', fontSize: 12 }}>
                        {/* 输入上下文 */}
                        <div style={{ marginBottom: 8 }}>
                          <div style={{ fontWeight: 600, color: '#555', marginBottom: 4 }}>输入上下文</div>
                          <div style={{ color: '#666', background: '#f9f9f9', padding: '6px 8px', borderRadius: 4 }}>
                            {log.inputContext}
                          </div>
                        </div>
                        {/* 推理摘要 */}
                        <div style={{ marginBottom: 8 }}>
                          <div style={{ fontWeight: 600, color: '#555', marginBottom: 4 }}>推理摘要</div>
                          <div style={{ color: '#666', background: '#f9f9f9', padding: '6px 8px', borderRadius: 4 }}>
                            {log.reasoning}
                          </div>
                        </div>
                        {/* 三条硬约束 */}
                        <div style={{ marginBottom: 8 }}>
                          <div style={{ fontWeight: 600, color: '#555', marginBottom: 4 }}>硬约束校验</div>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                            <div style={{ color: '#52c41a' }}>✓ 毛利底线 — 通过</div>
                            <div style={{ color: '#52c41a' }}>✓ 食安合规 — 通过</div>
                            <div style={{ color: '#52c41a' }}>✓ 客户体验 — 通过</div>
                          </div>
                        </div>
                        {/* 置信度 */}
                        <div>
                          <div style={{ fontWeight: 600, color: '#555', marginBottom: 4 }}>
                            置信度 {log.confidence}%
                          </div>
                          <Progress
                            percent={log.confidence}
                            strokeColor={log.confidence >= 90 ? '#52c41a' : '#faad14'}
                            size="small"
                            showInfo={false}
                          />
                        </div>
                      </div>
                    ),
                  },
                ]}
              />
            </div>
          ),
        }))}
      />
    </div>
  );
}
