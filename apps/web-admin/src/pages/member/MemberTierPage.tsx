/**
 * MemberTierPage — 会员等级体系管理
 * 等级分布概览 / 等级配置编辑 / 升降级记录 / 权益对比表
 */
import { useState, useEffect } from 'react';
import {
  Card,
  Col,
  Row,
  Tag,
  Button,
  Table,
  Timeline,
  Typography,
  Space,
  Statistic,
  Spin,
  message,
  Input,
  InputNumber,
  Form,
  Tooltip,
} from 'antd';
import {
  TrophyOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
  SaveOutlined,
  PlusOutlined,
  CloseOutlined,
} from '@ant-design/icons';
import { ConfigProvider } from 'antd';
import { txFetch } from '../../api';

const { Title, Text } = Typography;

// ─── 类型 ───────────────────────────────────────────────────────────────────

interface Tier {
  id: string;
  level: number;
  name: string;
  min_points: number;
  min_spend_fen: number;
  benefits: string[];
  discount_rate: number;
  points_multiplier: number;
  birthday_bonus_fen: number;
  free_delivery_threshold_fen: number;
  color: string;
  icon: string;
  member_count: number;
  percentage: number;
}

interface UpgradeLogItem {
  id: string;
  customer_id: string;
  customer_name: string;
  from_tier: string;
  to_tier: string;
  trigger: string;
  reason?: string;
  points_at_upgrade?: number;
  spend_total_fen?: number;
  upgraded_at: string;
}

// ─── 编辑标签组件 ─────────────────────────────────────────────────────────────

