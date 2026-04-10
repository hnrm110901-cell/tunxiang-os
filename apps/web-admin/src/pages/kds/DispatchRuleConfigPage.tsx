/**
 * 档口路由规则配置页面
 *
 * 功能：
 * - 门店选择
 * - 规则列表（上移/下移调整优先级）
 * - 每条规则：优先级 / 名称 / 触发条件 / 目标档口 / 启用状态
 * - 新建 / 编辑规则 ModalForm
 * - 规则测试：输入条件 → 显示路由结果
 * - 路由模拟：输入菜品 → 完整路由结果预览
 *
 * 设计规范：admin.md + tokens.md
 * API 来源：kdsManageApi.ts（/api/v1/dispatch-rules/...）
 */

import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Divider,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  DeleteOutlined,
  EditOutlined,
  ExperimentOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import {
  type DispatchRule,
  type DispatchRuleCreatePayload,
  type StoreOption,
  createDispatchRule,
  deleteDispatchRule,
  fetchProductionDepts,
  fetchStoreOptions,
  listDispatchRules,
  simulateDispatchRouting,
  testDispatchRule,
  updateDispatchRule,
} from '../../api/kdsManageApi';
import type { ProductionDept } from '../../api/kdsManageApi';

const { Title, Text, Paragraph } = Typography;

// ─── Design Token ──────────────────────────────────────────────────────────
const TX_PRIMARY = '#FF6B35';
const TX_SUCCESS = '#0F6E56';
const TX_WARNING = '#BA7517';
const TX_DANGER = '#A32D2D';
const TX_BG_SECONDARY = '#F8F7F5';
const TX_TEXT_SECONDARY = '#5F5E5A';

// ─── 常量 ──────────────────────────────────────────────────────────────────

const CHANNEL_LABELS: Record<string, string> = {
  dine_in: '堂食',
  takeaway: '外带',
  delivery: '外卖',
  reservation: '预订',
};

const DAY_TYPE_LABELS: Record<string, string> = {
  weekday: '工作日',
  weekend: '周末',
  holiday: '节假日',
};

const CHANNEL_OPTIONS = Object.entries(CHANNEL_LABELS).map(([v, l]) => ({ value: v, label: l }));
const DAY_TYPE_OPTIONS = Object.entries(DAY_TYPE_LABELS).map(([v, l]) => ({ value: v, label: l }));

// ─── 子组件：条件标签 ──────────────────────────────────────────────────────

function ConditionTags({ rule }: { rule: DispatchRule }) {
  const tags: React.ReactNode[] = [];

  if (rule.match_dish_id) {
    tags.push(
      <Tag key="dish" color="blue">菜品ID: {rule.match_dish_id.slice(0, 8)}…</Tag>,
    );
  }
  if (rule.match_dish_category) {
    tags.push(
      <Tag key="cat" color="purple">分类: {rule.match_dish_category}</Tag>,
    );
  }
  if (rule.match_channel) {
    tags.push(
      <Tag key="chan" color="cyan">渠道: {CHANNEL_LABELS[rule.match_channel] ?? rule.match_channel}</Tag>,
    );
  }
  if (rule.match_time_start && rule.match_time_end) {
    tags.push(
      <Tag key="time" color="geekblue">
        时段: {rule.match_time_start}–{rule.match_time_end}
      </Tag>,
    );
  }
  if (rule.match_day_type) {
    tags.push(
      <Tag key="day" color="volcano">
        {DAY_TYPE_LABELS[rule.match_day_type] ?? rule.match_day_type}
      </Tag>,
    );
  }
  if (rule.match_brand_id) {
    tags.push(
      <Tag key="brand" color="orange">品牌: {rule.match_brand_id.slice(0, 8)}…</Tag>,
    );
  }
  if (tags.length === 0) {
    return <Text type="secondary" style={{ fontSize: 12 }}>默认兜底</Text>;
  }
  return <Space size={4} wrap>{tags}</Space>;
}

// ─── 规则编辑 Modal ─────────────────────────────────────────────────────────

interface RuleModalProps {
  open: boolean;
  editingRule: DispatchRule | null;
  depts: ProductionDept[];
  onClose: () => void;
  onSaved: () => void;
  storeId: string;
}

