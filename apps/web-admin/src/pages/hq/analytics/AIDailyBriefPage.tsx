/**
 * AIDailyBriefPage — AI 经营简报
 * Sprint 3: 经营分析师 tx-brain 生成的每日简报
 */
import { useState, useEffect } from 'react';
import {
  ConfigProvider, Row, Col, Card, Statistic, Alert, Collapse, List, Button, Timeline, Tag, Space,
} from 'antd';
import {
  CheckCircleOutlined, WarningOutlined, ExclamationCircleOutlined,
} from '@ant-design/icons';

// ---- Mock 数据 ----
const HIGHLIGHTS = [
  '南山旗舰店今日营业额 ¥28,640，超目标 13%，同比上月大幅提升',
  '会员复购率本周升至 38%，较上周 +3.2pct，处历史高位',
  '蒜蓉蒸鲍鱼今日售罄率 95%，热门菜品带动整体客单价提升 8%',
];

const CONCERNS = [
  { text: '福田中心店今日营业额 ¥19,820，环比昨日下降 6.1%，连续两日低于目标', path: '/hq/ops/store-analysis' },
  { text: '濑尿虾库存预计明日见底，当前剩余量仅够 1 日营业，建议立即补货', path: '/hq/supply/inventory-intel' },
  { text: '南山旗舰店午市翻台率 1.8 次，低于目标 2.2 次，需检查排班安排', path: '/hq/ops/dashboard' },
];

const RISKS = [
  { text: '某蔬菜供应商应付账款逾期 7 天，金额 ¥23,400，可能影响下周供货稳定性' },
  { text: '南山旗舰店食安证明将于 3 天后到期（2026-04-10），请尽快更新' },
];

const AGENT_ACTIONS = [
  { time: '09:00', label: '自动生成今日经营简报并推送至管理层企微' },
  { time: '09:15', label: '向福田店长发送翻台率预警，附带排班优化建议' },
  { time: '10:30', label: '触发濑尿虾补货工单，发送至采购负责人审批' },
  { time: '11:00', label: '安排供应商账款逾期提醒，抄送财务总监' },
  { time: '14:00', label: '计划发送南山旗舰店下午茶促销推送（待审批）' },
];

const BRIEF_HISTORY = [
  { date: '2026-04-06', label: '周日', score: '良好' },
  { date: '2026-04-05', label: '周六', score: '优秀' },
  { date: '2026-04-04', label: '周五', score: '良好' },
  { date: '2026-04-03', label: '周四', score: '需关注' },
  { date: '2026-04-02', label: '周三', score: '良好' },
];

const scoreColor = (s: string) => {
  if (s === '优秀') return 'green';
  if (s === '良好') return 'blue';
  if (s === '需关注') return 'orange';
  return 'red';
};

