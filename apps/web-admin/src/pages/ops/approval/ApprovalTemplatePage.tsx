/**
 * 审批模板管理 — 总部审批流模板 CRUD
 * 路由：/approval-templates
 * API：GET/POST /api/v1/ops/approvals/templates
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Table, Button, Tag, Switch, Space, Drawer, Form, Input, Select,
  InputNumber, message, Popconfirm, Spin, Typography, Divider,
  Modal, Card, Row, Col,
} from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined, SettingOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { txFetchData } from '../../../api';

const { Title, Text } = Typography;

// ─── 类型定义 ────────────────────────────────────────────────────────────────

type BusinessType =
  | 'discount'
  | 'refund'
  | 'void_order'
  | 'large_purchase'
  | 'leave'
  | 'payroll';

interface ApprovalStep {
  step_no: number;
  approver_role: string;
  approval_type: 'single' | 'any' | 'all';
  amount_min?: number;
  amount_max?: number;
}

interface ApprovalTemplate {
  id: string;
  name: string;
  business_type: BusinessType;
  steps: ApprovalStep[];
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
}

interface TemplateListResponse {
  items: ApprovalTemplate[];
  total: number;
}

// ─── 常量 ────────────────────────────────────────────────────────────────────

const BUSINESS_TYPE_OPTIONS: { label: string; value: BusinessType; color: string }[] = [
  { label: '折扣审批', value: 'discount', color: 'orange' },
  { label: '退款审批', value: 'refund', color: 'red' },
  { label: '作废单审批', value: 'void_order', color: 'volcano' },
  { label: '大额采购', value: 'large_purchase', color: 'blue' },
  { label: '员工请假', value: 'leave', color: 'purple' },
  { label: '薪资审批', value: 'payroll', color: 'gold' },
];

const BUSINESS_TYPE_MAP: Record<BusinessType, { label: string; color: string }> = {
  discount:       { label: '折扣审批', color: 'orange' },
  refund:         { label: '退款审批', color: 'red' },
  void_order:     { label: '作废单审批', color: 'volcano' },
  large_purchase: { label: '大额采购', color: 'blue' },
  leave:          { label: '员工请假', color: 'purple' },
  payroll:        { label: '薪资审批', color: 'gold' },
};

const APPROVER_ROLE_OPTIONS = [
  { label: '店长', value: 'store_manager' },
  { label: '区域经理', value: 'regional_manager' },
  { label: '财务主管', value: 'finance_supervisor' },
  { label: '运营总监', value: 'ops_director' },
  { label: '人事专员', value: 'hr_specialist' },
  { label: '采购主管', value: 'purchase_supervisor' },
];

const APPROVAL_TYPE_OPTIONS = [
  { label: '单人审批', value: 'single' },
  { label: '任一审批', value: 'any' },
  { label: '全部审批', value: 'all' },
];

// ─── Mock 数据已移除，API 加载失败时回退空列表 ─────────────────────────────────

// ─── 步骤配置子表单 ────────────────────────────────────────────────────────────

interface StepFormItem {
  step_no: number;
  approver_role: string;
  approval_type: 'single' | 'any' | 'all';
  amount_min?: number;
  amount_max?: number;
}

function StepEditor({
  steps,
  onChange,
}: {
  steps: StepFormItem[];
  onChange: (s: StepFormItem[]) => void;
}) {
  const addStep = () => {
    const maxNo = steps.reduce((m, s) => Math.max(m, s.step_no), 0);
    onChange([...steps, { step_no: maxNo + 1, approver_role: 'store_manager', approval_type: 'single' }]);
  };

  const removeStep = (idx: number) => {
    const next = steps.filter((_, i) => i !== idx).map((s, i) => ({ ...s, step_no: i + 1 }));
    onChange(next);
  };

  const updateStep = (idx: number, patch: Partial<StepFormItem>) => {
    onChange(steps.map((s, i) => (i === idx ? { ...s, ...patch } : s)));
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
        <Text strong>审批步骤</Text>
        <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={addStep}>
          添加步骤
        </Button>
      </div>
      {steps.length === 0 && (
        <div style={{ textAlign: 'center', color: '#999', padding: '16px 0', border: '1px dashed #d9d9d9', borderRadius: 6 }}>
          暂无步骤，点击"添加步骤"开始配置
        </div>
      )}
      {steps.map((step, idx) => (
        <Card
          key={idx}
          size="small"
          style={{ marginBottom: 8, background: '#fafafa' }}
          title={<Text style={{ fontSize: 13 }}>第 {step.step_no} 步</Text>}
          extra={
            <Button size="small" danger type="text" icon={<DeleteOutlined />} onClick={() => removeStep(idx)} />
          }
        >
          <Row gutter={8}>
            <Col span={10}>
              <Form.Item label="审批角色" style={{ marginBottom: 8 }}>
                <Select
                  size="small"
                  value={step.approver_role}
                  options={APPROVER_ROLE_OPTIONS}
                  onChange={v => updateStep(idx, { approver_role: v })}
                />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="审批类型" style={{ marginBottom: 8 }}>
                <Select
                  size="small"
                  value={step.approval_type}
                  options={APPROVAL_TYPE_OPTIONS}
                  onChange={v => updateStep(idx, { approval_type: v })}
                />
              </Form.Item>
            </Col>
            <Col span={6} />
            <Col span={10}>
              <Form.Item label="金额下限(元)" style={{ marginBottom: 8 }}>
                <InputNumber
                  size="small"
                  min={0}
                  style={{ width: '100%' }}
                  value={step.amount_min}
                  placeholder="不限"
                  onChange={v => updateStep(idx, { amount_min: v ?? undefined })}
                />
              </Form.Item>
            </Col>
            <Col span={10}>
              <Form.Item label="金额上限(元)" style={{ marginBottom: 8 }}>
                <InputNumber
                  size="small"
                  min={0}
                  style={{ width: '100%' }}
                  value={step.amount_max}
                  placeholder="不限"
                  onChange={v => updateStep(idx, { amount_max: v ?? undefined })}
                />
              </Form.Item>
            </Col>
          </Row>
        </Card>
      ))}
    </div>
  );
}

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export function ApprovalTemplatePage() {
  const [templates, setTemplates] = useState<ApprovalTemplate[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);

  // Drawer 状态
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<ApprovalTemplate | null>(null);
  const [saving, setSaving] = useState(false);

  // 步骤编辑
  const [steps, setSteps] = useState<StepFormItem[]>([]);

  const [form] = Form.useForm();

  // ── 加载列表 ──
  const loadTemplates = useCallback(async (p = 1) => {
    setLoading(true);
    try {
      const res = await txFetchData<TemplateListResponse>(
        `/api/v1/ops/approval-templates?page=${p}&size=20`,
      );
      setTemplates(res.data?.items ?? []);
      setTotal(res.data?.total ?? 0);
    } catch {
      // API 失败时保持空列表
      setTemplates([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadTemplates(page);
  }, [loadTemplates, page]);

  // ── 打开新建/编辑 Drawer ──
  const openDrawer = (template?: ApprovalTemplate) => {
    setEditTarget(template || null);
    if (template) {
      form.setFieldsValue({
        name: template.name,
        business_type: template.business_type,
        is_enabled: template.is_enabled,
      });
      setSteps(template.steps.map(s => ({ ...s })));
    } else {
      form.resetFields();
      form.setFieldValue('is_enabled', true);
      setSteps([]);
    }
    setDrawerOpen(true);
  };

  // ── 提交 ──
  const handleSave = async () => {
    const values = await form.validateFields();
    if (steps.length === 0) {
      message.warning('请至少添加一个审批步骤');
      return;
    }
    setSaving(true);
    try {
      const payload = { ...values, steps };
      if (editTarget) {
        await txFetchData(`/api/v1/ops/approval-templates/${editTarget.id}`, {
          method: 'PATCH',
          body: JSON.stringify(payload),
        });
        message.success('模板已更新');
      } else {
        await txFetchData('/api/v1/ops/approval-templates', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        message.success('模板已创建');
      }
      setDrawerOpen(false);
      loadTemplates(page);
    } finally {
      setSaving(false);
    }
  };

  // ── 切换启用状态 ──
  const handleToggle = async (template: ApprovalTemplate, enabled: boolean) => {
    try {
      await txFetchData(`/api/v1/ops/approval-templates/${template.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_enabled: enabled }),
      });
      setTemplates(prev => prev.map(t => (t.id === template.id ? { ...t, is_enabled: enabled } : t)));
      message.success(enabled ? '已启用' : '已禁用');
    } catch {
      message.error('操作失败');
    }
  };

  // ── 删除 ──
  const handleDelete = async (templateId: string) => {
    try {
      await txFetchData(`/api/v1/ops/approval-templates/${templateId}`, {
        method: 'DELETE',
      });
      message.success('已删除');
      loadTemplates(page);
    } catch {
      message.error('删除失败');
    }
  };

  // ── 表格列定义 ──
  const columns: ColumnsType<ApprovalTemplate> = [
    {
      title: '模板名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string) => <Text strong>{name}</Text>,
    },
    {
      title: '业务类型',
      dataIndex: 'business_type',
      key: 'business_type',
      render: (bt: BusinessType) => {
        const conf = BUSINESS_TYPE_MAP[bt];
        return <Tag color={conf?.color}>{conf?.label ?? bt}</Tag>;
      },
    },
    {
      title: '步骤数',
      dataIndex: 'steps',
      key: 'steps_count',
      width: 80,
      render: (steps: ApprovalStep[]) => (
        <Tag icon={<SettingOutlined />} color="default">{steps.length} 步</Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'is_enabled',
      key: 'is_enabled',
      width: 100,
      render: (enabled: boolean, record) => (
        <Switch
          checked={enabled}
          checkedChildren="启用"
          unCheckedChildren="禁用"
          onChange={v => handleToggle(record, v)}
          size="small"
        />
      ),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 160,
      render: (t: string) => new Date(t).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }),
    },
    {
      title: '操作',
      key: 'actions',
      width: 140,
      render: (_, record) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => openDrawer(record)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确认删除此模板？"
            description="删除后不可恢复，正在进行的审批实例不受影响。"
            onConfirm={() => handleDelete(record.id)}
            okText="确认删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: '24px 32px', background: '#f8f7f5', minHeight: '100vh' }}>
      {/* 页面标题栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <Title level={4} style={{ margin: 0, color: '#1E2A3A' }}>审批模板管理</Title>
          <Text type="secondary" style={{ fontSize: 13 }}>
            配置各业务场景的审批流程模板，支持多步骤、条件路由
          </Text>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => openDrawer()}
          style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
        >
          新建模板
        </Button>
      </div>

      {/* 模板列表 */}
      <div style={{ background: '#fff', borderRadius: 8, padding: '0 0 16px' }}>
        <Table<ApprovalTemplate>
          columns={columns}
          dataSource={templates}
          rowKey="id"
          loading={loading}
          pagination={{
            current: page,
            total,
            pageSize: 20,
            showSizeChanger: false,
            showTotal: (t) => `共 ${t} 条`,
            onChange: setPage,
          }}
          size="middle"
          style={{ padding: '0 16px' }}
        />
      </div>

      {/* 新建/编辑 Drawer */}
      <Drawer
        title={editTarget ? `编辑模板：${editTarget.name}` : '新建审批模板'}
        placement="right"
        width={560}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        footer={
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <Button onClick={() => setDrawerOpen(false)}>取消</Button>
            <Button
              type="primary"
              loading={saving}
              onClick={handleSave}
              style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
            >
              {editTarget ? '保存修改' : '创建模板'}
            </Button>
          </div>
        }
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="模板名称"
            rules={[{ required: true, message: '请输入模板名称' }]}
          >
            <Input placeholder="例：折扣审批流程" maxLength={50} showCount />
          </Form.Item>

          <Form.Item
            name="business_type"
            label="业务类型"
            rules={[{ required: true, message: '请选择业务类型' }]}
          >
            <Select
              placeholder="选择适用的业务场景"
              options={BUSINESS_TYPE_OPTIONS.map(o => ({
                label: (
                  <Space>
                    <Tag color={o.color} style={{ margin: 0 }}>{o.label}</Tag>
                  </Space>
                ),
                value: o.value,
              }))}
            />
          </Form.Item>

          <Form.Item name="is_enabled" label="启用状态" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>

          <Divider />

          <StepEditor steps={steps} onChange={setSteps} />
        </Form>
      </Drawer>
    </div>
  );
}