function RuleModal({ open, editingRule, depts, onClose, onSaved, storeId }: RuleModalProps) {
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const isEdit = !!editingRule;

  useEffect(() => {
    if (open) {
      if (editingRule) {
        form.setFieldsValue({
          name: editingRule.name,
          priority: editingRule.priority,
          match_dish_category: editingRule.match_dish_category ?? undefined,
          match_dish_id: editingRule.match_dish_id ?? undefined,
          match_brand_id: editingRule.match_brand_id ?? undefined,
          match_channel: editingRule.match_channel ?? undefined,
          match_time_start: editingRule.match_time_start ?? undefined,
          match_time_end: editingRule.match_time_end ?? undefined,
          match_day_type: editingRule.match_day_type ?? undefined,
          target_dept_id: editingRule.target_dept_id,
          is_active: editingRule.is_active,
        });
      } else {
        form.resetFields();
        form.setFieldsValue({ priority: 0, is_active: true });
      }
    }
  }, [open, editingRule, form]);

  const handleOk = async () => {
    let values: Record<string, unknown>;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }

    setSaving(true);
    try {
      const payload: DispatchRuleCreatePayload = {
        name: values.name as string,
        priority: values.priority as number | undefined,
        match_dish_id: (values.match_dish_id as string) || null,
        match_dish_category: (values.match_dish_category as string) || null,
        match_brand_id: (values.match_brand_id as string) || null,
        match_channel: (values.match_channel as string) || null,
        match_time_start: (values.match_time_start as string) || null,
        match_time_end: (values.match_time_end as string) || null,
        match_day_type: (values.match_day_type as string) || null,
        target_dept_id: values.target_dept_id as string,
        is_active: values.is_active as boolean,
      };

      if (isEdit && editingRule) {
        await updateDispatchRule(editingRule.id, payload);
        message.success('规则已更新');
      } else {
        await createDispatchRule(storeId, payload);
        message.success('规则已创建');
      }
      onSaved();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '保存失败，请重试');
    } finally {
      setSaving(false);
    }
  };

  const deptOptions = depts.map((d) => ({
    value: d.id,
    label: `${d.dept_name}（${d.dept_code}）`,
  }));

  return (
    <Modal
      title={isEdit ? '编辑路由规则' : '新建路由规则'}
      open={open}
      onCancel={onClose}
      onOk={handleOk}
      confirmLoading={saving}
      okText={isEdit ? '保存修改' : '立即创建'}
      cancelText="取消"
      width={600}
      destroyOnClose
    >
      <Form form={form} layout="vertical" style={{ marginTop: 8 }}>
        <Row gutter={16}>
          <Col span={16}>
            <Form.Item
              name="name"
              label="规则名称"
              rules={[{ required: true, message: '请输入规则名称' }]}
            >
              <Input placeholder="如：热菜→热炒档，晚市堂食→VIP档口" maxLength={100} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item
              name="priority"
              label={
                <Tooltip title="数值越大越优先匹配，相同优先级按创建时间">
                  优先级
                </Tooltip>
              }
            >
              <Input type="number" placeholder="0" />
            </Form.Item>
          </Col>
        </Row>

        <Divider orientation="left" style={{ fontSize: 13, color: TX_TEXT_SECONDARY }}>
          触发条件（至少设置一项，或留空作为默认兜底）
        </Divider>

        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="match_dish_category" label="菜品分类">
              <Input placeholder="如：热菜、冷菜、主食" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="match_channel" label="渠道">
              <Select
                placeholder="不限渠道"
                allowClear
                options={CHANNEL_OPTIONS}
              />
            </Form.Item>
          </Col>
        </Row>

        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="match_time_start" label="时段开始（HH:MM）">
              <Input placeholder="如：11:00" pattern="^[0-2]\d:[0-5]\d$" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="match_time_end" label="时段结束（HH:MM）">
              <Input placeholder="如：14:00" pattern="^[0-2]\d:[0-5]\d$" />
            </Form.Item>
          </Col>
        </Row>

        <Row gutter={16}>
          <Col span={12}>
            <Form.Item name="match_day_type" label="工作日类型">
              <Select
                placeholder="不限"
                allowClear
                options={DAY_TYPE_OPTIONS}
              />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="match_dish_id" label="指定菜品ID（UUID）">
              <Input placeholder="精确匹配菜品" />
            </Form.Item>
          </Col>
        </Row>

        <Form.Item name="match_brand_id" label="品牌ID（UUID，多品牌场景）">
          <Input placeholder="不填则不限品牌" />
        </Form.Item>

        <Divider orientation="left" style={{ fontSize: 13, color: TX_TEXT_SECONDARY }}>
          路由目标
        </Divider>

        <Row gutter={16}>
          <Col span={16}>
            <Form.Item
              name="target_dept_id"
              label="目标档口"
              rules={[{ required: true, message: '请选择目标档口' }]}
            >
              <Select
                placeholder="选择档口"
                options={deptOptions}
                showSearch
                optionFilterProp="label"
              />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="is_active" label="启用状态" valuePropName="checked">
              <Switch checkedChildren="启用" unCheckedChildren="禁用" />
            </Form.Item>
          </Col>
        </Row>
      </Form>
    </Modal>
  );
}