// ---- 主组件 ----
export const AIDailyBriefPage = () => {
  const [briefData, setBriefData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const tenantId = localStorage.getItem('tx-tenant-id') || 'default';
    fetch('/api/v1/daily-review/today', {
      headers: { 'X-Tenant-ID': tenantId },
    })
      .then(r => r.json())
      .then(res => {
        if (res.ok && res.data) setBriefData(res.data);
      })
      .catch(() => {/* 保留 mock */})
      .finally(() => setLoading(false));
  }, []);

  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#FF6B35' } }}>
      <div style={{ padding: 24 }}>
        {/* 顶部 4 个 Statistic 卡片 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card>
              <Statistic
                title="今日总营业额"
                value={63890}
                prefix="¥"
                valueStyle={{ color: '#FF6B35', fontWeight: 700 }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="AI 预测达成率"
                value={87.3}
                suffix="%"
                valueStyle={{ color: '#0F6E56', fontWeight: 700 }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="需关注门店数"
                value={2}
                suffix="家"
                valueStyle={{ color: '#BA7517', fontWeight: 700 }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="今日待处理 Agent 行动"
                value={5}
                suffix="条"
                valueStyle={{ color: '#185FA5', fontWeight: 700 }}
              />
            </Card>
          </Col>
        </Row>

        {/* 中部主体 */}
        <Row gutter={16}>
          {/* 左侧: 简报内容 */}
          <Col span={16}>
            <Card title="今日 AI 经营简报" style={{ marginBottom: 16 }}>
              <Alert
                type="info"
                banner
                message="由 tx-brain 经营分析师 生成 · 2026-04-07 09:00"
                style={{ marginBottom: 16 }}
              />
              <Collapse defaultActiveKey={['highlights']}>
                <Collapse.Panel
                  key="highlights"
                  header={
                    <span style={{ fontWeight: 600 }}>
                      <CheckCircleOutlined style={{ color: '#0F6E56', marginRight: 6 }} />
                      业绩亮点
                    </span>
                  }
                >
                  <List
                    dataSource={HIGHLIGHTS}
                    renderItem={(item) => (
                      <List.Item>
                        <Space>
                          <CheckCircleOutlined style={{ color: '#0F6E56' }} />
                          <span>{item}</span>
                        </Space>
                      </List.Item>
                    )}
                  />
                </Collapse.Panel>
                <Collapse.Panel
                  key="concerns"
                  header={
                    <span style={{ fontWeight: 600 }}>
                      <WarningOutlined style={{ color: '#BA7517', marginRight: 6 }} />
                      需关注事项
                    </span>
                  }
                >
                  <List
                    dataSource={CONCERNS}
                    renderItem={(item) => (
                      <List.Item
                        actions={[
                          <Button key="view" size="small" onClick={() => {}}>查看</Button>,
                        ]}
                      >
                        <Space>
                          <WarningOutlined style={{ color: '#BA7517' }} />
                          <span>{item.text}</span>
                        </Space>
                      </List.Item>
                    )}
                  />
                </Collapse.Panel>
                <Collapse.Panel
                  key="risks"
                  header={
                    <span style={{ fontWeight: 600 }}>
                      <ExclamationCircleOutlined style={{ color: '#A32D2D', marginRight: 6 }} />
                      紧急风险
                    </span>
                  }
                >
                  <List
                    dataSource={RISKS}
                    renderItem={(item) => (
                      <List.Item
                        actions={[
                          <Button
                            key="handle"
                            size="small"
                            type="primary"
                            danger
                          >
                            立即处理
                          </Button>,
                        ]}
                      >
                        <Space>
                          <ExclamationCircleOutlined style={{ color: '#A32D2D' }} />
                          <span>{item.text}</span>
                        </Space>
                      </List.Item>
                    )}
                  />
                </Collapse.Panel>
              </Collapse>
            </Card>
          </Col>

          {/* 右侧: Agent 行动 + 历史简报 */}
          <Col span={8}>
            <Card title="Agent 行动建议" style={{ marginBottom: 16 }}>
              <Timeline
                items={AGENT_ACTIONS.map((a) => ({
                  color: '#FF6B35',
                  children: (
                    <div>
                      <div style={{ fontSize: 11, color: '#888', marginBottom: 2 }}>{a.time}</div>
                      <div style={{ fontSize: 13 }}>{a.label}</div>
                    </div>
                  ),
                }))}
              />
            </Card>

            <Card title="本周简报历史">
              <List
                dataSource={BRIEF_HISTORY}
                renderItem={(item) => (
                  <List.Item
                    actions={[
                      <Button key="view" size="small" type="link">查看</Button>,
                    ]}
                  >
                    <Space>
                      <span style={{ color: '#666', fontSize: 12 }}>{item.date}</span>
                      <span style={{ fontSize: 13 }}>{item.label}</span>
                      <Tag color={scoreColor(item.score)}>{item.score}</Tag>
                    </Space>
                  </List.Item>
                )}
              />
            </Card>
          </Col>
        </Row>

        {/* 底部操作 */}
        <Row style={{ marginTop: 16 }}>
          <Col>
            <Space>
              <Button icon={<span>📧</span>}>发送至邮件</Button>
              <Button icon={<span>📥</span>}>导出 PDF</Button>
            </Space>
          </Col>
        </Row>
      </div>
    </ConfigProvider>
  );
};
