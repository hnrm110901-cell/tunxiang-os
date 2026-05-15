/**
 * 部门用料白名单管理页 — 域D 供应链（PRD-08 / Phase 2 W11 / T2 + Tier 1 邻接）
 * 路由：/supply/dept-whitelists
 *
 * 功能：
 *   1. 白名单列表 + 部门/启用过滤 + 启用/禁用切换 + 软删
 *   2. 单条新建（dept_id + ingredient_id + max_qty_per_day）
 *   3. 矩阵授权（一个部门一次性勾选多食材 — 简化版：手填 ingredient_id 列表）
 *
 * 业务场景：徐记海鲜食安总监 / 采购总监给后厨各档口（早餐/海鲜/热菜/凉菜）
 *   配置可领食材白名单 — 防早餐档串货高端海鲜（毛利底线硬约束）。
 *
 * 调用接口（PRD-08）：
 *   POST   /api/v1/supply/dept-whitelists
 *   GET    /api/v1/supply/dept-whitelists?dept_id=&only_active=
 *   PATCH  /api/v1/supply/dept-whitelists/{id}
 *   DELETE /api/v1/supply/dept-whitelists/{id}
 *   POST   /api/v1/supply/dept-whitelists/bulk-authorize
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
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined, ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { txFetchData } from '../../api/client';

const { Title, Text, Paragraph } = Typography;

interface Whitelist {
  id: string;
  tenant_id: string;
  dept_id: string;
  ingredient_id: string;
  max_qty_per_day: string | null;
  is_active: boolean;
  notes: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  is_deleted: boolean;
}

export function DeptWhitelistPage() {
  const [list, setList] = useState<Whitelist[]>([]);
  const [loading, setLoading] = useState(false);
  const [deptFilter, setDeptFilter] = useState<string>('');
  const [onlyActive, setOnlyActive] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [form] = Form.useForm();
  const [bulkForm] = Form.useForm();

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (deptFilter.trim()) params.set('dept_id', deptFilter.trim());
      params.set('only_active', String(onlyActive));
      params.set('limit', '100');
      const data = await txFetchData<{ data: Whitelist[] }>(
        `/api/v1/supply/dept-whitelists?${params.toString()}`
      );
      setList(data?.data ?? []);
    } catch (e) {
      message.error('加载白名单失败：' + String(e));
    } finally {
      setLoading(false);
    }
  }, [deptFilter, onlyActive]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleCreate = async (values: {
    dept_id: string;
    ingredient_id: string;
    max_qty_per_day: number | null;
    notes: string;
  }) => {
    try {
      await txFetchData('/api/v1/supply/dept-whitelists', {
        method: 'POST',
        body: JSON.stringify({
          dept_id: values.dept_id,
          ingredient_id: values.ingredient_id,
          max_qty_per_day:
            values.max_qty_per_day === null || values.max_qty_per_day === undefined
              ? null
              : String(values.max_qty_per_day),
          notes: values.notes || null,
        }),
      });
      message.success('白名单创建成功');
      setCreateOpen(false);
      form.resetFields();
      await refresh();
    } catch (e) {
      message.error('创建失败：' + String(e));
    }
  };

  const handleToggleActive = async (row: Whitelist, next: boolean) => {
    try {
      await txFetchData(`/api/v1/supply/dept-whitelists/${row.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_active: next }),
      });
      message.success(next ? '已启用' : '已禁用');
      await refresh();
    } catch (e) {
      message.error('切换失败：' + String(e));
    }
  };

  const handleDelete = async (row: Whitelist) => {
    try {
      await txFetchData(`/api/v1/supply/dept-whitelists/${row.id}`, {
        method: 'DELETE',
      });
      message.success('已删除');
      await refresh();
    } catch (e) {
      message.error('删除失败：' + String(e));
    }
  };

  const handleBulkAuthorize = async (values: {
    dept_id: string;
    ingredient_ids_csv: string;
    max_qty_per_day: number | null;
  }) => {
    const ids = values.ingredient_ids_csv
      .split(/[,\n\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (ids.length === 0) {
      message.warning('请至少输入一个 ingredient_id');
      return;
    }
    if (ids.length > 200) {
      message.warning('一次最多 200 个，请分批提交');
      return;
    }
    try {
      const result = await txFetchData<{
        data: { created_count: number; updated_count: number };
      }>('/api/v1/supply/dept-whitelists/bulk-authorize', {
        method: 'POST',
        body: JSON.stringify({
          dept_id: values.dept_id,
          items: ids.map((iid) => ({
            ingredient_id: iid,
            max_qty_per_day:
              values.max_qty_per_day === null || values.max_qty_per_day === undefined
                ? null
                : String(values.max_qty_per_day),
          })),
        }),
      });
      message.success(
        `授权完成 — 新建 ${result?.data?.created_count ?? 0} 条 / 更新 ${result?.data?.updated_count ?? 0} 条`
      );
      setBulkOpen(false);
      bulkForm.resetFields();
      await refresh();
    } catch (e) {
      message.error('批量授权失败：' + String(e));
    }
  };

  const columns: ColumnsType<Whitelist> = [
    { title: '部门 ID', dataIndex: 'dept_id', key: 'dept_id', width: 280, ellipsis: true },
    {
      title: '食材 ID',
      dataIndex: 'ingredient_id',
      key: 'ingredient_id',
      width: 280,
      ellipsis: true,
    },
    {
      title: '日上限',
      dataIndex: 'max_qty_per_day',
      key: 'max_qty_per_day',
      width: 120,
      render: (v: string | null) => (v === null ? <Tag color="blue">不限量</Tag> : v),
    },
    {
      title: '启用',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 100,
      render: (v: boolean, row: Whitelist) => (
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
        <Popconfirm title="确认删除白名单？" onConfirm={() => handleDelete(row)}>
          <Button type="link" danger size="small">
            删除
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <Card
      title={<Title level={3}>部门用料白名单（PRD-08）</Title>}
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={refresh}>
            刷新
          </Button>
          <Button icon={<PlusOutlined />} type="primary" onClick={() => setCreateOpen(true)}>
            新建白名单
          </Button>
          <Button icon={<ThunderboltOutlined />} onClick={() => setBulkOpen(true)}>
            矩阵授权
          </Button>
        </Space>
      }
    >
      <Alert
        message="部门用料白名单 — 防后厨员工领料串货"
        description={
          <Paragraph style={{ marginBottom: 0 }}>
            <Text>食安总监 / 采购总监配置每个档口可领的食材列表（含日上限可选）。</Text>
            <br />
            <Text>领料 / 扣料路径校验未授权 → 403 Forbidden 硬阻塞，毛利底线硬约束。</Text>
            <br />
            <Text type="secondary">
              提示：max_qty_per_day = NULL 表示不限量（仅校验白名单存在性）；非 NULL 则按日累计扣料上限。
            </Text>
          </Paragraph>
        }
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
      />

      <Space style={{ marginBottom: 16 }} wrap>
        <Input
          placeholder="按 dept_id 过滤（UUID）"
          value={deptFilter}
          onChange={(e) => setDeptFilter(e.target.value)}
          style={{ width: 320 }}
          allowClear
        />
        <span>
          仅启用：
          <Switch checked={onlyActive} onChange={setOnlyActive} />
        </span>
      </Space>

      <Table<Whitelist>
        rowKey="id"
        dataSource={list}
        columns={columns}
        loading={loading}
        scroll={{ x: 1200 }}
        pagination={{ pageSize: 20 }}
      />

      {/* 新建 Modal */}
      <Modal
        open={createOpen}
        title="新建白名单"
        onCancel={() => setCreateOpen(false)}
        onOk={() => form.submit()}
        okText="创建"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" onFinish={handleCreate}>
          <Form.Item
            name="dept_id"
            label="部门 ID（UUID）"
            rules={[{ required: true, message: '必填' }]}
          >
            <Input placeholder="例如：22222222-0001-0001-0001-222222222222" />
          </Form.Item>
          <Form.Item
            name="ingredient_id"
            label="食材 ID（UUID）"
            rules={[{ required: true, message: '必填' }]}
          >
            <Input placeholder="例如：33333333-0001-0001-0001-333333333333" />
          </Form.Item>
          <Form.Item
            name="max_qty_per_day"
            label="日上限（留空 = 不限量）"
            tooltip="按日累计扣料上限；NULL 仅校验白名单存在性"
          >
            <InputNumber<number> min={0.0001} step={0.01} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 矩阵授权 Modal */}
      <Modal
        open={bulkOpen}
        title="矩阵授权（一个部门 → 多食材一次性授权）"
        onCancel={() => setBulkOpen(false)}
        onOk={() => bulkForm.submit()}
        okText="提交授权"
        cancelText="取消"
        width={640}
      >
        <Form form={bulkForm} layout="vertical" onFinish={handleBulkAuthorize}>
          <Form.Item
            name="dept_id"
            label="部门 ID（UUID）"
            rules={[{ required: true, message: '必填' }]}
          >
            <Input placeholder="例如：22222222-0001-0001-0001-222222222222" />
          </Form.Item>
          <Form.Item
            name="ingredient_ids_csv"
            label="食材 ID 列表（逗号 / 换行 / 空格分隔，最多 200）"
            rules={[{ required: true, message: '必填' }]}
            tooltip="已存在的 (dept_id, ingredient_id) 自动 upsert（恢复启用 + 更新上限）"
          >
            <Input.TextArea
              rows={6}
              placeholder={
                '33333333-0001-0001-0001-333333333333\n' +
                '33333333-0002-0002-0002-333333333333'
              }
            />
          </Form.Item>
          <Form.Item
            name="max_qty_per_day"
            label="统一日上限（留空 = 不限量）"
            tooltip="对所有授权的食材生效；逐条精细化授权请用上方'新建白名单'"
          >
            <InputNumber<number> min={0.0001} step={0.01} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}

export default DeptWhitelistPage;