// ─── 规则测试面板 ──────────────────────────────────────────────────────────

interface TestPanelProps {
  storeId: string;
  rules: DispatchRule[];
  depts: ProductionDept[];
}

function TestPanel({ storeId, rules, depts }: TestPanelProps) {
  const [form] = Form.useForm();
  const [testing, setTesting] = useState(false);
  const [simResult, setSimResult] = useState<{
    matched: boolean;
    deptName?: string;
    deptCode?: string;
    deptId?: string;
  } | null>(null);

  const handleSimulate = async () => {
    let values: Record<string, unknown>;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    if (!values.dish_id) {
      message.warning('请输入菜品ID');
      return;
    }
    setTesting(true);
    setSimResult(null);
    try {
      const result = await simulateDispatchRouting(storeId, {
        dish_id: values.dish_id as string,
        dish_category: (values.dish_category as string) || undefined,
        channel: (values.channel as string) || undefined,
        order_time: (values.order_time as string) || undefined,
      });
      if (result.matched && result.dept) {
        setSimResult({
          matched: true,
          deptName: result.dept.dept_name,
          deptCode: result.dept.dept_code,
          deptId: result.dept.dept_id,
        });
      } else {
        setSimResult({ matched: false });
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : '模拟失败');
    } finally {
      setTesting(false);
    }
  };

  return (
    <Card
      title={
        <Space>
          <ExperimentOutlined style={{ color: TX_PRIMARY }} />
          <span>路由模拟测试</span>
        </Space>
      }
      style={{ marginTop: 24 }}
    >
      <Paragraph style={{ color: TX_TEXT_SECONDARY, fontSize: 13, marginBottom: 16 }}>
        输入菜品信息，模拟该订单项会被路由到哪个档口（按实际生效规则匹配）。
      </Paragraph>

      <Form form={form} layout="inline" style={{ flexWrap: 'wrap', gap: 8 }}>
        <Form.Item name="dish_id" label="菜品ID" rules={[{ required: true }]}>
          <Input placeholder="UUID" style={{ width: 200 }} />
        </Form.Item>
        <Form.Item name="dish_category" label="分类">
          <Input placeholder="如：热菜" style={{ width: 120 }} />
        </Form.Item>
        <Form.Item name="channel" label="渠道">
          <Select placeholder="不限" allowClear options={CHANNEL_OPTIONS} style={{ width: 110 }} />
        </Form.Item>
        <Form.Item>
          <Button
            type="primary"
            loading={testing}
            onClick={handleSimulate}
            style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
          >
            开始模拟
          </Button>
        </Form.Item>
      </Form>

      {simResult && (
        <div style={{ marginTop: 16 }}>
          {simResult.matched ? (
            <Alert
              type="success"
              showIcon
              message={
                <Space>
                  <span>路由结果：</span>
                  <Tag color="green" style={{ fontSize: 14, padding: '2px 10px' }}>
                    {simResult.deptName}（{simResult.deptCode}）
                  </Tag>
                </Space>
              }
            />
          ) : (
            <Alert
              type="warning"
              showIcon
              message="未匹配任何规则 — 将使用系统默认档口（无默认则不路由）"
            />
          )}
        </div>
      )}

      {rules.length === 0 && (
        <Alert
          type="info"
          style={{ marginTop: 16 }}
          message="当前门店暂无路由规则，请先新建规则再使用模拟功能。"
        />
      )}
    </Card>
  );
}

