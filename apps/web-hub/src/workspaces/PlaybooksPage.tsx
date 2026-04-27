/**
 * Playbooks 剧本库页面
 *
 * 6个预置Playbook卡片网格 + 筛选 + 点击展开详情面板
 */
import { useState } from 'react';

const C = {
  bg: '#0A1418', surface: '#0E1E24', surface2: '#132932', surface3: '#1A3540',
  border: '#1A3540', border2: '#23485a',
  text: '#E6EDF1', text2: '#94A8B3', text3: '#647985',
  orange: '#FF6B2C', green: '#22C55E', yellow: '#F59E0B', red: '#EF4444', blue: '#3B82F6', purple: '#A855F7',
};

// ── 类型 ──

type Category = '客户成功' | '运维' | '事件响应' | '迁移';

interface PlaybookStep {
  name: string;
  description: string;
  timeout: string;
  fallback: string;
}

interface ExecutionRecord {
  time: string;
  target: string;
  status: 'success' | 'failed' | 'running';
  duration: string;
}

interface Playbook {
  id: string;
  title: string;
  category: Category;
  description: string;
  trigger: string;
  steps: PlaybookStep[];
  execCount: number;
  successRate: number;
  avgDuration: string;
  version: string;
  owner: string;
  createdAt: string;
  recentExecutions: ExecutionRecord[];
  sliHistory: number[];
}

// ── Mock 数据 ──

