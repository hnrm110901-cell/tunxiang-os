/**
 * BadgeManagePage — 徽章管理
 * 徽章网格展示 / CRUD / 持有者列表 / 稀有度筛选
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
  Typography,
  Space,
  Statistic,
  Spin,
  message,
  Tooltip,
  Popconfirm,
  Empty,
} from 'antd';
import {
  TrophyOutlined,
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  TeamOutlined,
  CrownOutlined,
  StarOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { txFetchData } from '../../api';

const { Title, Text } = Typography;

// ─── 类型 ───────────────────────────────────────────────────────────────────

interface Badge {
  id: string;
  name: string;
  description: string;
  category: string;
  unlock_rule: Record<string, unknown>;
  rarity: string;
  points_reward: number;
  icon_url: string;
  display_order: number;
  is_active: boolean;
}

interface BadgeHolder {
  customer_id: string;
  unlocked_at: string;
  unlock_context: Record<string, unknown>;
}

// ─── 常量 ───────────────────────────────────────────────────────────────────

const CATEGORIES = [
  { value: 'loyalty', label: '忠诚', color: 'gold' },
  { value: 'social', label: '社交', color: 'blue' },
  { value: 'exploration', label: '探索', color: 'green' },
  { value: 'seasonal', label: '季节', color: 'orange' },
  { value: 'milestone', label: '里程碑', color: 'purple' },
  { value: 'secret', label: '隐藏', color: 'default' },
];

const RARITIES = [
  { value: 'common', label: '普通', color: '#8c8c8c' },
  { value: 'uncommon', label: '稀有', color: '#52c41a' },
  { value: 'rare', label: '精良', color: '#1890ff' },
  { value: 'epic', label: '史诗', color: '#722ed1' },
  { value: 'legendary', label: '传说', color: '#faad14' },
];

const RULE_TYPES = [
  { value: 'visit_count', label: '到店次数' },
  { value: 'spend_total', label: '累计消费(分)' },
  { value: 'consecutive_visits', label: '连续到店天数' },
  { value: 'dish_variety', label: '尝试菜品数' },
  { value: 'referral_count', label: '推荐人数' },
];

// ─── 辅助 ───────────────────────────────────────────────────────────────────

const getCategoryTag = (cat: string) => {
  const found = CATEGORIES.find((c) => c.value === cat);
  return found ? <Tag color={found.color}>{found.label}</Tag> : <Tag>{cat}</Tag>;
};

const getRarityTag = (rarity: string) => {
  const found = RARITIES.find((r) => r.value === rarity);
  return found ? (
    <Tag color={found.color} style={{ fontWeight: 600 }}>
      {found.label}
    </Tag>
  ) : (
    <Tag>{rarity}</Tag>
  );
};

// ─── 组件 ───────────────────────────────────────────────────────────────────

export default function BadgeManagePage() {
  const [badges, setBadges] = useState<Badge[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingBadge, setEditingBadge] = useState<Badge | null>(null);
  const [holdersModalOpen, setHoldersModalOpen] = useState(false);
  const [holders, setHolders] = useState<BadgeHolder[]>([]);
  const [holdersLoading, setHoldersLoading] = useState(false);
  const [selectedBadgeName, setSelectedBadgeName] = useState('');
  const [filterCategory, setFilterCategory] = useState<string | undefined>();
  const [form] = Form.useForm();

  // ── 加载徽章列表 ──

  const fetchBadges = useCallback(async () => {
    setLoading(true);
    try {
      const params = filterCategory ? `?category=${filterCategory}&size=100` : '?size=100';
      const res = await txFetchData(`/api/v1/member/badges${params}`);
      if (res?.ok) {
        setBadges(res.data.items || []);
      }
    } catch {
      message.error('加载徽章失败');
    } finally {
      setLoading(false);
    }
  }, [filterCategory]);

  useEffect(() => {
    fetchBadges();
  }, [fetchBadges]);

  // ── 创建/编辑 ──

  const openCreate = () => {
    setEditingBadge(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (badge: Badge) => {
    setEditingBadge(badge);
    const rule = badge.unlock_rule as Record<string, unknown>;
    form.setFieldsValue({
      ...badge,
      rule_type: rule?.type || 'visit_count',
      rule_threshold: rule?.threshold || 0,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      const payload = {
        name: values.name,
        description: values.description || '',
        category: values.category,
        rarity: values.rarity || 'common',
        points_reward: values.points_reward || 0,
        icon_url: values.icon_url || '',
        display_order: values.display_order || 0,
        unlock_rule: {
          type: values.rule_type,
          threshold: values.rule_threshold || 0,
        },
      };

      if (editingBadge) {
        const res = await txFetchData(`/api/v1/member/badges/${editingBadge.id}`, {
          method: 'PUT',
          body: JSON.stringify(payload),
        });
        if (res?.ok) {
          message.success('更新成功');
        }
      } else {
        const res = await txFetchData('/api/v1/member/badges', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        if (res?.ok) {
          message.success('创建成功');
        }
      }
      setModalOpen(false);
      fetchBadges();
    } catch {
      // form validation error
    }
  };

  // ── 删除 ──

  const handleDelete = async (badgeId: string) => {
    const res = await txFetchData(`/api/v1/member/badges/${badgeId}`, {
      method: 'DELETE',
    });
    if (res?.ok) {
      message.success('删除成功');
      fetchBadges();
    }
  };

  // ── 持有者 ──

  const openHolders = async (badge: Badge) => {
    setSelectedBadgeName(badge.name);
    setHoldersModalOpen(true);
    setHoldersLoading(true);
    try {
      const res = await txFetchData(`/api/v1/member/badges/${badge.id}/holders?size=50`);
      if (res?.ok) {
        setHolders(res.data.items || []);
      }
    } catch {
      message.error('加载持有者失败');
    } finally {
      setHoldersLoading(false);
    }
  };

  // ── 统计 ──

  const totalBadges = badges.length;
  const activeBadges = badges.filter((b) => b.is_active).length;
  const legendaryCount = badges.filter((b) => b.rarity === 'legendary').length;

  // ── 渲染 ──

  return (
    <div style={{ padding: 24 }}>
      <Title level={3}>
        <TrophyOutlined /> 徽章管理
      </Title>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic title="徽章总数" value={totalBadges} prefix={<StarOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="已启用" value={activeBadges} valueStyle={{ color: '#52c41a' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="传说级"
              value={legendaryCount}
              prefix={<CrownOutlined />}
              valueStyle={{ color: '#faad14' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="分类数" value={CATEGORIES.length} />
          </Card>
        </Col>
      </Row>

      {/* 操作栏 */}
      <Space style={{ marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建徽章
        </Button>
        <Select
          placeholder="按分类筛选"
          allowClear
          style={{ width: 160 }}
          value={filterCategory}
          onChange={setFilterCategory}
          options={CATEGORIES}
        />
        <Button icon={<ReloadOutlined />} onClick={fetchBadges}>
          刷新
        </Button>
      </Space>

      {/* 徽章网格 */}
      <Spin spinning={loading}>
        {badges.length === 0 ? (
          <Empty description="暂无徽章，点击上方按钮创建" />
        ) : (
          <Row gutter={[16, 16]}>
            {badges.map((badge) => (
              <Col key={badge.id} xs={24} sm={12} md={8} lg={6}>
                <Card
                  hoverable
                  actions={[
                    <Tooltip title="编辑" key="edit">
                      <EditOutlined onClick={() => openEdit(badge)} />
                    </Tooltip>,
                    <Tooltip title="持有者" key="holders">
                      <TeamOutlined onClick={() => openHolders(badge)} />
                    </Tooltip>,
                    <Popconfirm
                      key="delete"
                      title="确认删除？"
                      onConfirm={() => handleDelete(badge.id)}
                    >
                      <DeleteOutlined />
                    </Popconfirm>,
                  ]}
                >
                  <Card.Meta
                    avatar={
                      badge.icon_url ? (
                        <img
                          src={badge.icon_url}
                          alt={badge.name}
                          style={{ width: 48, height: 48, borderRadius: 8 }}
                        />
                      ) : (
                        <TrophyOutlined style={{ fontSize: 36, color: '#faad14' }} />
                      )
                    }
                    title={badge.name}
                    description={badge.description || '无描述'}
                  />
                  <div style={{ marginTop: 12 }}>
                    {getCategoryTag(badge.category)}
                    {getRarityTag(badge.rarity)}
                  </div>
                  <div style={{ marginTop: 8 }}>
                    <Text type="secondary">积分奖励: {badge.points_reward}</Text>
                  </div>
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </Spin>

      {/* 创建/编辑弹窗 */}
      <Modal
        title={editingBadge ? '编辑徽章' : '新建徽章'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        width={600}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="徽章名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="category"
                label="分类"
                rules={[{ required: true, message: '请选择分类' }]}
              >
                <Select options={CATEGORIES} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="rarity" label="稀有度" initialValue="common">
                <Select options={RARITIES.map((r) => ({ value: r.value, label: r.label }))} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="rule_type" label="解锁规则类型" initialValue="visit_count">
                <Select options={RULE_TYPES} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="rule_threshold" label="阈值" initialValue={1}>
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="points_reward" label="积分奖励" initialValue={0}>
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

      {/* 持有者弹窗 */}
      <Modal
        title={`${selectedBadgeName} - 持有者`}
        open={holdersModalOpen}
        onCancel={() => setHoldersModalOpen(false)}
        footer={null}
        width={700}
      >
        <Spin spinning={holdersLoading}>
          <Table
            dataSource={holders}
            rowKey="customer_id"
            pagination={{ pageSize: 10 }}
            columns={[
              { title: '顾客ID', dataIndex: 'customer_id', key: 'customer_id', ellipsis: true },
              {
                title: '解锁时间',
                dataIndex: 'unlocked_at',
                key: 'unlocked_at',
                render: (v: string) => (v ? new Date(v).toLocaleString('zh-CN') : '-'),
              },
            ]}
          />
        </Spin>
      </Modal>
    </div>
  );
}
