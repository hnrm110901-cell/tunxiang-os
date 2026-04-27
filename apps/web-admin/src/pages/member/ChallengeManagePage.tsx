/**
 * ChallengeManagePage — 挑战活动管理
 * 挑战列表 / CRUD / 进度查看 / 参与者列表
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Col,
  Row,
  Tag,
  Button,
  Table,
  Modal,
  Form,
  Input,
  InputNumber,
  Select,
  DatePicker,
  Typography,
  Space,
  Statistic,
  Spin,
  message,
  Progress,
  Tooltip,
  Popconfirm,
  Tabs,
} from 'antd';
import {
  FlagOutlined,
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  TeamOutlined,
  CalendarOutlined,
  ReloadOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';
import { txFetchData } from '../../api';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

// ─── 类型 ───────────────────────────────────────────────────────────────────

interface Challenge {
  id: string;
  name: string;
  description: string;
  type: string;
  rules: Record<string, unknown>;
  reward: Record<string, unknown>;
  badge_id: string | null;
  start_date: string;
  end_date: string;
  max_participants: number;
  current_participants: number;
  is_active: boolean;
  icon_url: string;
  display_order: number;
}

interface Participant {
  customer_id: string;
  current_value: number;
  target_value: number;
  status: string;
  joined_at: string;
  completed_at: string | null;
  claimed_at: string | null;
}

// ─── 常量 ───────────────────────────────────────────────────────────────────

const CHALLENGE_TYPES = [
  { value: 'visit_streak', label: '连续到店' },
  { value: 'spend_target', label: '消费目标' },
  { value: 'dish_explorer', label: '美食探索' },
  { value: 'social_share', label: '社交分享' },
  { value: 'referral_drive', label: '推荐好友' },
  { value: 'seasonal_event', label: '季节活动' },
  { value: 'time_limited', label: '限时挑战' },
  { value: 'combo_quest', label: '组合任务' },
];

const REWARD_TYPES = [
  { value: 'points', label: '积分' },
  { value: 'coupon', label: '优惠券' },
  { value: 'badge', label: '徽章' },
  { value: 'free_item', label: '免费菜品' },
];

const STATUS_MAP: Record<string, { text: string; color: string }> = {
  active: { text: '进行中', color: 'processing' },
  completed: { text: '已完成', color: 'success' },
  claimed: { text: '已领取', color: 'default' },
  expired: { text: '已过期', color: 'warning' },
  abandoned: { text: '已放弃', color: 'error' },
};

const getTypeLabel = (type: string) => {
  const found = CHALLENGE_TYPES.find((t) => t.value === type);
  return found?.label || type;
};

// ─── 组件 ───────────────────────────────────────────────────────────────────

export default function ChallengeManagePage() {
  const [challenges, setChallenges] = useState<Challenge[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingChallenge, setEditingChallenge] = useState<Challenge | null>(null);
  const [participantsModalOpen, setParticipantsModalOpen] = useState(false);
  const [participants, setParticipants] = useState<Participant[]>([]);
  const [participantsLoading, setParticipantsLoading] = useState(false);
  const [selectedChallengeName, setSelectedChallengeName] = useState('');
  const [filterType, setFilterType] = useState<string | undefined>();
  const [form] = Form.useForm();

  // ── 加载列表 ──

  const fetchChallenges = useCallback(async () => {
    setLoading(true);
    try {
      const params: string[] = ['size=100'];
      if (filterType) params.push(`type=${filterType}`);
      const res = await txFetchData(`/api/v1/member/challenges?${params.join('&')}`);
      if (res?.ok) {
        setChallenges(res.data.items || []);
      }
    } catch {
      message.error('加载挑战失败');
    } finally {
      setLoading(false);
    }
  }, [filterType]);

  useEffect(() => {
    fetchChallenges();
  }, [fetchChallenges]);

  // ── 创建/编辑 ──

  const openCreate = () => {
    setEditingChallenge(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (ch: Challenge) => {
    setEditingChallenge(ch);
    const reward = ch.reward as Record<string, unknown>;
    form.setFieldsValue({
      ...ch,
      target: (ch.rules as Record<string, unknown>)?.target || 1,
      reward_type: reward?.type || 'points',
      reward_amount: reward?.amount || 0,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      const payload = {
        name: values.name,
        description: values.description || '',
        type: values.type,
        rules: { target: values.target || 1 },
        reward: {
          type: values.reward_type || 'points',
          amount: values.reward_amount || 0,
        },
        start_date: values.date_range?.[0]?.toISOString() || new Date().toISOString(),
        end_date: values.date_range?.[1]?.toISOString() || new Date().toISOString(),
        max_participants: values.max_participants || 0,
        icon_url: values.icon_url || '',
        display_order: values.display_order || 0,
      };

      if (editingChallenge) {
        const res = await txFetchData(`/api/v1/member/challenges/${editingChallenge.id}`, {
          method: 'PUT',
          body: JSON.stringify(payload),
        });
        if (res?.ok) message.success('更新成功');
      } else {
        const res = await txFetchData('/api/v1/member/challenges', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        if (res?.ok) message.success('创建成功');
      }
      setModalOpen(false);
      fetchChallenges();
    } catch {
      // form validation error
    }
  };

  // ── 删除 ──

  const handleDelete = async (id: string) => {
    const res = await txFetchData(`/api/v1/member/challenges/${id}`, { method: 'DELETE' });
    if (res?.ok) {
      message.success('删除成功');
      fetchChallenges();
    }
  };

  // ── 参与者 ──

  const openParticipants = async (ch: Challenge) => {
    setSelectedChallengeName(ch.name);
    setParticipantsModalOpen(true);
    setParticipantsLoading(true);
    try {
      // 生产环境调用 /api/v1/member/challenges/{id}/participants
      setParticipants([]);
    } catch {
      message.error('加载参与者失败');
    } finally {
      setParticipantsLoading(false);
    }
  };

  // ── 统计 ──

  const totalChallenges = challenges.length;
  const activeChallenges = challenges.filter((c) => c.is_active).length;
  const totalParticipants = challenges.reduce((s, c) => s + (c.current_participants || 0), 0);

  // ── 表格列 ──

  const columns = [
    {
      title: '挑战名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: Challenge) => (
        <Space>
          <FlagOutlined />
          <Text strong>{name}</Text>
          {!record.is_active && <Tag color="default">已停用</Tag>}
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      render: (type: string) => <Tag color="blue">{getTypeLabel(type)}</Tag>,
    },
    {
      title: '目标',
      key: 'target',
      render: (_: unknown, record: Challenge) => {
        const rules = record.rules as Record<string, unknown>;
        return <Text>{String(rules?.target || '-')}</Text>;
      },
    },
    {
      title: '参与人数',
      key: 'participants',
      render: (_: unknown, record: Challenge) => (
        <Space>
          <TeamOutlined />
          <Text>
            {record.current_participants}
            {record.max_participants > 0 ? ` / ${record.max_participants}` : ''}
          </Text>
        </Space>
      ),
    },
    {
      title: '时间',
      key: 'dates',
      render: (_: unknown, record: Challenge) => {
        const start = record.start_date ? new Date(record.start_date).toLocaleDateString('zh-CN') : '-';
        const end = record.end_date ? new Date(record.end_date).toLocaleDateString('zh-CN') : '-';
        const now = new Date();
        const isOngoing =
          record.start_date && record.end_date &&
          now >= new Date(record.start_date) &&
          now <= new Date(record.end_date);
        return (
          <Space>
            {isOngoing ? (
              <ClockCircleOutlined style={{ color: '#1890ff' }} />
            ) : (
              <CalendarOutlined />
            )}
            <Text type="secondary">
              {start} ~ {end}
            </Text>
          </Space>
        );
      },
    },
    {
      title: '奖励',
      key: 'reward',
      render: (_: unknown, record: Challenge) => {
        const reward = record.reward as Record<string, unknown>;
        const type = reward?.type as string;
        const amount = reward?.amount as number;
        return (
          <Tag color="gold">
            {type === 'points' ? `${amount}积分` : type === 'coupon' ? '优惠券' : type || '-'}
          </Tag>
        );
      },
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: unknown, record: Challenge) => (
        <Space>
          <Tooltip title="编辑">
            <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)} />
          </Tooltip>
          <Tooltip title="参与者">
            <Button size="small" icon={<TeamOutlined />} onClick={() => openParticipants(record)} />
          </Tooltip>
          <Popconfirm title="确认删除？" onConfirm={() => handleDelete(record.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // ── 参与者表格列 ──

  const participantColumns = [
    { title: '顾客ID', dataIndex: 'customer_id', key: 'customer_id', ellipsis: true },
    {
      title: '进度',
      key: 'progress',
      render: (_: unknown, record: Participant) => (
        <Progress
          percent={Math.round((record.current_value / record.target_value) * 100)}
          size="small"
          format={() => `${record.current_value}/${record.target_value}`}
        />
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        const s = STATUS_MAP[status] || { text: status, color: 'default' };
        return <Tag color={s.color}>{s.text}</Tag>;
      },
    },
    {
      title: '参加时间',
      dataIndex: 'joined_at',
      key: 'joined_at',
      render: (v: string) => (v ? new Date(v).toLocaleString('zh-CN') : '-'),
    },
    {
      title: '完成时间',
      dataIndex: 'completed_at',
      key: 'completed_at',
      render: (v: string | null) =>
        v ? (
          <Space>
            <CheckCircleOutlined style={{ color: '#52c41a' }} />
            {new Date(v).toLocaleString('zh-CN')}
          </Space>
        ) : (
          '-'
        ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Title level={3}>
        <FlagOutlined /> 挑战活动管理
      </Title>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={8}>
          <Card>
            <Statistic title="挑战总数" value={totalChallenges} prefix={<FlagOutlined />} />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title="进行中" value={activeChallenges} valueStyle={{ color: '#1890ff' }} />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="总参与人次"
              value={totalParticipants}
              prefix={<TeamOutlined />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 操作栏 */}
      <Space style={{ marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建挑战
        </Button>
        <Select
          placeholder="按类型筛选"
          allowClear
          style={{ width: 160 }}
          value={filterType}
          onChange={setFilterType}
          options={CHALLENGE_TYPES}
        />
        <Button icon={<ReloadOutlined />} onClick={fetchChallenges}>
          刷新
        </Button>
      </Space>

      {/* 挑战列表 */}
      <Table
        dataSource={challenges}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={{ pageSize: 15 }}
      />

      {/* 创建/编辑弹窗 */}
      <Modal
        title={editingChallenge ? '编辑挑战' : '新建挑战'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        width={650}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="挑战名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="type"
                label="挑战类型"
                rules={[{ required: true, message: '请选择类型' }]}
              >
                <Select options={CHALLENGE_TYPES} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="target" label="目标值" initialValue={1}>
                <InputNumber min={1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="reward_type" label="奖励类型" initialValue="points">
                <Select options={REWARD_TYPES} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="reward_amount" label="奖励数量" initialValue={0}>
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="date_range" label="活动时间" rules={[{ required: true, message: '请选择时间' }]}>
            <RangePicker showTime style={{ width: '100%' }} />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="max_participants" label="参与上限(0=不限)" initialValue={0}>
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="display_order" label="排序" initialValue={0}>
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="icon_url" label="图标URL">
            <Input placeholder="https://..." />
          </Form.Item>
        </Form>
      </Modal>

      {/* 参与者弹窗 */}
      <Modal
        title={`${selectedChallengeName} - 参与者`}
        open={participantsModalOpen}
        onCancel={() => setParticipantsModalOpen(false)}
        footer={null}
        width={850}
      >
        <Spin spinning={participantsLoading}>
          <Table
            dataSource={participants}
            columns={participantColumns}
            rowKey="customer_id"
            pagination={{ pageSize: 10 }}
          />
        </Spin>
      </Modal>
    </div>
  );
}
