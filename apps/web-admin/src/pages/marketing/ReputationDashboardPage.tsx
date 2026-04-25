/**
 * ReputationDashboardPage — AI舆情监控与危机预警仪表盘
 * 六大模块：预警级别卡片 / SLA合规仪表 / 预警列表 / 预警详情 / SLA报告 / 平台分布
 * API: tx-intel :8011
 */
import { useRef, useState, useEffect, useCallback } from 'react';
import {
  ProTable,
  ProColumns,
  ActionType,
} from '@ant-design/pro-components';
import {
  Badge,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Input,
  message,
  Modal,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import {
  AlertOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  ExclamationCircleOutlined,
  RiseOutlined,
  SendOutlined,
  TeamOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { txFetchData } from '../../api';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

// ─── 类型 ──────────────────────────────────

interface DashboardData {
  total_alerts: number;
  by_severity: Record<string, number>;
  by_platform: Record<string, number>;
  by_status: Record<string, number>;
  avg_response_time_sec: number | null;
  sla_compliance_rate: number | null;
  sla_met_count: number;
  sla_total: number;
  days: number;
}

interface SLAReportItem {
  store_id: string | null;
  total_alerts: number;
  sla_met_count: number;
  sla_missed_count: number;
  compliance_rate: number;
  avg_response_sec: number | null;
}

interface AlertItem {
  id: string;
  store_id: string | null;
  platform: string;
  alert_type: string;
  severity: string;
  summary: string;
  response_status: string;
  response_time_sec: number | null;
  sla_met: boolean | null;
  assigned_to: string | null;
  created_at: string | null;
  updated_at: string | null;
}

interface AlertDetail extends AlertItem {
  trigger_mention_ids: string[];
  trigger_data: Record<string, unknown>;
  recommended_actions: { action: string; priority: string; template: string }[];
  response_text: string | null;
  responded_at: string | null;
  sla_target_sec: number | null;
  escalated_to: string | null;
  escalated_at: string | null;
  resolved_at: string | null;
  resolution_note: string | null;
}

// ─── 常量 ──────────────────────────────────

const SEVERITY_CONFIG: Record<string, { color: string; label: string; tagColor: string }> = {
  critical: { color: '#ff4d4f', label: '严重', tagColor: 'red' },
  high: { color: '#ff7a45', label: '高', tagColor: 'orange' },
  medium: { color: '#faad14', label: '中', tagColor: 'gold' },
  low: { color: '#52c41a', label: '低', tagColor: 'green' },
};

const STATUS_CONFIG: Record<string, { label: string; tagColor: string }> = {
  pending: { label: '待处理', tagColor: 'red' },
  acknowledged: { label: '已确认', tagColor: 'orange' },
  responding: { label: '处理中', tagColor: 'blue' },
  escalated: { label: '已升级', tagColor: 'purple' },
  resolved: { label: '已解决', tagColor: 'green' },
  dismissed: { label: '已驳回', tagColor: 'default' },
};

const PLATFORM_LABELS: Record<string, string> = {
  weibo: '微博',
  xiaohongshu: '小红书',
  douyin: '抖音',
  dianping: '大众点评',
  meituan: '美团',
  wechat: '微信',
  google: 'Google',
};

const ALERT_TYPE_LABELS: Record<string, string> = {
  negative_spike: '负面激增',
  crisis: '舆情危机',
  trending_negative: '负面趋势',
  rating_drop: '评分下降',
  competitor_attack: '竞品攻击',
};

// ─── 辅助函数 ──────────────────────────────

function formatTimeSec(sec: number | null): string {
  if (sec === null || sec === undefined) return '-';
  if (sec < 60) return `${sec}秒`;
  if (sec < 3600) return `${Math.floor(sec / 60)}分${sec % 60}秒`;
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return `${h}时${m}分`;
}

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return '-';
  const diff = Date.now() - new Date(dateStr).getTime();
  const min = Math.floor(diff / 60000);
  if (min < 60) return `${min}分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}小时前`;
  return `${Math.floor(hr / 24)}天前`;
}

// ─── 组件 ──────────────────────────────────

export default function ReputationDashboardPage() {
  const actionRef = useRef<ActionType>();
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [slaReport, setSLAReport] = useState<SLAReportItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedAlert, setSelectedAlert] = useState<AlertDetail | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [respondText, setRespondText] = useState('');
  const [respondLoading, setRespondLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('alerts');

  // 加载仪表盘
  const loadDashboard = useCallback(async () => {
    setLoading(true);
    try {
      const res = await txFetchData('/api/v1/intel/reputation/dashboard?days=30');
      setDashboard(res.dashboard);
      setSLAReport(res.sla_report || []);
    } catch {
      message.error('加载仪表盘失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  // 加载预警详情
  const loadAlertDetail = async (alertId: string) => {
    try {
      const res = await txFetchData(`/api/v1/intel/reputation/alerts/${alertId}`);
      setSelectedAlert(res);
      setDrawerOpen(true);
      setRespondText('');
    } catch {
      message.error('加载预警详情失败');
    }
  };

  // 回应预警
  const handleRespond = async () => {
    if (!selectedAlert || !respondText.trim()) return;
    setRespondLoading(true);
    try {
      await txFetchData(`/api/v1/intel/reputation/alerts/${selectedAlert.id}/respond`, {
        method: 'POST',
        body: JSON.stringify({ response_text: respondText }),
      });
      message.success('回应已提交');
      setDrawerOpen(false);
      actionRef.current?.reload();
      loadDashboard();
    } catch {
      message.error('回应提交失败');
    } finally {
      setRespondLoading(false);
    }
  };

  // 升级预警
  const handleEscalate = async () => {
    if (!selectedAlert) return;
    Modal.confirm({
      title: '确认升级预警？',
      content: '升级后将通知品牌PR团队负责人',
      onOk: async () => {
        try {
          await txFetchData(`/api/v1/intel/reputation/alerts/${selectedAlert.id}/escalate`, {
            method: 'POST',
            body: JSON.stringify({ escalated_to: '00000000-0000-0000-0000-000000000000' }),
          });
          message.success('预警已升级');
          setDrawerOpen(false);
          actionRef.current?.reload();
          loadDashboard();
        } catch {
          message.error('升级失败');
        }
      },
    });
  };

  // 解决预警
  const handleResolve = async () => {
    if (!selectedAlert) return;
    Modal.confirm({
      title: '确认解决预警？',
      content: '标记此预警为已解决',
      onOk: async () => {
        try {
          await txFetchData(`/api/v1/intel/reputation/alerts/${selectedAlert.id}/resolve`, {
            method: 'POST',
            body: JSON.stringify({ resolution_note: respondText || '已处理完毕' }),
          });
          message.success('预警已解决');
          setDrawerOpen(false);
          actionRef.current?.reload();
          loadDashboard();
        } catch {
          message.error('解决失败');
        }
      },
    });
  };

  // ─── 预警列表列配置 ─────────────────────

  const columns: ProColumns<AlertItem>[] = [
    {
      title: '平台',
      dataIndex: 'platform',
      width: 100,
      render: (_: unknown, row: AlertItem) => (
        <Tag>{PLATFORM_LABELS[row.platform] || row.platform}</Tag>
      ),
      valueEnum: Object.fromEntries(
        Object.entries(PLATFORM_LABELS).map(([k, v]) => [k, { text: v }]),
      ),
    },
    {
      title: '级别',
      dataIndex: 'severity',
      width: 80,
      render: (_: unknown, row: AlertItem) => {
        const cfg = SEVERITY_CONFIG[row.severity];
        return cfg ? <Tag color={cfg.tagColor}>{cfg.label}</Tag> : row.severity;
      },
      valueEnum: Object.fromEntries(
        Object.entries(SEVERITY_CONFIG).map(([k, v]) => [k, { text: v.label }]),
      ),
    },
    {
      title: '类型',
      dataIndex: 'alert_type',
      width: 110,
      render: (_: unknown, row: AlertItem) => (
        <Text>{ALERT_TYPE_LABELS[row.alert_type] || row.alert_type}</Text>
      ),
    },
    {
      title: '摘要',
      dataIndex: 'summary',
      ellipsis: true,
    },
    {
      title: '状态',
      dataIndex: 'response_status',
      width: 90,
      render: (_: unknown, row: AlertItem) => {
        const cfg = STATUS_CONFIG[row.response_status];
        return cfg ? <Tag color={cfg.tagColor}>{cfg.label}</Tag> : row.response_status;
      },
      valueEnum: Object.fromEntries(
        Object.entries(STATUS_CONFIG).map(([k, v]) => [k, { text: v.label }]),
      ),
    },
    {
      title: 'SLA',
      dataIndex: 'sla_met',
      width: 70,
      render: (_: unknown, row: AlertItem) => {
        if (row.sla_met === null) return <Text type="secondary">-</Text>;
        return row.sla_met
          ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
          : <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />;
      },
    },
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 100,
      render: (_: unknown, row: AlertItem) => (
        <Text type="secondary">{timeAgo(row.created_at)}</Text>
      ),
      sorter: true,
      hideInSearch: true,
    },
    {
      title: '操作',
      width: 80,
      hideInSearch: true,
      render: (_: unknown, row: AlertItem) => (
        <Button type="link" size="small" onClick={() => loadAlertDetail(row.id)}>
          详情
        </Button>
      ),
    },
  ];

  // ─── SLA报告列 ─────────────────────

  const slaColumns = [
    { title: '门店ID', dataIndex: 'store_id', key: 'store_id',
      render: (v: string | null) => v ? v.slice(0, 8) + '...' : '品牌级别' },
    { title: '总预警', dataIndex: 'total_alerts', key: 'total_alerts' },
    { title: '达标', dataIndex: 'sla_met_count', key: 'sla_met_count' },
    { title: '未达标', dataIndex: 'sla_missed_count', key: 'sla_missed_count',
      render: (v: number) => v > 0 ? <Text type="danger">{v}</Text> : v },
    { title: '合规率', dataIndex: 'compliance_rate', key: 'compliance_rate',
      render: (v: number) => (
        <Progress
          percent={v}
          size="small"
          status={v >= 80 ? 'success' : v >= 60 ? 'normal' : 'exception'}
          format={(pct) => `${pct}%`}
        />
      ),
    },
    { title: '平均响应', dataIndex: 'avg_response_sec', key: 'avg_response_sec',
      render: (v: number | null) => formatTimeSec(v) },
  ];

  // ─── 渲染 ──────────────────────────────

  return (
    <div style={{ padding: 24 }}>
      <Title level={3}>
        <AlertOutlined /> 舆情监控与危机预警
      </Title>

      {/* 预警级别卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        {(['critical', 'high', 'medium', 'low'] as const).map((sev) => {
          const cfg = SEVERITY_CONFIG[sev];
          const count = dashboard?.by_severity?.[sev] || 0;
          return (
            <Col span={6} key={sev}>
              <Card hoverable>
                <Statistic
                  title={`${cfg.label}级别预警`}
                  value={count}
                  valueStyle={{ color: cfg.color, fontSize: 32 }}
                  prefix={sev === 'critical' ? <WarningOutlined /> : <AlertOutlined />}
                />
              </Card>
            </Col>
          );
        })}
      </Row>

      {/* SLA合规 + 平均响应时间 + 平台分布 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={8}>
          <Card title="SLA合规率（30min目标）" loading={loading}>
            <div style={{ textAlign: 'center' }}>
              <Progress
                type="dashboard"
                percent={dashboard?.sla_compliance_rate ?? 0}
                format={(pct) => `${pct}%`}
                strokeColor={
                  (dashboard?.sla_compliance_rate ?? 0) >= 80 ? '#52c41a'
                  : (dashboard?.sla_compliance_rate ?? 0) >= 60 ? '#faad14'
                  : '#ff4d4f'
                }
                size={160}
              />
              <div style={{ marginTop: 12 }}>
                <Text type="secondary">
                  达标 {dashboard?.sla_met_count ?? 0} / 总计 {dashboard?.sla_total ?? 0}
                </Text>
              </div>
            </div>
          </Card>
        </Col>
        <Col span={8}>
          <Card title="响应统计" loading={loading}>
            <Space direction="vertical" size="large" style={{ width: '100%' }}>
              <Statistic
                title="平均响应时间"
                value={formatTimeSec(dashboard?.avg_response_time_sec ?? null)}
                prefix={<ClockCircleOutlined />}
              />
              <Statistic
                title="总预警数（30天）"
                value={dashboard?.total_alerts ?? 0}
                prefix={<AlertOutlined />}
              />
            </Space>
          </Card>
        </Col>
        <Col span={8}>
          <Card title="平台分布" loading={loading}>
            {dashboard?.by_platform && Object.entries(dashboard.by_platform).length > 0 ? (
              <Space direction="vertical" style={{ width: '100%' }}>
                {Object.entries(dashboard.by_platform)
                  .sort(([, a], [, b]) => b - a)
                  .map(([platform, count]) => (
                    <div key={platform} style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <Text>{PLATFORM_LABELS[platform] || platform}</Text>
                      <Badge count={count} showZero style={{ backgroundColor: '#1890ff' }} />
                    </div>
                  ))}
              </Space>
            ) : (
              <Text type="secondary">暂无数据</Text>
            )}
          </Card>
        </Col>
      </Row>

      {/* 主标签页 */}
      <Card>
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: 'alerts',
              label: '预警列表',
              children: (
                <ProTable<AlertItem>
                  actionRef={actionRef}
                  rowKey="id"
                  columns={columns}
                  request={async (params) => {
                    const qs = new URLSearchParams();
                    qs.set('page', String(params.current || 1));
                    qs.set('size', String(params.pageSize || 20));
                    if (params.response_status) qs.set('status', params.response_status);
                    if (params.severity) qs.set('severity', params.severity);
                    if (params.platform) qs.set('platform', params.platform);
                    const res = await txFetchData(
                      `/api/v1/intel/reputation/alerts?${qs.toString()}`,
                    );
                    return { data: res.items, total: res.total, success: true };
                  }}
                  pagination={{ defaultPageSize: 20 }}
                  search={{ labelWidth: 'auto' }}
                  dateFormatter="string"
                  headerTitle="舆情预警"
                  toolBarRender={() => [
                    <Button
                      key="refresh"
                      type="primary"
                      onClick={() => {
                        actionRef.current?.reload();
                        loadDashboard();
                      }}
                    >
                      刷新数据
                    </Button>,
                  ]}
                />
              ),
            },
            {
              key: 'sla',
              label: 'SLA报告',
              children: (
                <Table
                  dataSource={slaReport}
                  columns={slaColumns}
                  rowKey="store_id"
                  pagination={false}
                  locale={{ emptyText: '暂无SLA数据' }}
                />
              ),
            },
          ]}
        />
      </Card>

      {/* 预警详情抽屉 */}
      <Drawer
        title="预警详情"
        placement="right"
        width={600}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        extra={
          <Space>
            {selectedAlert?.response_status === 'pending' || selectedAlert?.response_status === 'acknowledged' ? (
              <>
                <Button
                  icon={<TeamOutlined />}
                  onClick={handleEscalate}
                >
                  升级
                </Button>
                <Button
                  type="primary"
                  icon={<CheckCircleOutlined />}
                  onClick={handleResolve}
                >
                  解决
                </Button>
              </>
            ) : null}
          </Space>
        }
      >
        {selectedAlert && (
          <Space direction="vertical" size="large" style={{ width: '100%' }}>
            {/* 基本信息 */}
            <Descriptions column={2} bordered size="small">
              <Descriptions.Item label="平台">
                {PLATFORM_LABELS[selectedAlert.platform] || selectedAlert.platform}
              </Descriptions.Item>
              <Descriptions.Item label="级别">
                <Tag color={SEVERITY_CONFIG[selectedAlert.severity]?.tagColor}>
                  {SEVERITY_CONFIG[selectedAlert.severity]?.label || selectedAlert.severity}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="类型">
                {ALERT_TYPE_LABELS[selectedAlert.alert_type] || selectedAlert.alert_type}
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={STATUS_CONFIG[selectedAlert.response_status]?.tagColor}>
                  {STATUS_CONFIG[selectedAlert.response_status]?.label || selectedAlert.response_status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="创建时间" span={2}>
                {selectedAlert.created_at || '-'}
              </Descriptions.Item>
              {selectedAlert.response_time_sec !== null && (
                <Descriptions.Item label="响应时间" span={2}>
                  {formatTimeSec(selectedAlert.response_time_sec)}
                  {selectedAlert.sla_met !== null && (
                    selectedAlert.sla_met
                      ? <Tag color="green" style={{ marginLeft: 8 }}>SLA达标</Tag>
                      : <Tag color="red" style={{ marginLeft: 8 }}>SLA未达标</Tag>
                  )}
                </Descriptions.Item>
              )}
            </Descriptions>

            {/* AI摘要 */}
            <Card title="AI摘要" size="small">
              <Paragraph>{selectedAlert.summary}</Paragraph>
            </Card>

            {/* 建议动作 */}
            {selectedAlert.recommended_actions?.length > 0 && (
              <Card title="建议动作" size="small">
                {selectedAlert.recommended_actions.map((act, idx) => (
                  <div key={idx} style={{ marginBottom: 8 }}>
                    <Tag color={
                      act.priority === 'critical' ? 'red'
                      : act.priority === 'high' ? 'orange'
                      : act.priority === 'medium' ? 'gold'
                      : 'blue'
                    }>
                      {act.priority}
                    </Tag>
                    <Text>{act.action}</Text>
                  </div>
                ))}
              </Card>
            )}

            {/* 触发数据 */}
            {selectedAlert.trigger_data && Object.keys(selectedAlert.trigger_data).length > 0 && (
              <Card title="触发数据" size="small">
                <Descriptions column={1} size="small">
                  {Object.entries(selectedAlert.trigger_data).map(([k, v]) => (
                    <Descriptions.Item key={k} label={k}>
                      {String(v)}
                    </Descriptions.Item>
                  ))}
                </Descriptions>
              </Card>
            )}

            {/* 已有回应 */}
            {selectedAlert.response_text && (
              <Card title="已回应内容" size="small">
                <Paragraph>{selectedAlert.response_text}</Paragraph>
              </Card>
            )}

            {/* 回应输入 */}
            {(selectedAlert.response_status === 'pending' ||
              selectedAlert.response_status === 'acknowledged') && (
              <Card title="提交回应" size="small">
                <TextArea
                  rows={4}
                  value={respondText}
                  onChange={(e) => setRespondText(e.target.value)}
                  placeholder="输入回应内容..."
                />
                <Button
                  type="primary"
                  icon={<SendOutlined />}
                  style={{ marginTop: 12 }}
                  loading={respondLoading}
                  disabled={!respondText.trim()}
                  onClick={handleRespond}
                >
                  提交回应
                </Button>
              </Card>
            )}

            {/* 解决备注 */}
            {selectedAlert.resolution_note && (
              <Card title="解决备注" size="small">
                <Paragraph>{selectedAlert.resolution_note}</Paragraph>
                <Text type="secondary">
                  解决时间: {selectedAlert.resolved_at || '-'}
                </Text>
              </Card>
            )}
          </Space>
        )}
      </Drawer>
    </div>
  );
}
