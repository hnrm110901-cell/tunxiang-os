/**
 * S1W4 加购推荐话术管理页面
 * 功能：话术列表（含转化率）、批量生成、启用/禁用
 * 技术栈：Ant Design 5.x + ProTable
 */
import { useState, useRef, useCallback } from 'react';
import {
  Card,
  Button,
  Tag,
  Switch,
  Space,
  Typography,
  message,
  Modal,
  Form,
  InputNumber,
  Select,
  Statistic,
  Row,
  Col,
  Progress,
  Tooltip,
} from 'antd';
import {
  ThunderboltOutlined,
  ReloadOutlined,
  RocketOutlined,
  EyeOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons';
import { ProTable } from '@ant-design/pro-components';
import type { ProColumns, ActionType } from '@ant-design/pro-components';

const { Title, Text } = Typography;

const API_BASE = 'http://localhost:8002';
const TENANT_ID = localStorage.getItem('tenant_id') || '';

// ─── 类型定义 ────────────────────────────────────────────────────────────────

interface UpsellPrompt {
  id: string;
  trigger_dish_id: string;
  trigger_dish_name: string;
  suggest_dish_id: string;
  suggest_dish_name: string;
  prompt_text: string;
  prompt_type: string;
  is_enabled: boolean;
  conversion_count: number;
  impression_count: number;
  conversion_rate: number;
  priority: number;
  store_id: string | null;
  created_at: string;
}

interface BatchStats {
  generated: number;
  skipped: number;
  errors: number;
}

// ─── 常量 ────────────────────────────────────────────────────────────────────

const PROMPT_TYPE_MAP: Record<string, { label: string; color: string }> = {
  add_on: { label: '搭配加购', color: 'blue' },
  upgrade: { label: '升级推荐', color: 'purple' },
  combo: { label: '组合优惠', color: 'orange' },
  seasonal: { label: '时令推荐', color: 'green' },
  popular: { label: '人气必点', color: 'red' },
};

// ─── API 调用 ────────────────────────────────────────────────────────────────

async function fetchPrompts(params: {
  current?: number;
  pageSize?: number;
  store_id?: string;
  prompt_type?: string;
}): Promise<{ data: UpsellPrompt[]; total: number; success: boolean }> {
  const { current = 1, pageSize = 20, store_id, prompt_type } = params;
  const query = new URLSearchParams({
    page: String(current),
    size: String(pageSize),
  });
  if (store_id) query.set('store_id', store_id);
  if (prompt_type) query.set('prompt_type', prompt_type);

  const resp = await fetch(`${API_BASE}/api/v1/menu/upsell/prompts?${query}`, {
    headers: { 'X-Tenant-ID': TENANT_ID },
  });
  const json = await resp.json();
  if (!json.ok) throw new Error('加载话术列表失败');
  return { data: json.data.items, total: json.data.total, success: true };
}

async function batchGenerate(body: {
  store_id: string;
  top_n: number;
  period: string;
  prompt_type: string;
}): Promise<BatchStats> {
  const resp = await fetch(`${API_BASE}/api/v1/menu/upsell/generate-batch`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': TENANT_ID,
    },
    body: JSON.stringify(body),
  });
  const json = await resp.json();
  if (!json.ok) throw new Error('批量生成失败');
  return json.data as BatchStats;
}

async function toggleEnabled(id: string, enabled: boolean): Promise<void> {
  // 直接调用PATCH端点（如有），或通过通用更新
  const resp = await fetch(`${API_BASE}/api/v1/menu/upsell/prompts/${id}/toggle`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': TENANT_ID,
    },
    body: JSON.stringify({ is_enabled: enabled }),
  });
  if (!resp.ok) throw new Error('切换状态失败');
}

// ─── 组件 ────────────────────────────────────────────────────────────────────

