/**
 * AgentSettingsPage — 权限与授权
 * Sprint 4: tx-agent Agent权限管理
 */
import React from 'react';
import {
  ConfigProvider, Alert, Tabs, Tag, Card, Switch, Space, Button,
} from 'antd';
import type { TabsProps } from 'antd';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';

// ---- 类型 ----
interface AuthRow {
  key: number;
  agentName: string;
  permLevel: '只读' | '建议' | '执行';
  maxDiscount: string;
  autoThreshold: string;
  lastChanged: string;
}

interface LogRow {
  key: number;
  time: string;
  agent: string;
  actionType: string;
  summary: string;
  reviewStatus: '已确认' | '待确认' | '已拒绝';
  result: string;
}

// ---- Mock 数据 ----
const authData: AuthRow[] = [
  { key: 1, agentName: '运营指挥官 Pro', permLevel: '建议', maxDiscount: '25%', autoThreshold: '¥0',      lastChanged: '2026-04-01' },
  { key: 2, agentName: '菜品智能体',     permLevel: '建议', maxDiscount: '20%', autoThreshold: '¥0',      lastChanged: '2026-04-01' },
  { key: 3, agentName: '客户大脑',       permLevel: '只读', maxDiscount: '15%', autoThreshold: '¥0',      lastChanged: '2026-03-28' },
  { key: 4, agentName: '收益优化师',     permLevel: '建议', maxDiscount: '30%', autoThreshold: '¥500',    lastChanged: '2026-04-03' },
  { key: 5, agentName: '供应链卫士',     permLevel: '建议', maxDiscount: '0%',  autoThreshold: '¥2,000',  lastChanged: '2026-04-02' },
  { key: 6, agentName: '经营分析师',     permLevel: '只读', maxDiscount: '0%',  autoThreshold: '¥0',      lastChanged: '2026-03-25' },
];

const permLevelColor: Record<AuthRow['permLevel'], string> = {
  '只读': 'blue',
  '建议': 'orange',
  '执行': 'red',
};

const authColumns: ProColumns<AuthRow>[] = [
  { title: 'Agent名称',    dataIndex: 'agentName',     width: 130 },
  {
    title: '当前权限级别', dataIndex: 'permLevel', width: 100,
    render: (_, r) => <Tag color={permLevelColor[r.permLevel]}>{r.permLevel}</Tag>,
  },
  { title: '最大折扣授权', dataIndex: 'maxDiscount',   width: 100 },
  { title: '自主执行阈值', dataIndex: 'autoThreshold', width: 110 },
  { title: '上次变更',     dataIndex: 'lastChanged',   width: 110 },
  {
    title: '操作', valueType: 'option', width: 70,
    render: () => [
      <a key="edit" onClick={() => alert('编辑权限配置')}>编辑</a>,
    ],
  },
];

const logData: LogRow[] = [
  { key: 1,  time: '2026-04-07 10:30', agent: '供应链卫士',   actionType: '采购建议', summary: '建议采购濑尿虾15kg，参考价¥42/kg',         reviewStatus: '已确认', result: '成功'  },
  { key: 2,  time: '2026-04-07 10:15', agent: '收益优化师',   actionType: '定价建议', summary: '建议龙虾价格上调¥15，提升毛利率3%',         reviewStatus: '已确认', result: '成功'  },
  { key: 3,  time: '2026-04-07 09:45', agent: '运营指挥官Pro', actionType: '异常预警', summary: '南山旗舰午市营业额低于同期38%',             reviewStatus: '待确认', result: '处理中' },
  { key: 4,  time: '2026-04-07 09:30', agent: '菜品智能体',   actionType: '沽清预警', summary: '鲍鱼预计今日14:30沽清，建议推替代菜品',     reviewStatus: '已确认', result: '成功'  },
  { key: 5,  time: '2026-04-07 09:00', agent: '客户大脑',     actionType: '流失预警', summary: '识别高价值客户37人，30天未复购',             reviewStatus: '待确认', result: '待处理' },
  { key: 6,  time: '2026-04-06 21:00', agent: '收益优化师',   actionType: '促销建议', summary: '建议下午茶时段濑尿虾8折促销提升翻台',       reviewStatus: '已拒绝', result: '已拒绝' },
  { key: 7,  time: '2026-04-06 18:30', agent: '供应链卫士',   actionType: '临期预警', summary: '鲍鱼A批剩余2天到期，建议优先出餐',           reviewStatus: '已确认', result: '成功'  },
  { key: 8,  time: '2026-04-06 14:00', agent: '菜品智能体',   actionType: '健康度分析', summary: '发现3道菜品毛利率低于30%，建议调整成本', reviewStatus: '已确认', result: '成功'  },
  { key: 9,  time: '2026-04-06 11:30', agent: '运营指挥官Pro', actionType: '排班建议', summary: '晚市预计客流超预期，建议增加1名厨师',       reviewStatus: '已拒绝', result: '已拒绝' },
  { key: 10, time: '2026-04-06 09:00', agent: '经营分析师',   actionType: '报表生成', summary: '自动生成昨日经营简报，关键指标已推送',       reviewStatus: '已确认', result: '成功'  },
];