function EditableTagGroup({
  value,
  onChange,
}: {
  value: string[];
  onChange: (v: string[]) => void;
}) {
  const [inputVal, setInputVal] = useState('');
  const [adding, setAdding] = useState(false);

  const remove = (tag: string) => onChange(value.filter((t) => t !== tag));
  const add = () => {
    const trimmed = inputVal.trim();
    if (trimmed && !value.includes(trimmed)) {
      onChange([...value, trimmed]);
    }
    setInputVal('');
    setAdding(false);
  };

  return (
    <Space size={4} wrap>
      {value.map((tag) => (
        <Tag
          key={tag}
          closable
          onClose={() => remove(tag)}
          style={{ fontSize: 12 }}
        >
          {tag}
        </Tag>
      ))}
      {adding ? (
        <Input
          size="small"
          style={{ width: 120 }}
          value={inputVal}
          onChange={(e) => setInputVal(e.target.value)}
          onPressEnter={add}
          onBlur={add}
          autoFocus
          suffix={<CloseOutlined onClick={() => setAdding(false)} style={{ cursor: 'pointer', fontSize: 10 }} />}
        />
      ) : (
        <Tag
          style={{ cursor: 'pointer', borderStyle: 'dashed' }}
          icon={<PlusOutlined />}
          onClick={() => setAdding(true)}
        >
          添加权益
        </Tag>
      )}
    </Space>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export function MemberTierPage() {
  const [tiers, setTiers] = useState<Tier[]>([]);
  const [upgradeLog, setUpgradeLog] = useState<UpgradeLogItem[]>([]);
  const [upgradeCount, setUpgradeCount] = useState(0);
  const [downgradeCount, setDowngradeCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [logLoading, setLogLoading] = useState(true);
  const [selectedTier, setSelectedTier] = useState<Tier | null>(null);
  const [saving, setSaving] = useState(false);

  // 编辑态字段
  const [editBenefits, setEditBenefits] = useState<string[]>([]);
  const [form] = Form.useForm();

  // ── 数据加载 ──
  useEffect(() => {
    txFetch<{ tiers: Tier[]; total_members: number }>('/api/v1/member/tiers')
      .then((data) => {
        setTiers(data.tiers);
        if (data.tiers.length > 0) {
          setSelectedTier(data.tiers[0]);
          setEditBenefits(data.tiers[0].benefits);
          form.setFieldsValue(tierToForm(data.tiers[0]));
        }
      })
      .catch(() => message.error('加载等级配置失败'))
      .finally(() => setLoading(false));

    txFetch<{ items: UpgradeLogItem[]; upgrade_count: number; downgrade_count: number }>(
      '/api/v1/member/tiers/upgrade-log?days=7'
    )
      .then((data) => {
        setUpgradeLog(data.items);
        setUpgradeCount(data.upgrade_count);
        setDowngradeCount(data.downgrade_count);
      })
      .catch(() => message.error('加载升降级记录失败'))
      .finally(() => setLogLoading(false));
  }, []);

  const tierToForm = (t: Tier) => ({
    min_points: t.min_points,
    min_spend_fen: Math.round(t.min_spend_fen / 1000) / 10,
    discount_rate: Math.round(t.discount_rate * 100),
    points_multiplier: t.points_multiplier,
    birthday_bonus_fen: t.birthday_bonus_fen / 100,
    free_delivery_threshold_fen: t.free_delivery_threshold_fen / 100,
    color: t.color,
  });

  const selectTier = (tier: Tier) => {
    setSelectedTier(tier);
    setEditBenefits([...tier.benefits]);
    form.setFieldsValue(tierToForm(tier));
  };

  const handleSave = async () => {
    if (!selectedTier) return;
    try {
      const vals = await form.validateFields();
      setSaving(true);
      const body = {
        name: selectedTier.name,
        min_points: vals.min_points,
        min_spend_fen: Math.round(vals.min_spend_fen * 1000 * 10),
        benefits: editBenefits,
        discount_rate: vals.discount_rate / 100,
        points_multiplier: vals.points_multiplier,
        birthday_bonus_fen: Math.round(vals.birthday_bonus_fen * 100),
        free_delivery_threshold_fen: Math.round(vals.free_delivery_threshold_fen * 100),
        color: vals.color,
        icon: selectedTier.icon,
      };
      await txFetch(`/api/v1/member/tiers/${selectedTier.id}`, {
        method: 'PUT',
        body: JSON.stringify(body),
      });
      message.success('等级配置已保存（Mock）');
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  // ── 权益对比表数据 ──
  const comparisonRows = [
    {
      key: 'discount',
      benefit: '折扣率',
      render: (t: Tier) => (
        <Text strong={t.discount_rate === Math.min(...tiers.map((x) => x.discount_rate))} style={t.discount_rate === Math.min(...tiers.map((x) => x.discount_rate)) ? { color: '#FF6B35' } : {}}>
          {t.discount_rate === 1.0 ? '无折扣' : `${(t.discount_rate * 10).toFixed(1)}折`}
        </Text>
      ),
    },
    {
      key: 'points_multiplier',
      benefit: '积分倍率',
      render: (t: Tier) => (
        <Text strong={t.points_multiplier === Math.max(...tiers.map((x) => x.points_multiplier))} style={t.points_multiplier === Math.max(...tiers.map((x) => x.points_multiplier)) ? { color: '#FF6B35' } : {}}>
          {t.points_multiplier}x
        </Text>
      ),
    },
    {
      key: 'birthday',
      benefit: '生日红包',
      render: (t: Tier) => (
        <Text strong={t.birthday_bonus_fen === Math.max(...tiers.map((x) => x.birthday_bonus_fen))} style={t.birthday_bonus_fen === Math.max(...tiers.map((x) => x.birthday_bonus_fen)) ? { color: '#FF6B35' } : {}}>
          ¥{(t.birthday_bonus_fen / 100).toFixed(0)}
        </Text>
      ),
    },
    {
      key: 'delivery',
      benefit: '免配送费门槛',
      render: (t: Tier) => (
        <Text>
          {t.free_delivery_threshold_fen === 0 ? (
            <Tag color="gold">无条件免费</Tag>
          ) : (
            `满¥${(t.free_delivery_threshold_fen / 100).toFixed(0)}`
          )}
        </Text>
      ),
    },
    {
      key: 'benefits_count',
      benefit: '专属权益数',
      render: (t: Tier) => (
        <Text strong={t.benefits.length === Math.max(...tiers.map((x) => x.benefits.length))} style={t.benefits.length === Math.max(...tiers.map((x) => x.benefits.length)) ? { color: '#FF6B35' } : {}}>
          {t.benefits.length} 项
        </Text>
      ),
    },
  ];

  const comparisonColumns = [
    { title: '权益项目', dataIndex: 'benefit', key: 'benefit', width: 120, fixed: 'left' as const },
    ...tiers.map((tier) => ({
      title: (
        <Space>
          <span>{tier.icon}</span>
          <span style={{ color: tier.color }}>{tier.name}</span>
        </Space>
      ),
      key: tier.id,
      align: 'center' as const,
      render: (_: unknown, row: typeof comparisonRows[0]) => row.render(tier),
    })),
  ];

  const comparisonData = comparisonRows.map((r) => ({ key: r.key, benefit: r.benefit, ...r }));

  // ── Timeline 渲染 ──
  const timelineItems = upgradeLog.map((item) => {
    const isDowngrade = item.trigger === 'downgrade';
    const triggerLabel =
      item.trigger === 'points' ? '积分达标'
      : item.trigger === 'spend' ? '消费达标'
      : item.reason || '年度评估';
    return {
      color: isDowngrade ? 'red' : 'green',
      dot: isDowngrade ? (
        <ArrowDownOutlined style={{ color: '#ff4d4f', fontSize: 12 }} />
      ) : (
        <ArrowUpOutlined style={{ color: '#52c41a', fontSize: 12 }} />
      ),
      children: (
        <div style={{ paddingBottom: 8 }}>
          <Text strong>{item.customer_name}</Text>
          <Text style={{ margin: '0 6px', color: '#999' }}>
            {item.from_tier} → {item.to_tier}
          </Text>
          <Tag color={isDowngrade ? 'error' : 'success'} style={{ fontSize: 11 }}>
            {triggerLabel}
          </Tag>
          <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>
            {new Date(item.upgraded_at).toLocaleString('zh-CN')}
          </div>
        </div>
      ),
    };
  });

  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#FF6B35' } }}>
      <div style={{ padding: '20px 24px', background: '#f5f5f5', minHeight: '100vh' }}>
        <div style={{ marginBottom: 20 }}>
          <Title level={4} style={{ margin: 0 }}>
            <TrophyOutlined style={{ marginRight: 8, color: '#FF6B35' }} />
            会员等级体系
          </Title>
          <Text type="secondary">管理等级门槛、权益配置与升降级规则</Text>
        </div>

        {/* ── 顶部：等级分布卡片 ── */}
        <Spin spinning={loading}>
          <Row gutter={16} style={{ marginBottom: 20 }}>
            {tiers.map((tier) => {
              const isSelected = selectedTier?.id === tier.id;
              return (
                <Col key={tier.id} xs={24} sm={12} md={6}>
                  <Card
                    hoverable
                    onClick={() => selectTier(tier)}
                    style={{
                      cursor: 'pointer',
                      border: isSelected ? `2px solid ${tier.color}` : '2px solid transparent',
                      borderRadius: 12,
                      background: isSelected
                        ? `linear-gradient(135deg, ${tier.color}18 0%, ${tier.color}08 100%)`
                        : '#fff',
                      transition: 'all 0.2s',
                    }}
                    bodyStyle={{ padding: '16px 20px' }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
                      <span style={{ fontSize: 28 }}>{tier.icon}</span>
                      <div>
                        <div style={{ fontWeight: 700, fontSize: 14, color: tier.color }}>
                          {tier.name}
                        </div>
                        <div style={{ fontSize: 11, color: '#999' }}>
                          Lv.{tier.level}
                        </div>
                      </div>
                    </div>
                    <Statistic
                      value={tier.member_count}
                      suffix="人"
                      valueStyle={{ fontSize: 22, fontWeight: 700, color: tier.color }}
                    />
                    <div style={{ marginTop: 6 }}>
                      <div style={{
                        height: 4, borderRadius: 2, background: '#f0f0f0', overflow: 'hidden',
                      }}>
                        <div style={{
                          width: `${tier.percentage}%`, height: '100%',
                          background: tier.color, borderRadius: 2,
                          transition: 'width 0.6s ease',
                        }} />
                      </div>
                      <Text type="secondary" style={{ fontSize: 11, marginTop: 4, display: 'block' }}>
                        占比 {tier.percentage}%
                      </Text>
                    </div>
                  </Card>
                </Col>
              );
            })}
          </Row>
        </Spin>

        {/* ── 中部：配置编辑 + 升降级记录 ── */}
        <Row gutter={16} style={{ marginBottom: 20 }}>
          {/* 左栏：等级配置编辑 */}
          <Col xs={24} md={10}>
            <Card
              title={
                selectedTier ? (
                  <Space>
                    <span style={{ fontSize: 18 }}>{selectedTier.icon}</span>
                    <span style={{ color: selectedTier.color }}>{selectedTier.name}</span>
                    <Text type="secondary" style={{ fontSize: 12 }}>配置编辑</Text>
                  </Space>
                ) : '选择等级'
              }
              extra={
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  loading={saving}
                  onClick={handleSave}
                  disabled={!selectedTier}
                >
                  保存配置
                </Button>
              }
              style={{ borderRadius: 12 }}
            >
              {selectedTier ? (
                <Form form={form} layout="vertical" size="small">
                  <Row gutter={12}>
                    <Col span={12}>
                      <Form.Item
                        label="升级积分门槛"
                        name="min_points"
                        rules={[{ required: true }]}
                      >
                        <InputNumber
                          min={0}
                          style={{ width: '100%' }}
                          addonAfter="分"
                        />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Form.Item
                        label="升级消费门槛"
                        name="min_spend_fen"
                        rules={[{ required: true }]}
                      >
                        <InputNumber
                          min={0}
                          step={0.1}
                          precision={1}
                          style={{ width: '100%' }}
                          addonAfter="万元"
                        />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Form.Item
                        label="折扣率"
                        name="discount_rate"
                        rules={[{ required: true }]}
                      >
                        <InputNumber
                          min={50}
                          max={100}
                          style={{ width: '100%' }}
                          addonAfter="%"
                        />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Form.Item
                        label="积分倍率"
                        name="points_multiplier"
                        rules={[{ required: true }]}
                      >
                        <InputNumber
                          min={1}
                          max={10}
                          step={0.1}
                          precision={1}
                          style={{ width: '100%' }}
                          addonAfter="x"
                        />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Form.Item
                        label="生日红包"
                        name="birthday_bonus_fen"
                        rules={[{ required: true }]}
                      >
                        <InputNumber
                          min={0}
                          step={1}
                          style={{ width: '100%' }}
                          addonAfter="元"
                        />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Tooltip title="填 0 表示无条件免配送费">
                        <Form.Item
                          label="免配送费门槛"
                          name="free_delivery_threshold_fen"
                          rules={[{ required: true }]}
                        >
                          <InputNumber
                            min={0}
                            step={1}
                            style={{ width: '100%' }}
                            addonAfter="元"
                          />
                        </Form.Item>
                      </Tooltip>
                    </Col>
                    <Col span={12}>
                      <Form.Item label="展示颜色" name="color">
                        <Input
                          type="color"
                          style={{ width: '100%', height: 32, padding: '2px 4px' }}
                        />
                      </Form.Item>
                    </Col>
                  </Row>
                  <Form.Item label="等级权益">
                    <EditableTagGroup
                      value={editBenefits}
                      onChange={setEditBenefits}
                    />
                  </Form.Item>
                </Form>
              ) : (
                <div style={{ textAlign: 'center', padding: '40px 0', color: '#999' }}>
                  点击顶部等级卡片选择要编辑的等级
                </div>
              )}
            </Card>
          </Col>

          {/* 右栏：升降级记录 */}
          <Col xs={24} md={14}>
            <Card
              title="近7天升降级记录"
              extra={
                <Space>
                  <Tag color="success" icon={<ArrowUpOutlined />}>
                    升级 {upgradeCount} 人
                  </Tag>
                  <Tag color="error" icon={<ArrowDownOutlined />}>
                    降级 {downgradeCount} 人
                  </Tag>
                </Space>
              }
              style={{ borderRadius: 12 }}
            >
              <Spin spinning={logLoading}>
                {upgradeLog.length > 0 ? (
                  <Timeline items={timelineItems} style={{ marginTop: 8 }} />
                ) : (
                  <div style={{ textAlign: 'center', padding: '40px 0', color: '#999' }}>
                    暂无升降级记录
                  </div>
                )}
              </Spin>
            </Card>
          </Col>
        </Row>

        {/* ── 底部：权益对比表 ── */}
        <Card
          title="等级权益横向对比"
          style={{ borderRadius: 12 }}
        >
          <Table
            dataSource={comparisonData}
            columns={comparisonColumns}
            pagination={false}
            size="middle"
            scroll={{ x: 600 }}
            rowKey="key"
          />
        </Card>
      </div>
    </ConfigProvider>
  );
}
