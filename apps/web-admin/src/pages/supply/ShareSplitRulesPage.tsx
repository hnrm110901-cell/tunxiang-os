/**
 * POS 销售分成转入库 规则管理页 — 域D 供应链（PRD-11 sub-A / Phase 2 W11 / T2 + Tier 1 邻接）
 * 路由：/supply/share-split-rules
 *
 * 功能：
 *   1. 规则列表 + 启停 Switch 切换 + 软删
 *   2. 新建规则（dish_id + allow_share + default_method 3-way 枚举 + max_share_count）
 *   3. 规则编辑（PATCH 模式，model_dump exclude_unset 区分"未提供"vs"显式 None"）
 *
 * 业务场景：徐记海鲜采购总监 / 食安总监配置每个 dish 是否允许多人合点 +
 *   默认拆分方法 + 上限人数。POS 端 caller (PR-B tx-trade) 在 cashier 提交
 *   订单时根据 rule 拼 ShareSplitSpec 传 auto_deduction，emit
 *   inventory.split_attributed event 让 tx-analytics (PR-C) 做 per-customer
 *   cost attribution dashboard.
 *
 * 调用接口（PRD-11 sub-A）：
 *   POST   /api/v1/supply/share-split-rules
 *   GET    /api/v1/supply/share-split-rules?only_active=&limit=&offset=
 *   GET    /api/v1/supply/share-split-rules/{rule_id}
 *   PATCH  /api/v1/supply/share-split-rules/{rule_id}
 *   DELETE /api/v1/supply/share-split-rules/{rule_id}
 *   POST   /api/v1/supply/share-split-rules/validate (前端预校验, POS UI 调)
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { txFetchData } from '../../api/client';

const { Title, Text, Paragraph } = Typography;

type ShareSplitMethod = 'even' | 'weighted' | 'manual';

interface ShareSplitRule {
  id: string;
  tenant_id: string;
  dish_id: string;
  allow_share: boolean;
  default_method: ShareSplitMethod;
  max_share_count: number | null;
  is_active: boolean;
  notes: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  is_deleted: boolean;
}

export function ShareSplitRulesPage() {
  const [list, setList] = useState<ShareSplitRule[]>([]);
  const [loading, setLoading] = useState(false);
  const [onlyActive, setOnlyActive] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm();

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set('only_active', String(onlyActive));
      params.set('limit', '100');
      const data = await txFetchData<{ data: ShareSplitRule[] }>(
        `/api/v1/supply/share-split-rules?${params.toString()}`
      );
      setList(data?.data ?? []);
    } catch (e) {
      message.error('加载分享规则失败：' + String(e));
    } finally {
      setLoading(false);
    }
  }, [onlyActive]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleCreate = async (values: {
    dish_id: string;
    allow_share: boolean;
    default_method: ShareSplitMethod;
    max_share_count: number | null;
    notes: string;
  }) => {
    try {
      await txFetchData('/api/v1/supply/share-split-rules', {
        method: 'POST',
        body: JSON.stringify({
          dish_id: values.dish_id,
          allow_share: values.allow_share,
          default_method: values.default_method,
          max_share_count:
            values.max_share_count === null || values.max_share_count === undefined
              ? null
              : values.max_share_count,
          notes: values.notes || null,
        }),
      });
      message.success('分享规则创建成功');
      setCreateOpen(false);
      form.resetFields();
      await refresh();
    } catch (e) {
      message.error('创建失败：' + String(e));
    }
  };

  const handleToggleActive = async (row: ShareSplitRule, next: boolean) => {
    try {
      await txFetchData(`/api/v1/supply/share-split-rules/${row.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_active: next }),
      });
      message.success(next ? '已启用' : '已禁用');
      await refresh();
    } catch (e) {
      message.error('切换失败：' + String(e));
    }
  };

  const handleToggleAllowShare = async (row: ShareSplitRule, next: boolean) => {
    try {
      await txFetchData(`/api/v1/supply/share-split-rules/${row.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ allow_share: next }),
      });
      message.success(next ? '已允许分享' : '已禁止分享');
      await refresh();
    } catch (e) {
      message.error('切换失败：' + String(e));
    }
  };

  const handleDelete = async (row: ShareSplitRule) => {
    try {
      await txFetchData(`/api/v1/supply/share-split-rules/${row.id}`, {
        method: 'DELETE',
      });
      message.success('已删除');
      await refresh();
    } catch (e) {
      message.error('删除失败：' + String(e));
    }
  };

  const methodLabel = (m: ShareSplitMethod): string => {
    if (m === 'even') return '均分';
    if (m === 'weighted') return '加权';
    if (m === 'manual') return '手动';
    return m;
  };

  const columns: ColumnsType<ShareSplitRule> = [
    { title: '菜品 ID', dataIndex: 'dish_id', key: 'dish_id', width: 280, ellipsis: true },
    {
      title: '允许分享',
      dataIndex: 'allow_share',
      key: 'allow_share',
      width: 100,
      render: (v: boolean, row: ShareSplitRule) => (
        <Switch
          checked={v}
          onChange={(next) => handleToggleAllowShare(row, next)}
        />
      ),
    },
    {
      title: '默认方法',
      dataIndex: 'default_method',
      key: 'default_method',
      width: 100,
      render: (v: ShareSplitMethod) => <Tag color="cyan">{methodLabel(v)}</Tag>,
    },
    {
      title: '上限人数',
      dataIndex: 'max_share_count',
      key: 'max_share_count',
      width: 100,
      render: (v: number | null) => (v === null ? <Tag color="blue">不限</Tag> : v),
    },
    {
      title: '启用',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 80,
      render: (v: boolean, row: ShareSplitRule) => (
        <Switch checked={v} onChange={(next) => handleToggleActive(row, next)} />
      ),
    },
    { title: '备注', dataIndex: 'notes', key: 'notes', ellipsis: true },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 180 },
    {
      title: '操作',
      key: 'ops',
      width: 100,
      fixed: 'right',
      render: (_, row) => (
        <Popconfirm title="确认删除规则？" onConfirm={() => handleDelete(row)}>
          <Button type="link" danger size="small">
            删除
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <Card
      title={<Title level={3}>POS 销售分成转入库 规则（PRD-11 sub-A）</Title>}
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={refresh}>
            刷新
          </Button>
          <Button icon={<PlusOutlined />} type="primary" onClick={() => setCreateOpen(true)}>
            新建规则
          </Button>
        </Space>
      }
    >
      <Alert
        message="POS 销售分成转入库 — 多人合点成本归属"
        description={
          <Paragraph style={{ marginBottom: 0 }}>
            <Text>采购/食安总监配置每个菜品是否允许多人合点 + 默认拆分方法 + 上限人数。</Text>
            <br />
            <Text>POS 端拆单时 caller 传 ShareSplitSpec (3-way 枚举)，auto_deduction emit</Text>
            <br />
            <Text>inventory.split_attributed event 让 tx-analytics 做 per-customer cost attribution。</Text>
            <br />
            <Text type="secondary">
              提示：BOM 物理消耗不变 (1 dish 仍消耗 1 份 BOM)，只是 cost 分摊到多 share。
              max_share_count NULL = 不限人数；非 NULL ≥ 2 = 上限拆分人数。
            </Text>
          </Paragraph>
        }
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
      />

      <Space style={{ marginBottom: 16 }} wrap>
        <span>
          仅启用：
          <Switch checked={onlyActive} onChange={setOnlyActive} />
        </span>
      </Space>

      <Table<ShareSplitRule>
        rowKey="id"
        dataSource={list}
        columns={columns}
        loading={loading}
        scroll={{ x: 1200 }}
        pagination={{ pageSize: 20 }}
      />

      <Modal
        open={createOpen}
        title="新建分享规则"
        onCancel={() => setCreateOpen(false)}
        onOk={() => form.submit()}
        okText="创建"
        cancelText="取消"
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleCreate}
          initialValues={{ allow_share: true, default_method: 'even' }}
        >
          <Form.Item
            name="dish_id"
            label="菜品 ID（UUID）"
            rules={[{ required: true, message: '必填' }]}
          >
            <Input placeholder="例如：22222222-0001-0001-0001-222222222222" />
          </Form.Item>
          <Form.Item
            name="allow_share"
            label="允许分享"
            tooltip="FALSE = 单人套餐 / 不可拆分项 (例: 个人套餐)"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            name="default_method"
            label="默认拆分方法"
            tooltip="EVEN 均分 (1/N) / WEIGHTED 加权 (传 weights[]) / MANUAL 手动 (传 amounts_fen[])"
            rules={[{ required: true }]}
          >
            <Select
              options={[
                { value: 'even', label: 'EVEN 均分 (推荐, 1/N 平均分摊)' },
                { value: 'weighted', label: 'WEIGHTED 加权 (caller 传 weights[])' },
                { value: 'manual', label: 'MANUAL 手动 (caller 传 amounts_fen[])' },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="max_share_count"
            label="上限人数（留空 = 不限）"
            tooltip="最大可分享人数，≥2；防极端拆分（例: 一份酸菜鱼分给 100 人）"
          >
            <InputNumber<number> min={2} max={50} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}

export default ShareSplitRulesPage;
