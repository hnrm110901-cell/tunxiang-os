/**
 * HRHubOverviewPage — 人力中枢总览
 *
 * 功能：
 *  1. 顶部8个关键指标卡片（两行四列）
 *  2. 预警分布饼图 + 编制缺口
 *  3. 训练进度概览 + 即将到期
 *  4. 快捷导航入口（8个模块）
 *
 * API:
 *  GET /api/v1/alert-aggregation/hub-overview
 */

import { useEffect, useState } from 'react';
import { StatisticCard } from '@ant-design/pro-components';
import {
  Alert,
  Card,
  Col,
  Progress,
  Row,
  Space,
  Spin,
  Typography,
} from 'antd';
import {
  AlertOutlined,
  AuditOutlined,
  BookOutlined,
  DashboardOutlined,
  FileProtectOutlined,
  SafetyCertificateOutlined,
  TeamOutlined,
  ThunderboltOutlined,
  ToolOutlined,
  UserSwitchOutlined,
} from '@ant-design/icons';
import { Pie } from '@ant-design/charts';
import { useNavigate } from 'react-router-dom';
import { txFetchData } from '../../api/client';

const { Title, Text } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

interface HubOverview {
  alerts: { total_unresolved: number; critical: number; warning: number; info: number; resolution_rate: number };
  staffing: { total_templates: number; gap_stores: number };
  training: { in_progress: number; overdue: number; completed: number; completion_rate: number };
  certification: { total: number; pass_rate: number; expiring_soon: number };
  mentorship: { active: number; avg_score: number };
  readiness: { avg_score: number; red_stores: number; green_stores: number; yellow_stores: number };
  peak_guard: { upcoming: number; avg_coverage: number; low_coverage: number };
  coaching: { this_week: number; acceptance_rate: number; avg_lift: number };
}

// ─── 导航配置 ─────────────────────────────────────────────────────────────────

interface NavEntry {
  title: string;
  path: string;
  icon: React.ReactNode;
  metricKey: (d: HubOverview) => string;
}

const NAV_ITEMS: NavEntry[] = [
  { title: '编制管理', path: '/hr/staffing/templates', icon: <TeamOutlined />, metricKey: (d) => `${d.staffing.total_templates} 套模板` },
  { title: '编制分析', path: '/hr/staffing/analysis', icon: <DashboardOutlined />, metricKey: (d) => `${d.staffing.gap_stores} 门店缺编` },
  { title: 'DRI工单', path: '/hr/dri-workorders', icon: <ToolOutlined />, metricKey: (d) => `${d.alerts.total_unresolved} 未解决` },
  { title: '带教督导', path: '/hr/mentorship', icon: <UserSwitchOutlined />, metricKey: (d) => `${d.mentorship.active} 对活跃` },
  { title: '训练路径', path: '/hr/onboarding', icon: <BookOutlined />, metricKey: (d) => `${d.training.in_progress} 进行中` },
  { title: '岗位认证', path: '/hr/certifications', icon: <SafetyCertificateOutlined />, metricKey: (d) => `${d.certification.pass_rate}% 通过率` },
  { title: '营业就绪', path: '/hr/store-readiness', icon: <FileProtectOutlined />, metricKey: (d) => `${d.readiness.avg_score.toFixed(1)} 平均分` },
  { title: '高峰保障', path: '/hr/peak-guard', icon: <ThunderboltOutlined />, metricKey: (d) => `${d.peak_guard.avg_coverage}% 覆盖` },
];

// ─── 主组件 ───────────────────────────────────────────────────────────────────

