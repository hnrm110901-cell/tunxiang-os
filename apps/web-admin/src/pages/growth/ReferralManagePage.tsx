/**
 * CRM三级分销管理页
 * TC-P2-14 — 私域裂变三级链路 + 奖励体系
 *
 * 四个Tab：分销总览 / 推荐关系 / 奖励记录 / 排行榜
 */
import { useEffect, useState } from 'react';
import {
  Tabs,
  Card,
  Row,
  Col,
  Statistic,
  Button,
  Form,
  InputNumber,
  Select,
  Tag,
  Space,
  Tree,
  Input,
  message,
  Modal,
  Typography,
  Divider,
  Badge,
} from 'antd';
import type { DataNode } from 'antd/es/tree';
import {
  BranchesOutlined,
  GiftOutlined,
  RiseOutlined,
  TeamOutlined,
  TrophyOutlined,
  SearchOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns, ActionType } from '@ant-design/pro-components';
import { useRef } from 'react';

const { Title, Text } = Typography;
const { TabPane } = Tabs;

const API_BASE = '/api/v1/growth/referral';
const TENANT_ID = 'demo-tenant-001'; // 实际应从 useTenantContext() 获取

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------

interface DistributionStats {
  participant_count: number;
  participant_growth_this_month: number;
  three_level_chain_count: number;
  this_month_issued_fen: number;
  pending_reward_fen: number;
  total_click_count: number;
  total_convert_count: number;
}

interface DistributionRules {
  level1_rate: number;
  level2_rate: number;
  level3_rate: number;
  reward_type: string;
  trigger_type: string;
}

interface TreeNode {
  member_id: string;
  name: string;
  level: number;
  orders?: number;
  total_fen?: number;
  children: TreeNode[];
}

interface RewardRecord {
  id: string;
  member_id: string;
  referee_id: string;
  reward_level: number;
  trigger_type: string;
  reward_type: string;
  reward_value_fen: number;
  status: 'pending' | 'issued' | 'expired' | 'cancelled';
  order_id: string | null;
  issued_at: string | null;
  created_at: string;
}

interface LeaderboardItem {
  rank: number;
  member_id: string;
  nickname: string;
  phone_tail: string;
  direct_referrals: number;
  indirect_referrals: number;
  total_reward_fen: number;
}

// ---------------------------------------------------------------------------
// 工具函数
// ---------------------------------------------------------------------------

const fenToYuan = (fen: number) => (fen / 100).toFixed(2);
const rateToPercent = (rate: number) => `${(rate * 100).toFixed(1)}%`;

const statusTagProps: Record<string, { color: string; label: string }> = {
  pending:   { color: 'orange',  label: '待发放' },
  issued:    { color: 'green',   label: '已发放' },
  expired:   { color: 'default', label: '已过期' },
  cancelled: { color: 'red',     label: '已取消' },
};

const rankMedal = (rank: number) => {
  if (rank === 1) return <span style={{ color: '#FFD700', fontSize: 18 }}>🥇</span>;
  if (rank === 2) return <span style={{ color: '#C0C0C0', fontSize: 18 }}>🥈</span>;
  if (rank === 3) return <span style={{ color: '#CD7F32', fontSize: 18 }}>🥉</span>;
  return <span style={{ color: '#5F5E5A' }}>{rank}</span>;
};

// antd Tree 格式转换
const toTreeData = (node: TreeNode): DataNode => ({
  key: node.member_id,
  title: (
    <Space>
      <Text strong>{node.name}</Text>
      {node.orders !== undefined && (
        <Text type="secondary" style={{ fontSize: 12 }}>
          消费 {node.orders} 单 / ¥{fenToYuan(node.total_fen ?? 0)}
        </Text>
      )}
      {node.level === 1 && <Tag color="blue">一级</Tag>}
      {node.level === 2 && <Tag color="cyan">二级</Tag>}
      {node.level === 3 && <Tag color="geekblue">三级</Tag>}
    </Space>
  ),
  children: node.children.map(toTreeData),
});

// ---------------------------------------------------------------------------
// API 调用层
// ---------------------------------------------------------------------------

const apiFetch = async (path: string, init?: RequestInit) => {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': TENANT_ID,
      ...init?.headers,
    },
    ...init,
  });
  const json = await res.json();
  if (!json.ok) {
    throw new Error(json.error?.message ?? '请求失败');
  }
  return json.data;
};

// ---------------------------------------------------------------------------
// Tab1: 分销总览
// ---------------------------------------------------------------------------

