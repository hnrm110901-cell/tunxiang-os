/**
 * 全渠道会员 Golden ID 管理页 — Y-D9
 *
 * Tab 1：绑定概览 — 各渠道（美团/饿了么/抖音/微信）绑定数量卡片 + 柱状图
 * Tab 2：冲突解决 — 冲突列表 Table，可选择"保留哪个 ID"操作
 *
 * Admin 终端规范：Ant Design 5.x + ProComponents + @ant-design/charts
 * 主色 #FF6B35（通过 ConfigProvider 注入，不硬编码）
 */
import React, { useCallback, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  ConfigProvider,
  message,
  Modal,
  Row,
  Select,
  Statistic,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import {
  ActionType,
  ProColumns,
  ProTable,
} from '@ant-design/pro-components';
import { Column } from '@ant-design/charts';
import {
  BranchesOutlined,
  ExclamationCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons';

const { Title } = Typography;

// ── Design Token（屯象主题） ──────────────────────────────────────────────────

const TX_THEME = {
  token: {
    colorPrimary: '#FF6B35',
    colorSuccess: '#0F6E56',
    colorWarning: '#BA7517',
    colorError: '#A32D2D',
    colorInfo: '#185FA5',
    colorTextBase: '#2C2C2A',
    colorBgBase: '#FFFFFF',
    borderRadius: 6,
    fontSize: 14,
  },
  components: {
    Table: { headerBg: '#F8F7F5' },
  },
};

// ── 渠道显示配置 ───────────────────────────────────────────────────────────────

const CHANNEL_CONFIG: Record<string, { label: string; color: string }> = {
  meituan: { label: '美团外卖', color: '#FF6B35' },
  eleme:   { label: '饿了么',   color: '#00AEF3' },
  douyin:  { label: '抖音外卖', color: '#2C2C2A' },
  wechat:  { label: '微信',     color: '#07C160' },
};

// ── 类型定义 ──────────────────────────────────────────────────────────────────

interface ChannelStat {
  active_count: number;
  conflict_count: number;
  unbound_count: number;
  unique_customers: number;
}

interface StatsData {
  by_channel: Record<string, ChannelStat>;
  total_active_bindings: number;
  total_conflicts: number;
}

interface ConflictItem {
  id: string;
  customer_id: string;
  channel_type: string;
  channel_openid: string;
  phone_hash: string;
  created_at: string;
}

interface ResolveModalState {
  visible: boolean;
  conflict: ConflictItem | null;
}

// ── API 调用 ──────────────────────────────────────────────────────────────────

const TENANT_ID = localStorage.getItem('X-Tenant-ID') ?? 'default-tenant';
const HEADERS: Record<string, string> = {
  'Content-Type': 'application/json',
  'X-Tenant-ID': TENANT_ID,
};

async function fetchStats(): Promise<StatsData | null> {
  try {
    const res = await fetch('/api/v1/member/golden-id/stats', { headers: HEADERS });
    const json = await res.json();
    if (json.ok) return json.data as StatsData;
    return null;
  } catch {
    return null;
  }
}

async function fetchConflicts(params: {
  current?: number;
  pageSize?: number;
}): Promise<{ data: ConflictItem[]; total: number; success: boolean }> {
  const page = params.current ?? 1;
  const size = params.pageSize ?? 20;
  try {
    const res = await fetch(
      `/api/v1/member/golden-id/conflicts?page=${page}&size=${size}`,
      { headers: HEADERS },
    );
    const json = await res.json();
    if (json.ok) {
      return { data: json.data.items, total: json.data.total, success: true };
    }
    return { data: [], total: 0, success: false };
  } catch {
    return { data: [], total: 0, success: false };
  }
}

async function resolveConflict(
  conflictId: string,
  keepCustomerId: string,
): Promise<boolean> {
  try {
    const res = await fetch(
      `/api/v1/member/golden-id/conflicts/${conflictId}/resolve`,
      {
        method: 'POST',
        headers: HEADERS,
        body: JSON.stringify({
          keep_customer_id: keepCustomerId,
          operator_id: localStorage.getItem('operator_id') ?? 'admin',
        }),
      },
    );
    const json = await res.json();
    return json.ok === true;
  } catch {
    return false;
  }
}

// ── Tab 1：绑定概览 ───────────────────────────────────────────────────────────

const BindingOverviewTab: React.FC = () => {
  const [stats, setStats] = useState<StatsData | null>(null);
  const [loading, setLoading] = useState(false);

  const loadStats = useCallback(async () => {
    setLoading(true);
    const data = await fetchStats();
    setStats(data);
    setLoading(false);
  }, []);

  React.useEffect(() => {
    void loadStats();
  }, [loadStats]);

  // 构造柱状图数据
  const chartData = stats
    ? Object.entries(stats.by_channel).flatMap(([channel, stat]) => [
        {
          channel: CHANNEL_CONFIG[channel]?.label ?? channel,
          type: '已绑定',
          count: stat.active_count,
        },
        {
          channel: CHANNEL_CONFIG[channel]?.label ?? channel,
          type: '冲突',
          count: stat.conflict_count,
        },
        {
          channel: CHANNEL_CONFIG[channel]?.label ?? channel,
          type: '已解绑',
          count: stat.unbound_count,
        },
      ])
    : [];

  const columnConfig = {
    data: chartData,
    xField: 'channel',
    yField: 'count',
    seriesField: 'type',
    isGroup: true,
    color: ['#FF6B35', '#A32D2D', '#B4B2A9'],
    label: {
      position: 'middle' as const,
      style: { fill: '#FFFFFF', fontSize: 12 },
    },
    legend: { position: 'top-right' as const },
    xAxis: { label: { autoRotate: false } },
    columnStyle: { radius: [4, 4, 0, 0] },
  };

  return (
    <div style={{ padding: '0 0 24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={5} style={{ margin: 0, color: '#2C2C2A' }}>
          渠道绑定总览
        </Title>
        <Button
          icon={<ReloadOutlined />}
          loading={loading}
          onClick={() => void loadStats()}
        >
          刷新
        </Button>
      </div>

      {/* 汇总卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card bordered={false} style={{ background: '#FFF3ED', borderRadius: 6 }}>
            <Statistic
              title="全渠道有效绑定"
              value={stats?.total_active_bindings ?? '-'}
              valueStyle={{ color: '#FF6B35', fontWeight: 600 }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card bordered={false} style={{ background: '#FFF1F0', borderRadius: 6 }}>
            <Statistic
              title="待处理冲突"
              value={stats?.total_conflicts ?? '-'}
              valueStyle={{ color: '#A32D2D', fontWeight: 600 }}
              suffix={
                stats && stats.total_conflicts > 0 ? (
                  <ExclamationCircleOutlined style={{ fontSize: 14, marginLeft: 4 }} />
                ) : null
              }
            />
          </Card>
        </Col>
        {Object.entries(CHANNEL_CONFIG).map(([channel, cfg]) => (
          <Col span={6} key={channel}>
            <Card bordered={false} style={{ borderRadius: 6 }}>
              <Statistic
                title={`${cfg.label} 绑定`}
                value={stats?.by_channel[channel]?.active_count ?? '-'}
                valueStyle={{ color: cfg.color, fontWeight: 600 }}
                suffix={
                  stats?.by_channel[channel]?.unique_customers != null ? (
                    <span style={{ fontSize: 12, color: '#5F5E5A', fontWeight: 400 }}>
                      {` / ${stats.by_channel[channel].unique_customers} 顾客`}
                    </span>
                  ) : null
                }
              />
            </Card>
          </Col>
        ))}
      </Row>

      {/* 各渠道详细卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        {Object.entries(CHANNEL_CONFIG).map(([channel, cfg]) => {
          const stat = stats?.by_channel[channel];
          return (
            <Col span={6} key={channel}>
              <Card
                title={
                  <span style={{ color: cfg.color, fontWeight: 600 }}>
                    {cfg.label}
                  </span>
                }
                bordered={false}
                style={{ borderRadius: 6, border: `1px solid #E8E6E1` }}
                bodyStyle={{ paddingTop: 12 }}
              >
                <Row>
                  <Col span={12}>
                    <div style={{ fontSize: 12, color: '#5F5E5A' }}>有效绑定</div>
                    <div style={{ fontSize: 20, fontWeight: 600, color: '#0F6E56' }}>
                      {stat?.active_count ?? 0}
                    </div>
                  </Col>
                  <Col span={12}>
                    <div style={{ fontSize: 12, color: '#5F5E5A' }}>唯一顾客</div>
                    <div style={{ fontSize: 20, fontWeight: 600, color: '#2C2C2A' }}>
                      {stat?.unique_customers ?? 0}
                    </div>
                  </Col>
                  <Col span={12} style={{ marginTop: 8 }}>
                    <div style={{ fontSize: 12, color: '#5F5E5A' }}>冲突</div>
                    <div
                      style={{
                        fontSize: 16,
                        fontWeight: 600,
                        color: (stat?.conflict_count ?? 0) > 0 ? '#A32D2D' : '#B4B2A9',
                      }}
                    >
                      {stat?.conflict_count ?? 0}
                    </div>
                  </Col>
                  <Col span={12} style={{ marginTop: 8 }}>
                    <div style={{ fontSize: 12, color: '#5F5E5A' }}>已解绑</div>
                    <div style={{ fontSize: 16, fontWeight: 600, color: '#B4B2A9' }}>
                      {stat?.unbound_count ?? 0}
                    </div>
                  </Col>
                </Row>
              </Card>
            </Col>
          );
        })}
      </Row>

      {/* 柱状图 */}
      <Card
        title="各渠道绑定分布"
        bordered={false}
        style={{ borderRadius: 6, border: '1px solid #E8E6E1' }}
      >
        {chartData.length > 0 ? (
          <Column {...columnConfig} height={280} />
        ) : (
          <div style={{ textAlign: 'center', color: '#B4B2A9', padding: '40px 0' }}>
            {loading ? '加载中...' : '暂无数据'}
          </div>
        )}
      </Card>
    </div>
  );
};

// ── Tab 2：冲突解决 ───────────────────────────────────────────────────────────

const ConflictResolveTab: React.FC = () => {
  const tableRef = useRef<ActionType>();
  const [resolveModal, setResolveModal] = useState<ResolveModalState>({
    visible: false,
    conflict: null,
  });
  const [keepCustomerId, setKeepCustomerId] = useState<string>('');
  const [resolving, setResolving] = useState(false);

  const handleOpenResolve = (record: ConflictItem) => {
    setKeepCustomerId(record.customer_id);
    setResolveModal({ visible: true, conflict: record });
  };

  const handleResolveConfirm = async () => {
    if (!resolveModal.conflict || !keepCustomerId) return;
    setResolving(true);
    const ok = await resolveConflict(resolveModal.conflict.id, keepCustomerId);
    setResolving(false);
    if (ok) {
      message.success('冲突已解决');
      setResolveModal({ visible: false, conflict: null });
      tableRef.current?.reload();
    } else {
      message.error('解决失败，请重试');
    }
  };

  const columns: ProColumns<ConflictItem>[] = [
    {
      title: '冲突 ID',
      dataIndex: 'id',
      width: 220,
      copyable: true,
      ellipsis: true,
    },
    {
      title: '渠道',
      dataIndex: 'channel_type',
      width: 110,
      render: (_, r) => {
        const cfg = CHANNEL_CONFIG[r.channel_type];
        return (
          <Tag color={cfg ? cfg.color : 'default'}>
            {cfg?.label ?? r.channel_type}
          </Tag>
        );
      },
      valueType: 'select',
      valueEnum: Object.fromEntries(
        Object.entries(CHANNEL_CONFIG).map(([k, v]) => [k, { text: v.label }]),
      ),
    },
    {
      title: '渠道 OpenID',
      dataIndex: 'channel_openid',
      ellipsis: true,
      copyable: true,
    },
    {
      title: '当前 Customer ID',
      dataIndex: 'customer_id',
      ellipsis: true,
      copyable: true,
    },
    {
      title: '手机哈希',
      dataIndex: 'phone_hash',
      ellipsis: true,
      width: 180,
      render: (v) => (
        <span style={{ color: '#5F5E5A', fontFamily: 'monospace', fontSize: 12 }}>
          {String(v).slice(0, 12)}…
        </span>
      ),
    },
    {
      title: '产生时间',
      dataIndex: 'created_at',
      valueType: 'dateTime',
      width: 160,
      search: false,
    },
    {
      title: '状态',
      width: 90,
      search: false,
      render: () => (
        <Badge status="error" text={<span style={{ color: '#A32D2D' }}>冲突</span>} />
      ),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 100,
      render: (_, record) => [
        <Button
          key="resolve"
          type="link"
          size="small"
          style={{ color: '#FF6B35', padding: 0 }}
          onClick={() => handleOpenResolve(record)}
        >
          解决冲突
        </Button>,
      ],
    },
  ];

  return (
    <>
      <ProTable<ConflictItem>
        actionRef={tableRef}
        columns={columns}
        request={fetchConflicts}
        rowKey="id"
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 20, showSizeChanger: true }}
        toolBarRender={() => [
          <Button
            key="refresh"
            icon={<ReloadOutlined />}
            onClick={() => tableRef.current?.reload()}
          >
            刷新
          </Button>,
        ]}
        headerTitle={
          <span style={{ color: '#2C2C2A', fontWeight: 600 }}>
            <ExclamationCircleOutlined style={{ color: '#A32D2D', marginRight: 6 }} />
            待处理冲突列表
          </span>
        }
        locale={{ emptyText: '暂无冲突记录' }}
      />

      {/* 解决冲突 Modal */}
      <Modal
        title="解决 Golden ID 冲突"
        open={resolveModal.visible}
        onCancel={() => setResolveModal({ visible: false, conflict: null })}
        onOk={() => void handleResolveConfirm()}
        confirmLoading={resolving}
        okText="确认保留"
        cancelText="取消"
        okButtonProps={{ style: { background: '#FF6B35', borderColor: '#FF6B35' } }}
        width={520}
      >
        {resolveModal.conflict && (
          <div>
            <p style={{ color: '#5F5E5A', marginBottom: 16 }}>
              渠道 <Tag color={CHANNEL_CONFIG[resolveModal.conflict.channel_type]?.color}>
                {CHANNEL_CONFIG[resolveModal.conflict.channel_type]?.label ?? resolveModal.conflict.channel_type}
              </Tag>
              的 OpenID <code style={{ background: '#F8F7F5', padding: '2px 6px', borderRadius: 4 }}>
                {resolveModal.conflict.channel_openid}
              </code> 存在多个 Customer ID 绑定冲突。
            </p>
            <p style={{ marginBottom: 8, fontWeight: 500 }}>请选择要保留的 Customer ID：</p>
            <Select
              value={keepCustomerId}
              onChange={setKeepCustomerId}
              style={{ width: '100%' }}
              placeholder="选择保留的 Customer ID"
              options={[
                {
                  label: (
                    <span>
                      <Tag color="orange">当前记录</Tag>
                      {resolveModal.conflict.customer_id}
                    </span>
                  ),
                  value: resolveModal.conflict.customer_id,
                },
              ]}
            />
            <p style={{ marginTop: 12, color: '#BA7517', fontSize: 12 }}>
              未被选择的 Customer ID 绑定将标记为「已解绑」，操作不可逆。
            </p>
          </div>
        )}
      </Modal>
    </>
  );
};

// ── 主页面 ─────────────────────────────────────────────────────────────────────

const GoldenIDManagePage: React.FC = () => {
  const tabItems = [
    {
      key: 'overview',
      label: (
        <span>
          <BranchesOutlined />
          绑定概览
        </span>
      ),
      children: <BindingOverviewTab />,
    },
    {
      key: 'conflicts',
      label: (
        <span>
          <ExclamationCircleOutlined style={{ color: '#A32D2D' }} />
          冲突解决
        </span>
      ),
      children: <ConflictResolveTab />,
    },
  ];

  return (
    <ConfigProvider theme={TX_THEME}>
      <div style={{ padding: 24, background: '#F8F7F5', minHeight: '100vh' }}>
        <div style={{ marginBottom: 20 }}>
          <Title level={4} style={{ margin: 0, color: '#2C2C2A' }}>
            <BranchesOutlined style={{ color: '#FF6B35', marginRight: 8 }} />
            全渠道 Golden ID 管理
          </Title>
          <span style={{ color: '#5F5E5A', fontSize: 13 }}>
            管理美团 / 饿了么 / 抖音 / 微信渠道 openid 与内部 Golden ID 的绑定关系
          </span>
        </div>

        <Card
          bordered={false}
          style={{ borderRadius: 8, boxShadow: '0 1px 2px rgba(0,0,0,0.05)' }}
          bodyStyle={{ padding: '0 24px 24px' }}
        >
          <Tabs defaultActiveKey="overview" items={tabItems} />
        </Card>
      </div>
    </ConfigProvider>
  );
};

export default GoldenIDManagePage;