export default function HRHubOverviewPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<HubOverview | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await txFetchData<HubOverview>('/api/v1/alert-aggregation/hub-overview');
        if (!cancelled && res) setData(res);
      } catch (err) {
        console.error('Failed to load hub overview', err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '60vh' }}>
        <Spin size="large" tip="加载中..." />
      </div>
    );
  }

  if (!data) {
    return <Alert type="error" message="加载失败" description="无法获取人力中枢概览数据，请刷新重试。" showIcon />;
  }

  // ─── 饼图数据 ──────────────────────────────────────────────────────────────

  const pieData = [
    { type: '严重', value: data.alerts.critical },
    { type: '警告', value: data.alerts.warning },
    { type: '信息', value: data.alerts.info },
  ].filter((d) => d.value > 0);

  const pieConfig = {
    data: pieData,
    angleField: 'value',
    colorField: 'type',
    color: ({ type }: { type: string }) => {
      const map: Record<string, string> = { '严重': '#A32D2D', '警告': '#BA7517', '信息': '#185FA5' };
      return map[type] || '#999';
    },
    radius: 0.85,
    innerRadius: 0.55,
    label: { type: 'inner', offset: '-30%', content: '{value}', style: { fontSize: 13, fontWeight: 600 } },
    legend: { position: 'bottom' as const },
    interactions: [{ type: 'element-active' }],
    height: 220,
  };

  // ─── 辅助 ──────────────────────────────────────────────────────────────────

  const dangerStyle = (val: number, threshold = 0): React.CSSProperties =>
    val > threshold ? { color: '#A32D2D' } : {};

  return (
    <div style={{ padding: 24 }}>
      <Title level={4} style={{ marginBottom: 20 }}>
        <AuditOutlined style={{ marginRight: 8 }} />
        人力中枢总览
      </Title>

      {/* ─── Section 1: 顶部指标卡片 ─────────────────────────────────────── */}
      <Row gutter={[16, 16]}>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '未解决预警',
              value: data.alerts.total_unresolved,
              valueStyle: dangerStyle(data.alerts.total_unresolved),
            }}
            style={{ borderRadius: 6 }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '培训中 / 逾期',
              value: data.training.in_progress,
              suffix: (
                <Text style={{ fontSize: 14, ...dangerStyle(data.training.overdue) }}>
                  / {data.training.overdue} 逾期
                </Text>
              ),
            }}
            style={{ borderRadius: 6 }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '认证通过率',
              value: data.certification.pass_rate,
              suffix: '%',
            }}
            style={{ borderRadius: 6 }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '活跃带教',
              value: data.mentorship.active,
              suffix: '对',
            }}
            style={{ borderRadius: 6 }}
          />
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 0 }}>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '门店平均就绪分',
              value: data.readiness.avg_score.toFixed(1),
            }}
            style={{ borderRadius: 6 }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '红灯门店数',
              value: data.readiness.red_stores,
              valueStyle: dangerStyle(data.readiness.red_stores),
            }}
            style={{ borderRadius: 6 }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '高峰覆盖度',
              value: data.peak_guard.avg_coverage,
              suffix: '%',
            }}
            style={{ borderRadius: 6 }}
          />
        </Col>
        <Col span={6}>
          <StatisticCard
            statistic={{
              title: '本周教练会话',
              value: data.coaching.this_week,
              suffix: '次',
            }}
            style={{ borderRadius: 6 }}
          />
        </Col>
      </Row>

      {/* ─── Section 2: 两列布局 ─────────────────────────────────────────── */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        {/* 左列 */}
        <Col span={12}>
          <Card title="预警分布" bodyStyle={{ padding: 16 }} style={{ borderRadius: 6, marginBottom: 16 }}>
            {pieData.length > 0 ? (
              <Pie {...pieConfig} />
            ) : (
              <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>暂无预警</div>
            )}
          </Card>

          <Card title="编制缺口" bodyStyle={{ padding: 16 }} style={{ borderRadius: 6 }}>
            {data.staffing.gap_stores > 0 ? (
              <Alert
                type="warning"
                showIcon
                icon={<AlertOutlined />}
                message={
                  <Text strong>
                    {data.staffing.gap_stores} 个门店存在缺编
                  </Text>
                }
                description={`共 ${data.staffing.total_templates} 套编制模板在用`}
              />
            ) : (
              <Text type="success">所有门店编制满足，无缺编</Text>
            )}
          </Card>
        </Col>

        {/* 右列 */}
        <Col span={12}>
          <Card title="训练进度概览" bodyStyle={{ padding: 16 }} style={{ borderRadius: 6, marginBottom: 16 }}>
            <Space direction="vertical" style={{ width: '100%' }} size={16}>
              <div>
                <Text>培训完成率</Text>
                <Progress
                  percent={data.training.completion_rate}
                  strokeColor="#0F6E56"
                  format={(p) => `${p}%`}
                />
              </div>
              <div>
                <Text>认证通过率</Text>
                <Progress
                  percent={data.certification.pass_rate}
                  strokeColor="#185FA5"
                  format={(p) => `${p}%`}
                />
              </div>
              <div>
                <Text>建议采纳率</Text>
                <Progress
                  percent={data.coaching.acceptance_rate}
                  strokeColor="#BA7517"
                  format={(p) => `${p}%`}
                />
              </div>
            </Space>
          </Card>

          <Card title="即将到期" bodyStyle={{ padding: 16 }} style={{ borderRadius: 6 }}>
            <Space direction="vertical" size={12}>
              <div>
                <SafetyCertificateOutlined style={{ marginRight: 8, color: '#BA7517' }} />
                <Text>认证即将过期：</Text>
                <Text strong style={dangerStyle(data.certification.expiring_soon)}>
                  {data.certification.expiring_soon} 条
                </Text>
              </div>
              <div>
                <ThunderboltOutlined style={{ marginRight: 8, color: '#A32D2D' }} />
                <Text>高峰覆盖不足：</Text>
                <Text strong style={dangerStyle(data.peak_guard.low_coverage)}>
                  {data.peak_guard.low_coverage} 个门店
                </Text>
              </div>
            </Space>
          </Card>
        </Col>
      </Row>

      {/* ─── Section 3: 快捷入口 ─────────────────────────────────────────── */}
      <Title level={5} style={{ marginTop: 24, marginBottom: 12 }}>快捷入口</Title>
      <Row gutter={[16, 16]}>
        {NAV_ITEMS.map((item) => (
          <Col span={6} key={item.path}>
            <Card
              hoverable
              bodyStyle={{ padding: 16, textAlign: 'center' }}
              style={{ borderRadius: 6, cursor: 'pointer', transition: 'box-shadow 0.2s' }}
              onClick={() => navigate(item.path)}
            >
              <div style={{ fontSize: 28, color: '#FF6B35', marginBottom: 8 }}>
                {item.icon}
              </div>
              <Text strong>{item.title}</Text>
              <br />
              <Text type="secondary" style={{ fontSize: 12 }}>
                {item.metricKey(data)}
              </Text>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  );
}