const OverviewTab = () => {
  const [stats, setStats] = useState<DistributionStats | null>(null);
  const [rules, setRules] = useState<DistributionRules | null>(null);
  const [rulesLoading, setRulesLoading] = useState(false);
  const [form] = Form.useForm<DistributionRules>();

  useEffect(() => {
    apiFetch('/stats').then(setStats).catch((e: Error) => message.error(e.message));
    apiFetch('/rules').then((data: DistributionRules) => {
      setRules(data);
      form.setFieldsValue({
        level1_rate: data.level1_rate * 100,
        level2_rate: data.level2_rate * 100,
        level3_rate: data.level3_rate * 100,
        reward_type: data.reward_type,
        trigger_type: data.trigger_type,
      });
    }).catch((e: Error) => message.error(e.message));
  }, [form]);

  const handleSaveRules = async (values: {
    level1_rate: number;
    level2_rate: number;
    level3_rate: number;
    reward_type: string;
    trigger_type: string;
  }) => {
    setRulesLoading(true);
    try {
      await apiFetch('/rules', {
        method: 'POST',
        body: JSON.stringify({
          level1_rate: values.level1_rate / 100,
          level2_rate: values.level2_rate / 100,
          level3_rate: values.level3_rate / 100,
          reward_type: values.reward_type,
          trigger_type: values.trigger_type,
        }),
      });
      message.success('分销规则已保存');
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setRulesLoading(false);
    }
  };

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      {/* 统计卡片 */}
      <Row gutter={16}>
        <Col span={6}>
          <Card>
            <Statistic
              title="参与会员数"
              value={stats?.participant_count ?? '--'}
              prefix={<TeamOutlined />}
              suffix={
                stats ? (
                  <Text style={{ fontSize: 12, color: '#0F6E56' }}>
                    +{stats.participant_growth_this_month} 本月
                  </Text>
                ) : undefined
              }
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="三级链路数"
              value={stats?.three_level_chain_count ?? '--'}
              prefix={<BranchesOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="本月奖励发放"
              value={stats ? fenToYuan(stats.this_month_issued_fen) : '--'}
              prefix="¥"
              prefix={<GiftOutlined />}
              valueStyle={{ color: '#FF6B35' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="待发放奖励"
              value={stats ? fenToYuan(stats.pending_reward_fen) : '--'}
              prefix="¥"
              prefix={<ClockCircleOutlined />}
              valueStyle={{ color: '#BA7517' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 转化率统计 */}
      {stats && (
        <Row gutter={16}>
          <Col span={8}>
            <Card size="small" title="推荐链接点击">
              <Statistic value={stats.total_click_count} prefix={<RiseOutlined />} />
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small" title="成功转化注册">
              <Statistic value={stats.total_convert_count} />
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small" title="转化率">
              <Statistic
                value={
                  stats.total_click_count
                    ? ((stats.total_convert_count / stats.total_click_count) * 100).toFixed(1)
                    : '0.0'
                }
                suffix="%"
                valueStyle={{ color: '#0F6E56' }}
              />
            </Card>
          </Col>
        </Row>
      )}

      <Divider />

      {/* 分销规则配置 */}
      <Card
        title={
          <Space>
            <BranchesOutlined />
            <span>分销规则配置</span>
            <Tag color="blue">各级佣金比例可调</Tag>
          </Space>
        }
      >
        <Form
          form={form}
          layout="inline"
          onFinish={handleSaveRules}
          style={{ rowGap: 16 }}
        >
          <Form.Item
            name="level1_rate"
            label="一级佣金比例(%)"
            rules={[{ required: true, min: 0, max: 100, type: 'number' }]}
          >
            <InputNumber min={0} max={100} step={0.5} style={{ width: 120 }} />
          </Form.Item>
          <Form.Item
            name="level2_rate"
            label="二级佣金比例(%)"
            rules={[{ required: true, min: 0, max: 100, type: 'number' }]}
          >
            <InputNumber min={0} max={100} step={0.5} style={{ width: 120 }} />
          </Form.Item>
          <Form.Item
            name="level3_rate"
            label="三级佣金比例(%)"
            rules={[{ required: true, min: 0, max: 100, type: 'number' }]}
          >
            <InputNumber min={0} max={100} step={0.5} style={{ width: 120 }} />
          </Form.Item>
          <Form.Item name="reward_type" label="奖励类型">
            <Select style={{ width: 120 }}>
              <Select.Option value="points">积分</Select.Option>
              <Select.Option value="coupon">优惠券</Select.Option>
              <Select.Option value="cash">现金</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="trigger_type" label="触发方式">
            <Select style={{ width: 120 }}>
              <Select.Option value="first_order">首单触发</Select.Option>
              <Select.Option value="order">每单触发</Select.Option>
              <Select.Option value="recharge">充值触发</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              loading={rulesLoading}
              style={{ backgroundColor: '#FF6B35', borderColor: '#FF6B35' }}
            >
              保存规则
            </Button>
          </Form.Item>
        </Form>

        {rules && (
          <div style={{ marginTop: 16, padding: '12px 16px', background: '#F8F7F5', borderRadius: 6 }}>
            <Text type="secondary">
              当前规则：一级 {rateToPercent(rules.level1_rate)} /{' '}
              二级 {rateToPercent(rules.level2_rate)} /{' '}
              三级 {rateToPercent(rules.level3_rate)} |{' '}
              奖励类型：{rules.reward_type} | 触发：{rules.trigger_type}
            </Text>
          </div>
        )}
      </Card>
    </Space>
  );
};

// ---------------------------------------------------------------------------
// Tab2: 推荐关系树
// ---------------------------------------------------------------------------

const RelationshipTab = () => {
  const [searchId, setSearchId] = useState('mem-001');
  const [treeData, setTreeData] = useState<DataNode[]>([]);
  const [summary, setSummary] = useState<{
    direct_referrals: number;
    indirect_referrals: number;
    total_fen: number;
  } | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSearch = async () => {
    if (!searchId.trim()) {
      message.warning('请输入会员ID或手机号');
      return;
    }
    setLoading(true);
    try {
      const data = await apiFetch(`/tree/${encodeURIComponent(searchId.trim())}`);
      const root = toTreeData(data.tree as TreeNode);
      setTreeData([root]);
      setSummary(data.summary);
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // 初始加载演示数据
    handleSearch();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      {/* 搜索区 */}
      <Card size="small">
        <Space>
          <Input
            placeholder="输入会员ID（如 mem-001）或手机号"
            value={searchId}
            onChange={(e) => setSearchId(e.target.value)}
            onPressEnter={handleSearch}
            style={{ width: 320 }}
            prefix={<SearchOutlined />}
          />
          <Button
            type="primary"
            loading={loading}
            onClick={handleSearch}
            style={{ backgroundColor: '#FF6B35', borderColor: '#FF6B35' }}
          >
            查询推荐树
          </Button>
        </Space>
      </Card>

      {/* 汇总统计 */}
      {summary && (
        <Row gutter={12}>
          <Col span={8}>
            <Card size="small">
              <Statistic title="直接下线（一级）" value={summary.direct_referrals} />
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small">
              <Statistic title="间接下线（二/三级）" value={summary.indirect_referrals} />
            </Card>
          </Col>
          <Col span={8}>
            <Card size="small">
              <Statistic
                title="下线累计消费"
                value={fenToYuan(summary.total_fen)}
                prefix="¥"
                valueStyle={{ color: '#FF6B35' }}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* 推荐关系树 */}
      {treeData.length > 0 && (
        <Card title="推荐关系树（最多展示三级）">
          <Tree
            treeData={treeData}
            defaultExpandAll
            showLine
            style={{ fontSize: 14 }}
          />
        </Card>
      )}
    </Space>
  );
};

// ---------------------------------------------------------------------------
// Tab3: 奖励记录
// ---------------------------------------------------------------------------

const RewardsTab = () => {
  const actionRef = useRef<ActionType>();
  const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>([]);
  const [batchIssuing, setBatchIssuing] = useState(false);

  const columns: ProColumns<RewardRecord>[] = [
    {
      title: '获奖会员',
      dataIndex: 'member_id',
      width: 140,
      render: (val) => <Text code>{String(val)}</Text>,
    },
    {
      title: '触发会员',
      dataIndex: 'referee_id',
      width: 140,
      render: (val) => <Text code>{String(val)}</Text>,
    },
    {
      title: '奖励级别',
      dataIndex: 'reward_level',
      width: 90,
      render: (val) => {
        const colors = ['', 'blue', 'cyan', 'geekblue'];
        return <Tag color={colors[Number(val)] ?? 'default'}>第 {String(val)} 级</Tag>;
      },
    },
    {
      title: '奖励类型',
      dataIndex: 'reward_type',
      width: 90,
      render: (val) => <Tag>{String(val)}</Tag>,
    },
    {
      title: '奖励金额',
      dataIndex: 'reward_value_fen',
      width: 110,
      align: 'right',
      render: (val) => (
        <Text strong style={{ color: '#FF6B35' }}>
          ¥{fenToYuan(Number(val))}
        </Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (val) => {
        const { color, label } = statusTagProps[String(val)] ?? { color: 'default', label: String(val) };
        return <Tag color={color}>{label}</Tag>;
      },
      valueEnum: {
        pending:   { text: '待发放', status: 'Warning' },
        issued:    { text: '已发放', status: 'Success' },
        expired:   { text: '已过期', status: 'Default' },
        cancelled: { text: '已取消', status: 'Error' },
      },
    },
    {
      title: '触发方式',
      dataIndex: 'trigger_type',
      width: 100,
      render: (val) => {
        const map: Record<string, string> = {
          first_order: '首单',
          order: '每单',
          recharge: '充值',
        };
        return map[String(val)] ?? String(val);
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 160,
      render: (val) => <Text type="secondary" style={{ fontSize: 12 }}>{String(val)}</Text>,
    },
    {
      title: '发放时间',
      dataIndex: 'issued_at',
      width: 160,
      render: (val) =>
        val ? (
          <Text style={{ fontSize: 12 }}>{String(val)}</Text>
        ) : (
          <Text type="secondary" style={{ fontSize: 12 }}>--</Text>
        ),
    },
  ];

  const handleBatchIssue = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择待发放的奖励记录');
      return;
    }
    setBatchIssuing(true);
    let successCount = 0;
    let failCount = 0;
    for (const rewardId of selectedRowKeys) {
      try {
        await apiFetch(`/rewards/issue/${rewardId}`, { method: 'POST' });
        successCount++;
      } catch {
        failCount++;
      }
    }
    setBatchIssuing(false);
    setSelectedRowKeys([]);
    if (successCount > 0) message.success(`已发放 ${successCount} 条奖励`);
    if (failCount > 0) message.warning(`${failCount} 条发放失败（可能已非 pending 状态）`);
    actionRef.current?.reload();
  };

  return (
    <ProTable<RewardRecord>
      actionRef={actionRef}
      rowKey="id"
      columns={columns}
      request={async (params) => {
        const qs = new URLSearchParams({
          page: String(params.current ?? 1),
          size: String(params.pageSize ?? 20),
          ...(params.status ? { status: params.status as string } : {}),
        });
        // 演示：查询 mem-001 的奖励数据
        const data = await apiFetch(`/rewards/mem-001?${qs}`);
        return {
          data: data.items as RewardRecord[],
          total: data.total as number,
          success: true,
        };
      }}
      search={{ labelWidth: 'auto' }}
      rowSelection={{
        selectedRowKeys,
        onChange: (keys) => setSelectedRowKeys(keys as string[]),
        getCheckboxProps: (record) => ({
          disabled: record.status !== 'pending',
        }),
      }}
      toolBarRender={() => [
        <Button
          key="batch-issue"
          type="primary"
          icon={<CheckCircleOutlined />}
          loading={batchIssuing}
          onClick={handleBatchIssue}
          disabled={selectedRowKeys.length === 0}
          style={{ backgroundColor: '#0F6E56', borderColor: '#0F6E56' }}
        >
          批量发放 ({selectedRowKeys.length})
        </Button>,
      ]}
      pagination={{ defaultPageSize: 20 }}
      scroll={{ x: 1000 }}
    />
  );
};

// ---------------------------------------------------------------------------
// Tab4: 排行榜
// ---------------------------------------------------------------------------

const LeaderboardTab = () => {
  const [period, setPeriod] = useState<'today' | 'week' | 'month'>('month');
  const [items, setItems] = useState<LeaderboardItem[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchLeaderboard = async (p: string) => {
    setLoading(true);
    try {
      const data = await apiFetch(`/leaderboard?period=${p}`);
      setItems(data.items as LeaderboardItem[]);
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLeaderboard(period);
  }, [period]);

  const columns: ProColumns<LeaderboardItem>[] = [
    {
      title: '排名',
      dataIndex: 'rank',
      width: 70,
      render: (_, record) => rankMedal(record.rank),
    },
    {
      title: '昵称',
      dataIndex: 'nickname',
      render: (val, record) => (
        <Space>
          <Text strong>{String(val)}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            尾号 {record.phone_tail}
          </Text>
        </Space>
      ),
    },
    {
      title: '直接推荐人数',
      dataIndex: 'direct_referrals',
      align: 'right',
      render: (val) => (
        <Badge count={Number(val)} showZero color="#185FA5" />
      ),
    },
    {
      title: '间接推荐人数',
      dataIndex: 'indirect_referrals',
      align: 'right',
      render: (val) => (
        <Badge count={Number(val)} showZero color="#0F6E56" />
      ),
    },
    {
      title: '获得奖励总额',
      dataIndex: 'total_reward_fen',
      align: 'right',
      render: (val) => (
        <Text strong style={{ color: '#FF6B35', fontSize: 16 }}>
          ¥{fenToYuan(Number(val))}
        </Text>
      ),
    },
  ];

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      {/* 周期切换 */}
      <Card size="small">
        <Space>
          <Text>统计周期：</Text>
          {(['today', 'week', 'month'] as const).map((p) => (
            <Button
              key={p}
              type={period === p ? 'primary' : 'default'}
              size="small"
              onClick={() => setPeriod(p)}
              style={
                period === p
                  ? { backgroundColor: '#FF6B35', borderColor: '#FF6B35' }
                  : undefined
              }
            >
              {p === 'today' ? '今日' : p === 'week' ? '本周' : '本月'}
            </Button>
          ))}
        </Space>
      </Card>

      {/* TOP3 荣誉展示 */}
      {items.length >= 3 && (
        <Row gutter={16}>
          {[1, 0, 2].map((idx) => {
            const item = items[idx];
            if (!item) return null;
            const colors = ['#C0C0C0', '#FFD700', '#CD7F32'];
            return (
              <Col span={8} key={item.member_id}>
                <Card
                  style={{
                    textAlign: 'center',
                    borderColor: colors[idx],
                    borderWidth: idx === 1 ? 2 : 1,
                  }}
                >
                  <div style={{ fontSize: 32 }}>
                    {idx === 1 ? '🥇' : idx === 0 ? '🥈' : '🥉'}
                  </div>
                  <Title level={5} style={{ margin: '8px 0 4px' }}>
                    {item.nickname}
                  </Title>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    尾号 {item.phone_tail}
                  </Text>
                  <div style={{ marginTop: 8 }}>
                    <Text strong style={{ color: '#FF6B35', fontSize: 18 }}>
                      ¥{fenToYuan(item.total_reward_fen)}
                    </Text>
                  </div>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    推荐 {item.direct_referrals} 人 · 间接 {item.indirect_referrals} 人
                  </Text>
                </Card>
              </Col>
            );
          })}
        </Row>
      )}

      {/* 完整排行表 */}
      <ProTable<LeaderboardItem>
        rowKey="member_id"
        columns={columns}
        dataSource={items}
        loading={loading}
        search={false}
        pagination={false}
        toolBarRender={() => [
          <TrophyOutlined key="icon" style={{ fontSize: 20, color: '#FFD700' }} />,
        ]}
        headerTitle={`分销排行榜 · ${period === 'today' ? '今日' : period === 'week' ? '本周' : '本月'}`}
      />
    </Space>
  );
};

// ---------------------------------------------------------------------------
// 主页面
// ---------------------------------------------------------------------------

const ReferralManagePage = () => {
  return (
    <div style={{ padding: '24px', minWidth: 1280, background: '#F8F7F5', minHeight: '100vh' }}>
      <div style={{ marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0, color: '#2C2C2A' }}>
          <BranchesOutlined style={{ marginRight: 8, color: '#FF6B35' }} />
          CRM三级分销管理
        </Title>
        <Text type="secondary">私域裂变三级链路 + 奖励体系配置与管理</Text>
      </div>

      <Tabs
        defaultActiveKey="overview"
        type="card"
        size="large"
        items={[
          {
            key: 'overview',
            label: (
              <Space>
                <RiseOutlined />
                分销总览
              </Space>
            ),
            children: <OverviewTab />,
          },
          {
            key: 'relationships',
            label: (
              <Space>
                <BranchesOutlined />
                推荐关系
              </Space>
            ),
            children: <RelationshipTab />,
          },
          {
            key: 'rewards',
            label: (
              <Space>
                <GiftOutlined />
                奖励记录
              </Space>
            ),
            children: <RewardsTab />,
          },
          {
            key: 'leaderboard',
            label: (
              <Space>
                <TrophyOutlined />
                排行榜
              </Space>
            ),
            children: <LeaderboardTab />,
          },
        ]}
      />
    </div>
  );
};

export default ReferralManagePage;