export default function UpsellManagePage() {
  const actionRef = useRef<ActionType>();
  const [batchModalOpen, setBatchModalOpen] = useState(false);
  const [batchLoading, setBatchLoading] = useState(false);
  const [batchResult, setBatchResult] = useState<BatchStats | null>(null);
  const [form] = Form.useForm();

  // ─── 批量生成 ──────────────────────────────────────────────────────────────

  const handleBatchGenerate = useCallback(async () => {
    try {
      const values = await form.validateFields();
      setBatchLoading(true);
      const stats = await batchGenerate(values);
      setBatchResult(stats);
      message.success(`生成完成：新增 ${stats.generated} 条，跳过 ${stats.skipped} 条`);
      actionRef.current?.reload();
    } catch (err) {
      message.error('批量生成失败，请重试');
    } finally {
      setBatchLoading(false);
    }
  }, [form]);

  // ─── 启用/禁用 ─────────────────────────────────────────────────────────────

  const handleToggle = useCallback(async (record: UpsellPrompt, checked: boolean) => {
    try {
      await toggleEnabled(record.id, checked);
      message.success(checked ? '已启用' : '已禁用');
      actionRef.current?.reload();
    } catch {
      message.error('操作失败');
    }
  }, []);

  // ─── 列配置 ────────────────────────────────────────────────────────────────

  const columns: ProColumns<UpsellPrompt>[] = [
    {
      title: '触发菜品',
      dataIndex: 'trigger_dish_name',
      width: 120,
      ellipsis: true,
    },
    {
      title: '推荐菜品',
      dataIndex: 'suggest_dish_name',
      width: 120,
      ellipsis: true,
    },
    {
      title: '推荐话术',
      dataIndex: 'prompt_text',
      width: 240,
      ellipsis: true,
      search: false,
    },
    {
      title: '类型',
      dataIndex: 'prompt_type',
      width: 100,
      valueEnum: {
        add_on: { text: '搭配加购' },
        upgrade: { text: '升级推荐' },
        combo: { text: '组合优惠' },
        seasonal: { text: '时令推荐' },
        popular: { text: '人气必点' },
      },
      render: (_, record) => {
        const info = PROMPT_TYPE_MAP[record.prompt_type] || { label: record.prompt_type, color: 'default' };
        return <Tag color={info.color}>{info.label}</Tag>;
      },
    },
    {
      title: '曝光',
      dataIndex: 'impression_count',
      width: 80,
      sorter: true,
      search: false,
      render: (val) => (
        <Space size={4}>
          <EyeOutlined style={{ color: '#8c8c8c' }} />
          <span>{val}</span>
        </Space>
      ),
    },
    {
      title: '转化',
      dataIndex: 'conversion_count',
      width: 80,
      sorter: true,
      search: false,
      render: (val) => (
        <Space size={4}>
          <CheckCircleOutlined style={{ color: '#52c41a' }} />
          <span>{val}</span>
        </Space>
      ),
    },
    {
      title: '转化率',
      dataIndex: 'conversion_rate',
      width: 120,
      sorter: true,
      search: false,
      render: (_, record) => {
        const rate = record.conversion_rate * 100;
        let color = '#ff4d4f';
        if (rate >= 10) color = '#52c41a';
        else if (rate >= 5) color = '#faad14';
        return (
          <Tooltip title={`${record.conversion_count} / ${record.impression_count}`}>
            <Progress
              percent={Math.min(rate, 100)}
              size="small"
              strokeColor={color}
              format={() => `${rate.toFixed(1)}%`}
              style={{ width: 90 }}
            />
          </Tooltip>
        );
      },
    },
    {
      title: '启用',
      dataIndex: 'is_enabled',
      width: 70,
      search: false,
      render: (_, record) => (
        <Switch
          checked={record.is_enabled}
          size="small"
          onChange={(checked) => handleToggle(record, checked)}
        />
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 160,
      valueType: 'dateTime',
      search: false,
      sorter: true,
    },
  ];

  // ─── 渲染 ─────────────────────────────────────────────────────────────────

  return (
    <div style={{ padding: 24 }}>
      <Card>
        <Row gutter={24} style={{ marginBottom: 24 }}>
          <Col span={6}>
            <Statistic title="AI加购推荐" value="S1W4" prefix={<ThunderboltOutlined />} />
          </Col>
          <Col span={18}>
            <Text type="secondary">
              基于菜品共现亲和矩阵 + Claude AI生成个性化加购话术，提升客单价。
              系统每日凌晨4点自动重算亲和矩阵，可手动批量生成话术。
            </Text>
          </Col>
        </Row>

        <ProTable<UpsellPrompt>
          actionRef={actionRef}
          rowKey="id"
          headerTitle="加购话术管理"
          columns={columns}
          request={fetchPrompts}
          pagination={{ defaultPageSize: 20 }}
          toolBarRender={() => [
            <Button
              key="batch"
              type="primary"
              icon={<RocketOutlined />}
              onClick={() => {
                setBatchResult(null);
                setBatchModalOpen(true);
              }}
            >
              批量生成话术
            </Button>,
            <Button
              key="refresh"
              icon={<ReloadOutlined />}
              onClick={() => actionRef.current?.reload()}
            >
              刷新
            </Button>,
          ]}
        />
      </Card>

      {/* 批量生成对话框 */}
      <Modal
        title="批量生成加购话术"
        open={batchModalOpen}
        onCancel={() => setBatchModalOpen(false)}
        onOk={handleBatchGenerate}
        confirmLoading={batchLoading}
        okText="开始生成"
        width={480}
      >
        <Form form={form} layout="vertical" initialValues={{ top_n: 20, period: 'last_30d', prompt_type: 'add_on' }}>
          <Form.Item name="store_id" label="门店ID" rules={[{ required: true, message: '请输入门店ID' }]}>
            <Select placeholder="选择门店" />
          </Form.Item>
          <Form.Item name="top_n" label="生成数量（取亲和度最高的N对）">
            <InputNumber min={1} max={100} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="period" label="统计周期">
            <Select
              options={[
                { label: '近7天', value: 'last_7d' },
                { label: '近30天', value: 'last_30d' },
                { label: '近90天', value: 'last_90d' },
              ]}
            />
          </Form.Item>
          <Form.Item name="prompt_type" label="话术类型">
            <Select
              options={[
                { label: '搭配加购', value: 'add_on' },
                { label: '升级推荐', value: 'upgrade' },
                { label: '组合优惠', value: 'combo' },
                { label: '时令推荐', value: 'seasonal' },
                { label: '人气必点', value: 'popular' },
              ]}
            />
          </Form.Item>
        </Form>

        {batchResult && (
          <Card size="small" style={{ marginTop: 16, background: '#f6ffed' }}>
            <Row gutter={16}>
              <Col span={8}>
                <Statistic title="新增" value={batchResult.generated} valueStyle={{ color: '#52c41a' }} />
              </Col>
              <Col span={8}>
                <Statistic title="跳过" value={batchResult.skipped} valueStyle={{ color: '#8c8c8c' }} />
              </Col>
              <Col span={8}>
                <Statistic title="失败" value={batchResult.errors} valueStyle={{ color: batchResult.errors > 0 ? '#ff4d4f' : '#8c8c8c' }} />
              </Col>
            </Row>
          </Card>
        )}
      </Modal>
    </div>
  );
}
