/**
 * SplitRuleManagePage — 分润规则管理
 *
 * 管理 profit_split_rules 表的 CRUD：
 *   - 规则列表 ProTable（名称 / 收款方类型 / 分账方式 / 比例金额 / 门店数 / 优先级 / 启用状态 / 操作）
 *   - 新建/编辑规则 Modal
 *   - 启用/停用 Switch
 *   - 停用 Popconfirm
 *
 * API：/api/v1/finance/splits/rules
 * Admin 终端规范：Ant Design 5.x + ProComponents + 1280px 最小宽度
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Button,
  Col,
  DatePicker,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Switch,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import {
  DeleteOutlined,
  EditOutlined,
  LinkOutlined,
  PlusOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons';
import { ActionType, ProColumns, ProTable } from '@ant-design/pro-components';
import dayjs from 'dayjs';
import { formatPrice } from '@tx-ds/utils';

const { Title, Text } = Typography;

// ── 常量 ──────────────────────────────────────────────────────────────────────

const RECIPIENT_TYPES = ['brand', 'franchise', 'supplier', 'platform', 'custom'] as const;
const SPLIT_METHODS = ['percentage', 'fixed_fen'] as const;
const CHANNEL_OPTIONS = ['dine_in', 'meituan', 'eleme', 'douyin'];

const RECIPIENT_TYPE_LABELS: Record<string, string> = {
  brand: '品牌',
  franchise: '加盟商',
  supplier: '供应商',
  platform: '平台',
  custom: '自定义',
};

const RECIPIENT_TYPE_COLORS: Record<string, string> = {
  brand: 'purple',
  franchise: 'orange',
  supplier: 'blue',
  platform: 'cyan',
  custom: 'default',
};

const SPLIT_METHOD_LABELS: Record<string, string> = {
  percentage: '按比例',
  fixed_fen: '固定金额',
};

const CHANNEL_LABELS: Record<string, string> = {
  dine_in: '堂食',
  meituan: '美团',
  eleme: '饿了么',
  douyin: '抖音',
};

// ── 类型定义 ─────────────────────────────────────────────────────────────────

interface SplitRule {
  rule_id: string;
  tenant_id: string;
  name: string;
  recipient_type: string;
  recipient_id: string | null;
  split_method: string;
  percentage: number | null;
  fixed_fen: number | null;
  applicable_stores: string[];
  applicable_channels: string[];
  priority: number;
  is_active: boolean;
  valid_from: string | null;
  valid_to: string | null;
  created_at: string | null;
  updated_at: string | null;
}

interface RuleFormValues {
  id?: string;
  name: string;
  recipient_type: string;
  recipient_id?: string;
  split_method: string;
  percentage?: number;
  fixed_fen?: number;
  applicable_stores: string[];
  applicable_channels: string[];
  priority: number;
  is_active: boolean;
  valid_from?: string;
  valid_to?: string;
}

// ── 工具函数 ─────────────────────────────────────────────────────────────────

const getTenantId = (): string =>
  localStorage.getItem('tx_tenant_id') ?? '';

const apiRequest = async <T,>(
  path: string,
  options: RequestInit = {},
): Promise<T> => {
  const resp = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': getTenantId(),
      ...options.headers,
    },
  });
  const json = await resp.json();
  if (!json.ok) {
    throw new Error(json.error?.message ?? '请求失败');
  }
  return json.data as T;
};

// ── 主页面 ──────────────────────────────────────────────────────────────────

const SplitRuleManagePage: React.FC = () => {
  const navigate = useNavigate();
  const actionRef = useRef<ActionType>();
  const [modalOpen, setModalOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<SplitRule | null>(null);
  const [confirmLoading, setConfirmLoading] = useState(false);
  const [form] = Form.useForm<RuleFormValues>();

  // 监听分账方式切换
  const splitMethod = Form.useWatch('split_method', form);

  // ── 打开新建/编辑 Modal ──────────────────────────────────────────────────

  const openCreateModal = () => {
    setEditingRule(null);
    form.resetFields();
    form.setFieldsValue({
      is_active: true,
      priority: 0,
      applicable_stores: [],
      applicable_channels: [],
    });
    setModalOpen(true);
  };

  const openEditModal = (rule: SplitRule) => {
    setEditingRule(rule);
    form.setFieldsValue({
      id: rule.rule_id,
      name: rule.name,
      recipient_type: rule.recipient_type,
      recipient_id: rule.recipient_id ?? undefined,
      split_method: rule.split_method,
      percentage: rule.percentage ?? undefined,
      fixed_fen: rule.fixed_fen ?? undefined,
      applicable_stores: rule.applicable_stores ?? [],
      applicable_channels: rule.applicable_channels ?? [],
      priority: rule.priority,
      is_active: rule.is_active,
      valid_from: rule.valid_from ?? undefined,
      valid_to: rule.valid_to ?? undefined,
    });
    setModalOpen(true);
  };

  // ── 提交规则 ─────────────────────────────────────────────────────────────

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setConfirmLoading(true);

      const body: Record<string, unknown> = {
        name: values.name,
        recipient_type: values.recipient_type,
        recipient_id: values.recipient_id || null,
        split_method: values.split_method,
        priority: values.priority ?? 0,
        is_active: values.is_active ?? true,
        applicable_stores: values.applicable_stores ?? [],
        applicable_channels: values.applicable_channels ?? [],
        valid_from: values.valid_from ?? null,
        valid_to: values.valid_to ?? null,
      };

      if (values.split_method === 'percentage') {
        body.percentage = values.percentage !== undefined ? values.percentage / 100 : undefined;
      } else {
        body.fixed_fen = values.fixed_fen;
      }

      // 编辑时传 id
      if (values.id) {
        body.id = values.id;
      }

      await apiRequest('/api/v1/finance/splits/rules', {
        method: 'POST',
        body: JSON.stringify(body),
      });

      message.success(values.id ? '规则已更新' : '规则已创建');
      setModalOpen(false);
      form.resetFields();
      actionRef.current?.reload();
    } catch (err: unknown) {
      message.error((err as Error).message ?? '保存失败');
    } finally {
      setConfirmLoading(false);
    }
  };

  // ── 切换启用状态 ─────────────────────────────────────────────────────────

  const handleToggleActive = async (rule: SplitRule, checked: boolean) => {
    try {
      if (checked) {
        // 重新启用：调用 upsert（POST with id + is_active=true）
        await apiRequest('/api/v1/finance/splits/rules', {
          method: 'POST',
          body: JSON.stringify({
            id: rule.rule_id,
            name: rule.name,
            recipient_type: rule.recipient_type,
            recipient_id: rule.recipient_id,
            split_method: rule.split_method,
            percentage: rule.percentage,
            fixed_fen: rule.fixed_fen,
            applicable_stores: rule.applicable_stores,
            applicable_channels: rule.applicable_channels,
            priority: rule.priority,
            is_active: true,
            valid_from: rule.valid_from,
            valid_to: rule.valid_to,
          }),
        });
        message.success(`规则「${rule.name}」已启用`);
      } else {
        // 停用：调用 DELETE
        await apiRequest(`/api/v1/finance/splits/rules/${rule.rule_id}`, {
          method: 'DELETE',
        });
        message.success(`规则「${rule.name}」已停用`);
      }
      actionRef.current?.reload();
    } catch (err: unknown) {
      message.error((err as Error).message ?? '操作失败');
    }
  };

  // ── 停用规则 ─────────────────────────────────────────────────────────────

  const handleDeactivate = async (rule: SplitRule) => {
    try {
      await apiRequest(`/api/v1/finance/splits/rules/${rule.rule_id}`, {
        method: 'DELETE',
      });
      message.success(`规则「${rule.name}」已停用`);
      actionRef.current?.reload();
    } catch (err: unknown) {
      message.error((err as Error).message ?? '停用失败');
    }
  };

  // ── ProTable 列定义 ──────────────────────────────────────────────────────

  const columns: ProColumns<SplitRule>[] = [
    {
      title: '规则名称',
      dataIndex: 'name',
      width: 160,
      ellipsis: true,
      copyable: true,
    },
    {
      title: '收款方类型',
      dataIndex: 'recipient_type',
      width: 110,
      valueType: 'select',
      valueEnum: {
        brand: { text: '品牌' },
        franchise: { text: '加盟商' },
        supplier: { text: '供应商' },
        platform: { text: '平台' },
        custom: { text: '自定义' },
      },
      render: (_, r) => (
        <Tag color={RECIPIENT_TYPE_COLORS[r.recipient_type]}>
          {RECIPIENT_TYPE_LABELS[r.recipient_type] ?? r.recipient_type}
        </Tag>
      ),
    },
    {
      title: '分账方式',
      dataIndex: 'split_method',
      width: 100,
      valueType: 'select',
      valueEnum: {
        percentage: { text: '按比例' },
        fixed_fen: { text: '固定金额' },
      },
      render: (_, r) => (
        <Tag color={r.split_method === 'percentage' ? 'geekblue' : 'gold'}>
          {SPLIT_METHOD_LABELS[r.split_method] ?? r.split_method}
        </Tag>
      ),
    },
    {
      title: '比例/金额',
      width: 120,
      search: false,
      render: (_, r) => {
        if (r.split_method === 'percentage' && r.percentage != null) {
          return (
            <Text strong style={{ color: '#FF6B35' }}>
              {(r.percentage * 100).toFixed(2)}%
            </Text>
          );
        }
        if (r.split_method === 'fixed_fen' && r.fixed_fen != null) {
          return (
            <Text strong style={{ color: '#185FA5' }}>
              {formatPrice(r.fixed_fen)}
            </Text>
          );
        }
        return <Text type="secondary">—</Text>;
      },
    },
    {
      title: '适用门店',
      dataIndex: 'applicable_stores',
      width: 100,
      search: false,
      render: (_, r) => {
        const count = r.applicable_stores?.length ?? 0;
        return count === 0 ? (
          <Tag color="green">全部门店</Tag>
        ) : (
          <Tooltip
            title={
              <div style={{ maxHeight: 200, overflow: 'auto' }}>
                {r.applicable_stores.map((s) => (
                  <div key={s} style={{ fontSize: 12 }}>{s}</div>
                ))}
              </div>
            }
          >
            <Tag color="blue">{count} 个门店</Tag>
          </Tooltip>
        );
      },
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      width: 80,
      search: false,
      sorter: true,
      render: (_, r) => (
        <Tag color={r.priority <= 10 ? 'red' : r.priority <= 50 ? 'orange' : 'default'}>
          {r.priority}
        </Tag>
      ),
    },
    {
      title: '启用',
      dataIndex: 'is_active',
      width: 70,
      valueType: 'select',
      valueEnum: {
        true: { text: '已启用', status: 'Success' },
        false: { text: '已停用', status: 'Error' },
      },
      render: (_, r) => (
        <Switch
          checked={r.is_active}
          size="small"
          onChange={(checked) => handleToggleActive(r, checked)}
        />
      ),
    },
    {
      title: '有效期',
      width: 180,
      search: false,
      render: (_, r) => {
        if (!r.valid_from && !r.valid_to) {
          return <Tag>永久有效</Tag>;
        }
        return (
          <Text style={{ fontSize: 12 }}>
            {r.valid_from ?? '不限'} ~ {r.valid_to ?? '不限'}
          </Text>
        );
      },
    },
    {
      title: '操作',
      width: 150,
      fixed: 'right',
      search: false,
      render: (_, r) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => openEditModal(r)}
          >
            编辑
          </Button>
          {r.is_active && (
            <Popconfirm
              title="确认停用"
              description={`确定要停用规则「${r.name}」吗？`}
              onConfirm={() => handleDeactivate(r)}
              okText="确定"
              cancelText="取消"
            >
              <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                停用
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  // ── 渲染 ─────────────────────────────────────────────────────────────────

  return (
    <div
      style={{
        padding: '24px',
        minWidth: 1280,
        background: '#F8F7F5',
        minHeight: '100vh',
      }}
    >
      {/* 页头 */}
      <Row align="middle" style={{ marginBottom: 20 }}>
        <Col flex="auto">
          <Title level={3} style={{ margin: 0, color: '#1E2A3A' }}>
            分润规则管理
          </Title>
          <Text type="secondary">
            管理品牌/加盟商/供应商分润规则配置 · 优先级越小越先执行
          </Text>
        </Col>
        <Col>
          <Button
            icon={<LinkOutlined />}
            onClick={() => navigate('/finance/split-payment')}
          >
            分账管理
          </Button>
        </Col>
      </Row>

      {/* ProTable */}
      <div style={{ background: '#fff', borderRadius: 8, padding: 24 }}>
        <ProTable<SplitRule>
          actionRef={actionRef}
          rowKey="rule_id"
          columns={columns}
          search={{ labelWidth: 'auto' }}
          pagination={{ defaultPageSize: 20 }}
          scroll={{ x: 1200 }}
          toolBarRender={() => [
            <Button
              key="create"
              type="primary"
              icon={<PlusOutlined />}
              onClick={openCreateModal}
            >
              新建规则
            </Button>,
          ]}
          request={async (params) => {
            try {
              const qs = new URLSearchParams({
                page: String(params.current ?? 1),
                size: String(params.pageSize ?? 20),
              });
              if (params.is_active !== undefined && params.is_active !== null) {
                qs.set('is_active', String(params.is_active));
              }
              if (params.recipient_type) {
                qs.set('recipient_type', params.recipient_type);
              }
              const result = await apiRequest<{
                items: SplitRule[];
                total: number;
              }>(`/api/v1/finance/splits/rules?${qs}`);
              return {
                data: result.items,
                total: result.total,
                success: true,
              };
            } catch {
              return { data: [], total: 0, success: false };
            }
          }}
        />
      </div>

      {/* 新建/编辑 Modal */}
      <Modal
        title={editingRule ? '编辑分润规则' : '新建分润规则'}
        open={modalOpen}
        onCancel={() => {
          setModalOpen(false);
          form.resetFields();
        }}
        width={640}
        confirmLoading={confirmLoading}
        onOk={handleSubmit}
        okText={editingRule ? '保存' : '创建'}
        cancelText="取消"
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          style={{ marginTop: 16 }}
          initialValues={{
            is_active: true,
            priority: 0,
            applicable_stores: [],
            applicable_channels: [],
          }}
        >
          <Form.Item name="id" hidden>
            <Input />
          </Form.Item>

          <Row gutter={16}>
            <Col span={14}>
              <Form.Item
                name="name"
                label="规则名称"
                rules={[{ required: true, message: '请输入规则名称' }]}
              >
                <Input placeholder="如：品牌管理费分润" maxLength={100} />
              </Form.Item>
            </Col>
            <Col span={10}>
              <Form.Item
                name="priority"
                label="优先级"
                tooltip="数字越小越先执行"
                rules={[{ required: true, message: '请输入优先级' }]}
              >
                <InputNumber
                  style={{ width: '100%' }}
                  min={0}
                  max={9999}
                  placeholder="0"
                />
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="recipient_type"
                label="收款方类型"
                rules={[{ required: true, message: '请选择收款方类型' }]}
              >
                <Select
                  placeholder="选择收款方类型"
                  options={RECIPIENT_TYPES.map((t) => ({
                    value: t,
                    label: RECIPIENT_TYPE_LABELS[t],
                  }))}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="recipient_id"
                label="收款方 ID"
                tooltip="可选，留空表示集团总部"
              >
                <Input placeholder="UUID，留空=集团总部" />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            name="split_method"
            label="分账方式"
            rules={[{ required: true, message: '请选择分账方式' }]}
          >
            <Select
              placeholder="选择分账方式"
              options={SPLIT_METHODS.map((m) => ({
                value: m,
                label: SPLIT_METHOD_LABELS[m],
              }))}
            />
          </Form.Item>

          {/* 条件字段：按比例 */}
          {splitMethod === 'percentage' && (
            <Form.Item
              name="percentage"
              label="分润比例 (%)"
              rules={[
                { required: true, message: '请输入分润比例' },
                {
                  type: 'number',
                  min: 0,
                  max: 100,
                  message: '比例必须在 0-100 之间',
                },
              ]}
              tooltip="输入 0-100 的百分比值，如输入 5 表示 5%"
            >
              <InputNumber
                style={{ width: '100%' }}
                min={0}
                max={100}
                precision={2}
                addonAfter="%"
                placeholder="0.00"
              />
            </Form.Item>
          )}

          {/* 条件字段：固定金额 */}
          {splitMethod === 'fixed_fen' && (
            <Form.Item
              name="fixed_fen"
              label="固定金额（分）"
              rules={[
                { required: true, message: '请输入固定金额' },
                { type: 'number', min: 1, message: '金额必须大于 0' },
              ]}
              tooltip="金额单位：分（1元 = 100分）"
            >
              <InputNumber
                style={{ width: '100%' }}
                min={1}
                precision={0}
                placeholder="输入金额（分）"
              />
            </Form.Item>
          )}

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="applicable_stores"
                label="适用门店"
                tooltip="不选 = 全部门店"
              >
                <Select
                  mode="tags"
                  placeholder="输入门店 ID 后回车添加"
                  tokenSeparators={[',']}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="applicable_channels"
                label="适用渠道"
                tooltip="不选 = 全部渠道"
              >
                <Select
                  mode="multiple"
                  placeholder="选择适用渠道"
                  options={CHANNEL_OPTIONS.map((c) => ({
                    value: c,
                    label: CHANNEL_LABELS[c],
                  }))}
                />
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="valid_from" label="有效期开始">
                <DatePicker
                  style={{ width: '100%' }}
                  placeholder="不限"
                  onChange={(date) => {
                    form.setFieldValue(
                      'valid_from',
                      date ? date.format('YYYY-MM-DD') : undefined,
                    );
                  }}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="valid_to" label="有效期结束">
                <DatePicker
                  style={{ width: '100%' }}
                  placeholder="不限"
                  onChange={(date) => {
                    form.setFieldValue(
                      'valid_to',
                      date ? date.format('YYYY-MM-DD') : undefined,
                    );
                  }}
                />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            name="is_active"
            label="启用状态"
            valuePropName="checked"
          >
            <Switch
              checkedChildren="启用"
              unCheckedChildren="停用"
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default SplitRuleManagePage;