const PLAYBOOKS: Playbook[] = [
  {
    id: 'pb-1',
    title: '新客户Onboarding',
    category: '客户成功',
    description: '新签约客户从合同确认到首月回访的全流程自动化编排，确保客户顺利上线。',
    trigger: '新客户签约',
    steps: [
      { name: '签约确认', description: '确认合同签署完成，创建客户档案', timeout: '1天', fallback: '通知销售跟进' },
      { name: '实施启动', description: '分配CSM，创建实施项目', timeout: '2天', fallback: '升级至实施经理' },
      { name: '数据迁移', description: '启动数据迁移五段式流程', timeout: '5天', fallback: '切换手动迁移模式' },
      { name: '培训排期', description: '安排门店人员培训计划', timeout: '3天', fallback: '提供线上培训替代' },
      { name: '首周跟进', description: '上线首周每日巡检数据质量', timeout: '7天', fallback: '派驻现场支持' },
      { name: '首月回访', description: '月度回访收集反馈，评估健康分', timeout: '30天', fallback: '启动紧急护航' },
    ],
    execCount: 23,
    successRate: 91,
    avgDuration: '18天',
    version: 'v2.3',
    owner: '客户成功团队',
    createdAt: '2025-08-15',
    recentExecutions: [
      { time: '2026-04-20 10:30', target: '尚宫厨', status: 'success', duration: '16天' },
      { time: '2026-04-12 09:00', target: '最黔线', status: 'success', duration: '19天' },
      { time: '2026-03-28 14:15', target: '味蜀吾', status: 'failed', duration: '22天' },
      { time: '2026-03-15 11:00', target: '渝是乎', status: 'success', duration: '15天' },
      { time: '2026-03-01 08:45', target: '蜀大侠', status: 'success', duration: '17天' },
      { time: '2026-02-18 10:00', target: '大龙燚', status: 'success', duration: '20天' },
      { time: '2026-02-05 09:30', target: '小龙坎', status: 'success', duration: '14天' },
      { time: '2026-01-20 13:00', target: '谭鸭血', status: 'success', duration: '18天' },
      { time: '2026-01-08 10:15', target: '楠火锅', status: 'failed', duration: '25天' },
      { time: '2025-12-25 11:30', target: '巴奴', status: 'success', duration: '16天' },
    ],
    sliHistory: [88, 90, 85, 92, 91, 95, 89, 93, 90, 88, 91, 94],
  },
  {
    id: 'pb-2',
    title: '首营月护航',
    category: '客户成功',
    description: '门店首次上线后30天内的关键节点跟进，确保客户平稳度过适应期。',
    trigger: '门店首次上线后30天',
    steps: [
      { name: 'D1问候', description: '发送上线祝贺，确认系统运行正常', timeout: '1天', fallback: '电话回访' },
      { name: 'D3检查', description: '检查数据录入完整度和系统使用率', timeout: '1天', fallback: '安排远程指导' },
      { name: 'D7回访', description: '首周回访，收集使用问题和建议', timeout: '2天', fallback: '派驻现场支持' },
      { name: 'D14数据审查', description: '审查两周运营数据，生成健康报告', timeout: '2天', fallback: '紧急问题升级' },
      { name: 'D30总结', description: '月度总结，制定优化计划', timeout: '3天', fallback: '启动续航计划' },
    ],
    execCount: 18,
    successRate: 88,
    avgDuration: '30天',
    version: 'v1.8',
    owner: '客户成功团队',
    createdAt: '2025-09-20',
    recentExecutions: [
      { time: '2026-04-18 09:00', target: '尚宫厨-旗舰店', status: 'running', duration: '进行中' },
      { time: '2026-04-01 10:00', target: '最黔线-总店', status: 'success', duration: '30天' },
      { time: '2026-03-20 08:30', target: '味蜀吾-高新店', status: 'success', duration: '28天' },
      { time: '2026-03-05 09:15', target: '渝是乎-天心店', status: 'failed', duration: '30天' },
      { time: '2026-02-15 11:00', target: '蜀大侠-梅溪湖', status: 'success', duration: '29天' },
      { time: '2026-02-01 10:30', target: '大龙燚-五一店', status: 'success', duration: '31天' },
      { time: '2026-01-18 09:45', target: '小龙坎-河西店', status: 'success', duration: '27天' },
      { time: '2026-01-05 14:00', target: '谭鸭血-星沙店', status: 'success', duration: '30天' },
      { time: '2025-12-20 08:00', target: '楠火锅-开福店', status: 'failed', duration: '30天' },
      { time: '2025-12-05 10:00', target: '巴奴-岳麓店', status: 'success', duration: '28天' },
    ],
    sliHistory: [85, 88, 82, 90, 87, 92, 86, 89, 88, 85, 90, 91],
  },
  {
    id: 'pb-3',
    title: '季度健康检查',
    category: '客户成功',
    description: '每季度自动触发的客户健康度全面检查，健康分低于70时紧急触发。',
    trigger: '每季度自动 / 健康分<70时紧急触发',
    steps: [
      { name: '数据采集', description: '自动采集客户使用数据和关键指标', timeout: '1天', fallback: '手动数据导出' },
      { name: '健康评估', description: 'AI模型计算健康分并识别风险因子', timeout: '2小时', fallback: '人工评估' },
      { name: '报告生成', description: '生成可视化健康报告', timeout: '1小时', fallback: '模板报告' },
      { name: '客户沟通', description: '与客户分享报告并讨论改善方向', timeout: '3天', fallback: '邮件发送报告' },
      { name: '改善计划', description: '制定下季度改善目标和行动计划', timeout: '5天', fallback: '使用标准改善模板' },
    ],
    execCount: 45,
    successRate: 95,
    avgDuration: '7天',
    version: 'v3.1',
    owner: '客户成功团队',
    createdAt: '2025-06-01',
    recentExecutions: [
      { time: '2026-04-15 08:00', target: '全部客户-Q2', status: 'success', duration: '6天' },
      { time: '2026-04-10 10:00', target: '尚宫厨(紧急)', status: 'success', duration: '3天' },
      { time: '2026-03-25 09:00', target: '味蜀吾(紧急)', status: 'success', duration: '4天' },
      { time: '2026-01-15 08:00', target: '全部客户-Q1', status: 'success', duration: '7天' },
      { time: '2025-12-20 10:30', target: '最黔线(紧急)', status: 'success', duration: '2天' },
      { time: '2025-10-15 08:00', target: '全部客户-Q4', status: 'success', duration: '8天' },
      { time: '2025-10-05 09:00', target: '渝是乎(紧急)', status: 'failed', duration: '5天' },
      { time: '2025-07-15 08:00', target: '全部客户-Q3', status: 'success', duration: '6天' },
      { time: '2025-07-02 11:00', target: '蜀大侠(紧急)', status: 'success', duration: '3天' },
      { time: '2025-04-15 08:00', target: '全部客户-Q2', status: 'success', duration: '7天' },
    ],
    sliHistory: [92, 94, 93, 96, 95, 97, 94, 96, 95, 93, 95, 98],
  },
  {
    id: 'pb-4',
    title: '续约前提醒(90/60/30天)',
    category: '客户成功',
    description: '合同到期前90/60/30天分阶段推进续约流程，降低客户流失率。',
    trigger: '续约日前90/60/30天',
    steps: [
      { name: '通知CSM', description: '自动通知责任CSM启动续约流程', timeout: '1天', fallback: '升级至CSM主管' },
      { name: '准备方案', description: '生成客户价值报告和续约方案', timeout: '5天', fallback: '使用标准续约模板' },
      { name: '客户拜访', description: '安排面谈讨论续约条件', timeout: '10天', fallback: '线上会议替代' },
      { name: '报价', description: '发送正式报价单', timeout: '5天', fallback: '申请特批价格' },
      { name: '签约', description: '完成合同签署', timeout: '15天', fallback: '启动挽留流程' },
    ],
    execCount: 12,
    successRate: 83,
    avgDuration: '45天',
    version: 'v1.5',
    owner: '客户成功团队',
    createdAt: '2025-10-10',
    recentExecutions: [
      { time: '2026-04-10 09:00', target: '最黔线', status: 'running', duration: '进行中' },
      { time: '2026-03-20 10:00', target: '尚宫厨', status: 'running', duration: '进行中' },
      { time: '2026-02-15 08:30', target: '味蜀吾', status: 'success', duration: '42天' },
      { time: '2026-01-10 09:00', target: '渝是乎', status: 'success', duration: '38天' },
      { time: '2025-12-05 10:00', target: '蜀大侠', status: 'failed', duration: '55天' },
      { time: '2025-11-01 08:00', target: '大龙燚', status: 'success', duration: '40天' },
      { time: '2025-10-15 09:30', target: '小龙坎', status: 'success', duration: '50天' },
      { time: '2025-09-20 10:00', target: '谭鸭血', status: 'success', duration: '35天' },
      { time: '2025-08-10 11:00', target: '楠火锅', status: 'success', duration: '48天' },
      { time: '2025-07-05 09:00', target: '巴奴', status: 'failed', duration: '60天' },
    ],
    sliHistory: [80, 82, 78, 85, 83, 88, 80, 85, 83, 79, 84, 86],
  },
  {
    id: 'pb-5',
    title: 'P0事件自动响应',
    category: '事件响应',
    description: 'SLO违约、健康分骤降或多节点离线时自动触发的紧急响应流程。',
    trigger: 'SLO违约 / 健康分骤降 / 多节点离线',
    steps: [
      { name: '自动声明Incident', description: '创建Incident工单，设置P0优先级', timeout: '30秒', fallback: '人工创建工单' },
      { name: 'On-call通知', description: '通知值班工程师和相关负责人', timeout: '2分钟', fallback: '电话升级' },
      { name: '自动诊断', description: 'Agent自动收集日志和指标分析根因', timeout: '5分钟', fallback: '人工排查' },
      { name: '建议方案', description: 'AI生成修复建议并评估影响范围', timeout: '3分钟', fallback: '使用预案库' },
      { name: '执行/回滚', description: '确认后自动执行修复或回滚', timeout: '10分钟', fallback: '手动操作' },
    ],
    execCount: 7,
    successRate: 100,
    avgDuration: '18分钟',
    version: 'v2.0',
    owner: 'SRE团队',
    createdAt: '2025-11-01',
    recentExecutions: [
      { time: '2026-04-26 07:45', target: 'mcp-server', status: 'running', duration: '进行中' },
      { time: '2026-04-15 03:20', target: 'tx-supply', status: 'success', duration: '12分钟' },
      { time: '2026-03-28 22:10', target: 'TX-MAC-007', status: 'success', duration: '8分钟' },
      { time: '2026-03-10 14:55', target: 'tx-trade', status: 'success', duration: '22分钟' },
      { time: '2026-02-20 01:30', target: 'TX-MAC-003', status: 'success', duration: '15分钟' },
      { time: '2026-01-15 18:45', target: 'tx-member', status: 'success', duration: '20分钟' },
      { time: '2025-12-28 09:00', target: '全节点', status: 'success', duration: '25分钟' },
      { time: '2025-12-10 06:15', target: 'tx-analytics', status: 'success', duration: '10分钟' },
      { time: '2025-11-25 23:40', target: 'TX-MAC-005', status: 'success', duration: '18分钟' },
      { time: '2025-11-15 04:00', target: 'tx-trade', status: 'success', duration: '14分钟' },
    ],
    sliHistory: [100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100],
  },
  {
    id: 'pb-6',
    title: '数据迁移五段式',
    category: '迁移',
    description: '从旧系统迁移数据到屯象OS的标准五阶段流程，确保数据完整性和业务连续性。',
    trigger: '创建迁移项目时',
    steps: [
      { name: '映射', description: '建立旧系统字段与屯象OS Ontology的映射关系', timeout: '3天', fallback: '人工补全映射' },
      { name: '历史回放', description: '将历史数据按时间顺序回放写入', timeout: '5天', fallback: '分批次导入' },
      { name: '增量追平', description: '实时同步增量数据至双系统一致', timeout: '3天', fallback: '加大同步频率' },
      { name: '双跑对账', description: '双系统并行运行，自动对账核实', timeout: '7天', fallback: '延长双跑周期' },
      { name: '切流', description: '确认无差异后切换流量到屯象OS', timeout: '1天', fallback: '立即回切旧系统' },
    ],
    execCount: 5,
    successRate: 80,
    avgDuration: '14天',
    version: 'v1.2',
    owner: '实施团队',
    createdAt: '2025-07-20',
    recentExecutions: [
      { time: '2026-04-05 09:00', target: '尚宫厨-品智POS', status: 'success', duration: '12天' },
      { time: '2026-03-01 10:00', target: '最黔线-天财', status: 'success', duration: '15天' },
      { time: '2026-01-20 08:30', target: '味蜀吾-奥琦玮', status: 'failed', duration: '18天' },
      { time: '2025-11-10 09:00', target: '渝是乎-客如云', status: 'success', duration: '13天' },
      { time: '2025-09-05 10:00', target: '蜀大侠-二维火', status: 'success', duration: '11天' },
      { time: '2025-08-01 08:00', target: '测试环境', status: 'success', duration: '8天' },
      { time: '2025-07-25 09:00', target: '开发环境', status: 'success', duration: '5天' },
      { time: '2025-07-22 10:00', target: 'Demo数据', status: 'success', duration: '3天' },
      { time: '2025-07-21 14:00', target: '单表测试', status: 'success', duration: '1天' },
      { time: '2025-07-20 16:00', target: '冒烟测试', status: 'success', duration: '2小时' },
    ],
    sliHistory: [75, 78, 80, 82, 80, 85, 78, 82, 80, 76, 82, 84],
  },
];