// ─── 主页面 ────────────────────────────────────────────────────────────────

export const DispatchRuleConfigPage: React.FC = () => {
  const [stores, setStores] = useState<StoreOption[]>([]);
  const [storeId, setStoreId] = useState<string>('');
  const [rules, setRules] = useState<DispatchRule[]>([]);
  const [depts, setDepts] = useState<ProductionDept[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<DispatchRule | null>(null);

  // 加载门店列表
  useEffect(() => {
    fetchStoreOptions().then((opts) => {
      setStores(opts);
      if (opts.length > 0 && !storeId) {
        setStoreId(opts[0].value);
      }
    });
  }, []);

  // 加载规则列表 + 档口列表
  const loadData = useCallback(async () => {
    if (!storeId) return;
    setLoading(true);
    try {
      const [ruleList, deptList] = await Promise.all([
        listDispatchRules(storeId),
        fetchProductionDepts(storeId),
      ]);
      setRules(ruleList);
      setDepts(deptList);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [storeId]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  // 构建档口 ID→名称 映射
  const deptMap = Object.fromEntries(depts.map((d) => [d.id, d.dept_name]));

  // 上移/下移：通过互换 priority 实现
  const handleMove = async (index: number, direction: 'up' | 'down') => {
    const targetIndex = direction === 'up' ? index - 1 : index + 1;
    if (targetIndex < 0 || targetIndex >= rules.length) return;

    const ruleA = rules[index];
    const ruleB = rules[targetIndex];
    const tempPriority = ruleA.priority;

    try {
      await Promise.all([
        updateDispatchRule(ruleA.id, { priority: ruleB.priority }),
        updateDispatchRule(ruleB.id, { priority: tempPriority }),
      ]);
      message.success('优先级已调整');
      void loadData();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '调整失败');
    }
  };

  // 删除规则
  const handleDelete = async (ruleId: string) => {
    try {
      await deleteDispatchRule(ruleId);
      message.success('规则已删除');
      void loadData();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '删除失败');
    }
  };

  // 快速切换启用状态
  const handleToggleActive = async (rule: DispatchRule, active: boolean) => {
    try {
      await updateDispatchRule(rule.id, { is_active: active });
      message.success(active ? '规则已启用' : '规则已禁用');
      void loadData();
    } catch (err) {
      message.error(err instanceof Error ? err.message : '操作失败');
    }
  };

  const columns: ColumnsType<DispatchRule> = [
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: 80,
      render: (val: number) => (
        <Tag color={val > 50 ? 'red' : val > 10 ? 'orange' : 'default'}>{val}</Tag>
      ),
    },
    {
      title: '规则名称',
      dataIndex: 'name',
      key: 'name',
      width: 160,
      render: (name: string) => <Text strong>{name}</Text>,
    },
    {
      title: '触发条件',
      key: 'conditions',
      render: (_: unknown, rule: DispatchRule) => <ConditionTags rule={rule} />,
    },
    {
      title: '目标档口',
      dataIndex: 'target_dept_id',
      key: 'target_dept_id',
      width: 140,
      render: (deptId: string) => (
        <Tag color="green" style={{ fontWeight: 500 }}>
          {deptMap[deptId] ?? deptId.slice(0, 8) + '…'}
        </Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 90,
      render: (active: boolean, rule: DispatchRule) => (
        <Switch
          size="small"
          checked={active}
          onChange={(checked) => handleToggleActive(rule, checked)}
          checkedChildren="启用"
          unCheckedChildren="禁用"
        />
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      render: (_: unknown, rule: DispatchRule, index: number) => (
        <Space size={4}>
          <Tooltip title="上移（提高优先级）">
            <Button
              size="small"
              icon={<ArrowUpOutlined />}
              disabled={index === 0}
              onClick={() => handleMove(index, 'up')}
            />
          </Tooltip>
          <Tooltip title="下移（降低优先级）">
            <Button
              size="small"
              icon={<ArrowDownOutlined />}
              disabled={index === rules.length - 1}
              onClick={() => handleMove(index, 'down')}
            />
          </Tooltip>
          <Tooltip title="编辑">
            <Button
              size="small"
              icon={<EditOutlined />}
              onClick={() => {
                setEditingRule(rule);
                setModalOpen(true);
              }}
            />
          </Tooltip>
          <Popconfirm
            title="确认删除该规则？"
            description="删除后不可恢复，相关订单将使用默认路由。"
            onConfirm={() => handleDelete(rule.id)}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Tooltip title="删除">
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      {/* 页面标题 */}
      <div style={{ marginBottom: 24 }}>
        <Title level={2} style={{ margin: 0, color: '#2C2C2A' }}>
          档口路由规则配置
        </Title>
        <Paragraph style={{ color: TX_TEXT_SECONDARY, margin: '8px 0 0', fontSize: 14 }}>
          配置菜品/分类/渠道/时段到对应档口的自动路由规则。规则按优先级从高到低依次匹配，命中即路由。
        </Paragraph>
      </div>

      {/* 门店选择 + 工具栏 */}
      <Card
        style={{ marginBottom: 24 }}
        styles={{ body: { padding: '16px 24px' } }}
      >
        <Space size={16} wrap>
          <Space>
            <Text strong>门店：</Text>
            <Select
              options={stores}
              value={storeId || undefined}
              onChange={(v) => setStoreId(v)}
              placeholder="选择门店"
              style={{ width: 220 }}
              showSearch
              optionFilterProp="label"
            />
          </Space>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => void loadData()}
            loading={loading}
          >
            刷新
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            disabled={!storeId}
            onClick={() => {
              setEditingRule(null);
              setModalOpen(true);
            }}
            style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
          >
            新建规则
          </Button>
        </Space>
      </Card>

      {/* 规则列表 */}
      <Card>
        {!storeId ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="请先选择门店"
          />
        ) : rules.length === 0 && !loading ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_DEFAULT}
            description={
              <Space direction="vertical" align="center">
                <Text style={{ color: TX_TEXT_SECONDARY }}>暂无规则，点击新建开始配置</Text>
                <Button
                  type="primary"
                  icon={<PlusOutlined />}
                  onClick={() => {
                    setEditingRule(null);
                    setModalOpen(true);
                  }}
                  style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
                >
                  新建第一条规则
                </Button>
              </Space>
            }
          />
        ) : (
          <Table<DispatchRule>
            columns={columns}
            dataSource={rules}
            rowKey="id"
            loading={loading}
            pagination={{ defaultPageSize: 20, showSizeChanger: true }}
            size="middle"
            rowClassName={(rule) =>
              rule.is_active ? '' : 'ant-table-row-disabled'
            }
            style={{ '--row-disabled-opacity': '0.5' } as React.CSSProperties}
          />
        )}

        {/* 图例说明 */}
        {rules.length > 0 && (
          <div
            style={{
              marginTop: 12,
              padding: '8px 16px',
              background: TX_BG_SECONDARY,
              borderRadius: 6,
              fontSize: 12,
              color: TX_TEXT_SECONDARY,
            }}
          >
            规则按优先级从高到低匹配 · 命中第一条即停止 · 未匹配规则使用系统默认档口
          </div>
        )}
      </Card>

      {/* 路由模拟测试 */}
      {storeId && (
        <TestPanel storeId={storeId} rules={rules} depts={depts} />
      )}

      {/* 规则编辑 Modal */}
      <RuleModal
        open={modalOpen}
        editingRule={editingRule}
        depts={depts}
        storeId={storeId}
        onClose={() => setModalOpen(false)}
        onSaved={() => {
          setModalOpen(false);
          void loadData();
        }}
      />
    </div>
  );
};

export default DispatchRuleConfigPage;