const reviewColor: Record<LogRow['reviewStatus'], string> = {
  '已确认': 'green',
  '待确认': 'orange',
  '已拒绝': 'red',
};

const logColumns: ProColumns<LogRow>[] = [
  { title: '时间',   dataIndex: 'time',         width: 140 },
  { title: 'Agent', dataIndex: 'agent',         width: 120 },
  { title: '操作类型', dataIndex: 'actionType', width: 90 },
  { title: '内容摘要', dataIndex: 'summary',    flex: 1 },
  {
    title: '人工审核', dataIndex: 'reviewStatus', width: 90,
    render: (_, r) => <Tag color={reviewColor[r.reviewStatus]}>{r.reviewStatus}</Tag>,
  },
  { title: '结果', dataIndex: 'result', width: 70 },
];

const securityRules = [
  {
    title: '折扣上限保护',
    desc: '任何Agent不得授权超过35%的折扣',
    defaultChecked: true,
  },
  {
    title: '食安合规强制',
    desc: '食材到期前48小时自动触发预警，不可绕过',
    defaultChecked: true,
  },
  {
    title: '客户体验保护',
    desc: '差评率超过15%时暂停相关自动化操作',
    defaultChecked: true,
  },
];

// ---- Tabs ----
const tabItems: TabsProps['items'] = [
  {
    key: '1',
    label: '授权管理',
    children: (
      <ProTable<AuthRow>
        columns={authColumns}
        dataSource={authData}
        rowKey="key"
        search={false}
        pagination={false}
        toolBarRender={false}
        size="small"
      />
    ),
  },
  {
    key: '2',
    label: '操作日志',
    children: (
      <ProTable<LogRow>
        columns={logColumns}
        dataSource={logData}
        rowKey="key"
        search={false}
        pagination={{ pageSize: 10 }}
        toolBarRender={false}
        size="small"
      />
    ),
  },
  {
    key: '3',
    label: '安全规则',
    children: (
      <Space direction="vertical" style={{ width: '100%' }} size={16}>
        {securityRules.map((rule) => (
          <Card key={rule.title} size="small">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>{rule.title}</div>
                <div style={{ fontSize: 12, color: '#666' }}>{rule.desc}</div>
              </div>
              <Switch defaultChecked={rule.defaultChecked} />
            </div>
          </Card>
        ))}
      </Space>
    ),
  },
];

// ---- 页面组件 ----
export const AgentSettingsPage: React.FC = () => {
  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#FF6B35' } }}>
      <div style={{ padding: 24, background: '#f5f5f5', minHeight: '100vh' }}>
        {/* 顶部说明 */}
        <Alert
          type="warning"
          showIcon
          message="Phase 1 · 建议模式 — 所有 Agent 操作需人工确认。Phase 2（自主执行）将在完成30天安全运行后解锁"
          style={{ marginBottom: 16 }}
        />

        {/* 主体 Tabs */}
        <Card>
          <Tabs items={tabItems} defaultActiveKey="1" />
        </Card>
      </div>
    </ConfigProvider>
  );
};