const CATEGORIES: { key: string; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: '客户成功', label: '客户成功' },
  { key: '运维', label: '运维' },
  { key: '事件响应', label: '事件响应' },
  { key: '迁移', label: '迁移' },
];

const CATEGORY_COLOR: Record<Category, string> = {
  '客户成功': C.blue,
  '运维': C.yellow,
  '事件响应': C.red,
  '迁移': C.purple,
};

const STATUS_COLOR: Record<string, string> = {
  success: C.green,
  failed: C.red,
  running: C.yellow,
};

const STATUS_LABEL: Record<string, string> = {
  success: '成功',
  failed: '失败',
  running: '运行中',
};

// ── 组件 ──

function StepFlow({ steps }: { steps: PlaybookStep[] }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 0, overflow: 'hidden', padding: '8px 0' }}>
      {steps.map((step, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', flexShrink: 0 }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
            <div style={{
              width: 10, height: 10, borderRadius: '50%',
              background: C.orange,
              border: `2px solid ${C.orange}`,
              flexShrink: 0,
            }} />
            <div style={{ fontSize: 10, color: C.text3, whiteSpace: 'nowrap', maxWidth: 60, overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {step.name}
            </div>
          </div>
          {i < steps.length - 1 && (
            <div style={{ width: 20, height: 2, background: C.border2, flexShrink: 0, marginBottom: 16 }} />
          )}
        </div>
      ))}
    </div>
  );
}

function SliChart({ data }: { data: number[] }) {
  const max = Math.max(...data, 100);
  const barWidth = 18;
  const height = 80;
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height, padding: '4px 0' }}>
      {data.map((v, i) => {
        const h = (v / max) * (height - 16);
        const color = v >= 90 ? C.green : v >= 80 ? C.yellow : C.red;
        return (
          <div key={i} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
            <div style={{ fontSize: 9, color: C.text3 }}>{v}%</div>
            <div style={{
              width: barWidth, height: h, borderRadius: 3,
              background: color, opacity: 0.8,
              transition: 'height 0.3s',
            }} />
          </div>
        );
      })}
    </div>
  );
}

function DetailPanel({ playbook, onClose }: { playbook: Playbook; onClose: () => void }) {
  return (
    <div style={{
      position: 'fixed', top: 0, right: 0, bottom: 0,
      width: 520, background: C.surface, borderLeft: `1px solid ${C.border}`,
      zIndex: 300, display: 'flex', flexDirection: 'column',
      boxShadow: '-8px 0 32px rgba(0,0,0,0.5)',
      overflow: 'hidden',
    }}>
      {/* 遮罩 */}
      <div
        style={{ position: 'fixed', top: 0, left: 0, right: 520, bottom: 0, background: 'rgba(0,0,0,0.3)', zIndex: 299 }}
        onClick={onClose}
      />

      {/* 头部 */}
      <div style={{ padding: '20px 24px 16px', borderBottom: `1px solid ${C.border}`, flexShrink: 0, position: 'relative', zIndex: 301 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 700, color: C.text, marginBottom: 6 }}>{playbook.title}</div>
            <div style={{ display: 'flex', gap: 8, fontSize: 12, color: C.text3 }}>
              <span style={{
                padding: '2px 8px', borderRadius: 4,
                background: CATEGORY_COLOR[playbook.category] + '22',
                color: CATEGORY_COLOR[playbook.category], fontWeight: 600,
              }}>
                {playbook.category}
              </span>
              <span>{playbook.version}</span>
              <span>|</span>
              <span>{playbook.owner}</span>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'none', border: 'none', color: C.text3, fontSize: 20,
              cursor: 'pointer', padding: '0 4px', lineHeight: 1,
            }}
          >
            x
          </button>
        </div>
        <div style={{ fontSize: 13, color: C.text2, marginTop: 10 }}>{playbook.description}</div>
        <div style={{ fontSize: 12, color: C.text3, marginTop: 6 }}>
          创建于 {playbook.createdAt} | 触发条件：{playbook.trigger}
        </div>
      </div>

      {/* 可滚动内容 */}
      <div style={{ flex: 1, overflow: 'auto', padding: '16px 24px 24px', position: 'relative', zIndex: 301 }}>
        {/* 完整步骤列表 */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>步骤详情</div>
          {playbook.steps.map((step, i) => (
            <div key={i} style={{
              padding: '12px 14px', marginBottom: 8, borderRadius: 8,
              background: C.surface2, border: `1px solid ${C.border}`,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                <span style={{
                  width: 22, height: 22, borderRadius: '50%', background: C.orange + '22',
                  color: C.orange, fontSize: 11, fontWeight: 700,
                  display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                }}>
                  {i + 1}
                </span>
                <span style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{step.name}</span>
              </div>
              <div style={{ fontSize: 12, color: C.text2, marginLeft: 30, marginBottom: 4 }}>{step.description}</div>
              <div style={{ fontSize: 11, color: C.text3, marginLeft: 30, display: 'flex', gap: 12 }}>
                <span>超时：{step.timeout}</span>
                <span>回退：{step.fallback}</span>
              </div>
            </div>
          ))}
        </div>

        {/* 最近10次执行历史 */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>最近执行记录</div>
          <div style={{ borderRadius: 8, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
            <div style={{
              display: 'grid', gridTemplateColumns: '1fr 1fr 70px 80px',
              padding: '8px 12px', background: C.surface3, fontSize: 11, color: C.text3, fontWeight: 600,
            }}>
              <span>时间</span><span>目标</span><span>状态</span><span>耗时</span>
            </div>
            {playbook.recentExecutions.map((exec, i) => (
              <div key={i} style={{
                display: 'grid', gridTemplateColumns: '1fr 1fr 70px 80px',
                padding: '8px 12px', fontSize: 12, color: C.text2,
                borderTop: `1px solid ${C.border}`,
              }}>
                <span>{exec.time}</span>
                <span style={{ color: C.text }}>{exec.target}</span>
                <span style={{
                  color: STATUS_COLOR[exec.status], fontWeight: 600,
                }}>
                  {STATUS_LABEL[exec.status]}
                </span>
                <span>{exec.duration}</span>
              </div>
            ))}
          </div>
        </div>

        {/* SLI达成率趋势 */}
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.text, marginBottom: 12 }}>SLI达成率趋势（最近12次）</div>
          <div style={{ background: C.surface2, borderRadius: 8, padding: 16, border: `1px solid ${C.border}` }}>
            <SliChart data={playbook.sliHistory} />
          </div>
        </div>
      </div>
    </div>
  );
}

// ── 主页面 ──

export function PlaybooksPage() {
  const [filter, setFilter] = useState('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const filtered = filter === 'all' ? PLAYBOOKS : PLAYBOOKS.filter(p => p.category === filter);
  const selectedPlaybook = selectedId ? PLAYBOOKS.find(p => p.id === selectedId) : null;

  return (
    <div style={{ color: C.text, padding: 24, height: '100%', overflow: 'auto' }}>
      {/* 标题行 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
          <span style={{ fontSize: 22, fontWeight: 700, color: C.text }}>Playbooks 剧本库</span>
          <span style={{ fontSize: 13, color: C.text3 }}>{filtered.length} 个剧本</span>
        </div>
      </div>

      {/* 筛选 chips */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 24 }}>
        {CATEGORIES.map(cat => {
          const active = filter === cat.key;
          return (
            <button
              key={cat.key}
              onClick={() => setFilter(cat.key)}
              style={{
                padding: '6px 14px', borderRadius: 6, fontSize: 13,
                fontWeight: active ? 600 : 400,
                color: active ? C.orange : C.text2,
                background: active ? 'rgba(255,107,44,0.12)' : C.surface2,
                border: `1px solid ${active ? C.orange + '44' : C.border}`,
                cursor: 'pointer', transition: 'all 0.15s',
              }}
            >
              {cat.label}
            </button>
          );
        })}
      </div>

      {/* 卡片网格 */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gap: 16,
      }}>
        {filtered.map(pb => (
          <div
            key={pb.id}
            onClick={() => setSelectedId(pb.id)}
            style={{
              background: C.surface, borderRadius: 10, padding: 18,
              border: `1px solid ${C.border}`, cursor: 'pointer',
              transition: 'border-color 0.15s, transform 0.15s',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.borderColor = C.border2;
              e.currentTarget.style.transform = 'translateY(-2px)';
            }}
            onMouseLeave={e => {
              e.currentTarget.style.borderColor = C.border;
              e.currentTarget.style.transform = 'translateY(0)';
            }}
          >
            {/* 标题 + 类别 */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
              <div style={{ fontSize: 15, fontWeight: 700, color: C.text }}>{pb.title}</div>
              <span style={{
                padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600,
                background: CATEGORY_COLOR[pb.category] + '22',
                color: CATEGORY_COLOR[pb.category], whiteSpace: 'nowrap', flexShrink: 0,
              }}>
                {pb.category}
              </span>
            </div>

            {/* 描述 */}
            <div style={{
              fontSize: 12, color: C.text2, marginBottom: 10, lineHeight: 1.5,
              display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' as const,
              overflow: 'hidden',
            }}>
              {pb.description}
            </div>

            {/* 触发条件 */}
            <div style={{ fontSize: 11, color: C.text3, marginBottom: 10 }}>
              <span style={{ color: C.text3, fontWeight: 600 }}>触发：</span>{pb.trigger}
            </div>

            {/* 步骤流程 */}
            <StepFlow steps={pb.steps} />

            {/* 统计 */}
            <div style={{
              display: 'flex', gap: 16, marginTop: 10, paddingTop: 10,
              borderTop: `1px solid ${C.border}`, fontSize: 12,
            }}>
              <div>
                <span style={{ color: C.text3 }}>执行</span>{' '}
                <span style={{ color: C.text, fontWeight: 600 }}>{pb.execCount}次</span>
              </div>
              <div>
                <span style={{ color: C.text3 }}>成功率</span>{' '}
                <span style={{ color: pb.successRate >= 90 ? C.green : pb.successRate >= 80 ? C.yellow : C.red, fontWeight: 600 }}>
                  {pb.successRate}%
                </span>
              </div>
              <div>
                <span style={{ color: C.text3 }}>平均耗时</span>{' '}
                <span style={{ color: C.text2, fontWeight: 600 }}>{pb.avgDuration}</span>
              </div>
            </div>

            {/* 底部按钮 */}
            <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
              <button
                onClick={(e) => { e.stopPropagation(); setSelectedId(pb.id); }}
                style={{
                  flex: 1, padding: '7px 0', borderRadius: 6, fontSize: 12, fontWeight: 600,
                  color: C.orange, background: 'rgba(255,107,44,0.1)',
                  border: `1px solid ${C.orange}44`, cursor: 'pointer',
                  transition: 'background 0.15s',
                }}
                onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,107,44,0.2)'; }}
                onMouseLeave={e => { e.currentTarget.style.background = 'rgba(255,107,44,0.1)'; }}
              >
                查看详情
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); }}
                style={{
                  flex: 1, padding: '7px 0', borderRadius: 6, fontSize: 12, fontWeight: 600,
                  color: C.text2, background: C.surface2,
                  border: `1px solid ${C.border}`, cursor: 'pointer',
                  transition: 'background 0.15s',
                }}
                onMouseEnter={e => { e.currentTarget.style.background = C.surface3; }}
                onMouseLeave={e => { e.currentTarget.style.background = C.surface2; }}
              >
                手动触发
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* 详情面板 */}
      {selectedPlaybook && (
        <DetailPanel playbook={selectedPlaybook} onClose={() => setSelectedId(null)} />
      )}
    </div>
  );
}
