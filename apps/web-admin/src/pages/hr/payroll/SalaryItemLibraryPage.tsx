/**
 * SalaryItemLibraryPage -- 薪资项目库管理
 * 域F - 组织人事 - 薪资管理
 *
 * 功能:
 *  - 顶部统计卡片: 总项数/已启用/自定义数
 *  - 按分类 Tab 切换 (7大类 + 全部)
 *  - ProTable 展示薪资项列表
 *  - 启用/禁用开关
 *  - 新建自定义薪资项 ModalForm
 *  - 一键初始化按钮(首次使用时)
 *  - 模板预览功能
 *
 * API:
 *   GET  /api/v1/org/salary-items          (内存模板)
 *   GET  /api/v1/org/salary-items/categories
 *   GET  /api/v1/org/salary-items/template-preview?template=
 *   POST /api/v1/org/salary-items/init-db
 *   POST /api/v1/org/salary-items/custom
 *   PUT  /api/v1/org/salary-items/{item_code}/toggle
 */

import { useRef, useState, useCallback, useEffect } from 'react';
import {
  Card,
  Col,
  Row,
  Statistic,
  Tag,
  Switch,
  Button,
  message,
  Modal,
  Select,
  Typography,
  Space,
  Tabs,
} from 'antd';
import {
  AppstoreOutlined,
  CheckCircleOutlined,
  PlusOutlined,
  ThunderboltOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import { ProColumns, ProTable, ModalForm, ProFormText, ProFormSelect, ProFormDigit, ProFormTextArea } from '@ant-design/pro-components';
import type { ActionType } from '@ant-design/pro-components';
import { txFetchData } from '../../../api';

const { Title, Text } = Typography;
const TX_PRIMARY = '#FF6B35';

// ---- Types ----

interface SalaryItemRow {
  item_code: string;
  item_name: string;
  category: string;
  tax_type: string;
  calc_rule: string;
  formula: string;
  is_required: boolean;
  default_value_fen: number;
  description: string;
  is_enabled?: boolean;
  is_system?: boolean;
}

interface CategoryInfo {
  key: string;
  name: string;
  count: number;
}

// ---- Constants ----

const CATEGORY_LABELS: Record<string, string> = {
  attendance: '出勤类',
  leave: '假期类',
  performance: '���效类',
  commission: '提成类',
  subsidy: '补贴类',
  deduction: '扣款类',
  social: '社保类',
};

const CATEGORY_COLORS: Record<string, string> = {
  attendance: 'blue',
  leave: 'cyan',
  performance: 'gold',
  commission: 'orange',
  subsidy: 'green',
  deduction: 'red',
  social: 'purple',
};

const TAX_TYPE_LABELS: Record<string, { text: string; color: string }> = {
  pre_tax_add: { text: '税前加', color: 'green' },
  pre_tax_sub: { text: '税前减', color: 'red' },
  other: { text: '其他', color: 'default' },
};

const CALC_RULE_LABELS: Record<string, string> = {
  fixed: '固定值',
  formula: '公式',
  manual: '手动填写',
};

const fenToYuan = (fen: number) => (fen / 100).toFixed(2);

// ---- Component ----

export default function SalaryItemLibraryPage() {
  const actionRef = useRef<ActionType>(null);
  const [activeTab, setActiveTab] = useState<string>('all');
  const [categories, setCategories] = useState<CategoryInfo[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [enabledCount, setEnabledCount] = useState(0);
  const [customCount, setCustomCount] = useState(0);
  const [initModalOpen, setInitModalOpen] = useState(false);
  const [initTemplate, setInitTemplate] = useState('standard');
  const [initLoading, setInitLoading] = useState(false);

  // Load categories
  useEffect(() => {
    txFetchData<{ categories: CategoryInfo[] }>('/api/v1/org/salary-items/categories')
      .then((data) => {
        setCategories(data.categories);
        const total = data.categories.reduce((sum, c) => sum + c.count, 0);
        setTotalCount(total);
      })
      .catch(() => { /* silent */ });
  }, []);

  // Handle init
  const handleInit = useCallback(async () => {
    setInitLoading(true);
    try {
      await txFetchData('/api/v1/org/salary-items/init-db', {
        method: 'POST',
        body: JSON.stringify({ template: initTemplate }),
      });
      message.success('薪资项初始化成功');
      setInitModalOpen(false);
      actionRef.current?.reload();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '初始化失败';
      message.error(msg);
    } finally {
      setInitLoading(false);
    }
  }, [initTemplate]);

  // Handle toggle
  const handleToggle = useCallback(async (itemCode: string, checked: boolean) => {
    try {
      await txFetchData(`/api/v1/org/salary-items/${itemCode}/toggle`, {
        method: 'PUT',
        body: JSON.stringify({ is_enabled: checked }),
      });
      message.success(`${itemCode} 已${checked ? '启用' : '禁用'}`);
      actionRef.current?.reload();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '操作失败';
      message.error(msg);
    }
  }, []);

  // Table columns
  const columns: ProColumns<SalaryItemRow>[] = [
    {
      title: '编码',
      dataIndex: 'item_code',
      width: 110,
      fixed: 'left',
      copyable: true,
    },
    {
      title: '名称',
      dataIndex: 'item_name',
      width: 140,
      ellipsis: true,
    },
    {
      title: '分类',
      dataIndex: 'category',
      width: 90,
      render: (_, row) => (
        <Tag color={CATEGORY_COLORS[row.category] ?? 'default'}>
          {CATEGORY_LABELS[row.category] ?? row.category}
        </Tag>
      ),
      filters: Object.entries(CATEGORY_LABELS).map(([k, v]) => ({ text: v, value: k })),
      onFilter: (value, record) => record.category === value,
    },
    {
      title: '税前加减',
      dataIndex: 'tax_type',
      width: 90,
      render: (_, row) => {
        const info = TAX_TYPE_LABELS[row.tax_type];
        return info ? <Tag color={info.color}>{info.text}</Tag> : row.tax_type;
      },
    },
    {
      title: '计算规则',
      dataIndex: 'calc_rule',
      width: 90,
      render: (_, row) => CALC_RULE_LABELS[row.calc_rule] ?? row.calc_rule,
    },
    {
      title: '默认值(元)',
      dataIndex: 'default_value_fen',
      width: 100,
      render: (_, row) =>
        row.default_value_fen > 0 ? (
          <Text strong>{fenToYuan(row.default_value_fen)}</Text>
        ) : (
          <Text type="secondary">-</Text>
        ),
      sorter: (a, b) => a.default_value_fen - b.default_value_fen,
    },
    {
      title: '公式',
      dataIndex: 'formula',
      width: 200,
      ellipsis: true,
      render: (_, row) =>
        row.formula ? (
          <Text code style={{ fontSize: 12 }}>
            {row.formula}
          </Text>
        ) : (
          <Text type="secondary">-</Text>
        ),
    },
    {
      title: '必填',
      dataIndex: 'is_required',
      width: 60,
      render: (_, row) =>
        row.is_required ? <Tag color="red">必填</Tag> : null,
    },
    {
      title: '说明',
      dataIndex: 'description',
      width: 200,
      ellipsis: true,
    },
    {
      title: '状态',
      dataIndex: 'is_enabled',
      width: 80,
      fixed: 'right',
      render: (_, row) => (
        <Switch
          size="small"
          checked={row.is_enabled !== false}
          onChange={(checked) => handleToggle(row.item_code, checked)}
        />
      ),
    },
  ];

  // Tab items
  const tabItems = [
    { key: 'all', label: `全部 (${totalCount})` },
    ...categories.map((c) => ({
      key: c.key,
      label: `${c.name} (${c.count})`,
    })),
  ];

  return (
    <div style={{ padding: 24 }}>
      <Title level={4} style={{ marginBottom: 16 }}>
        <SettingOutlined style={{ marginRight: 8, color: TX_PRIMARY }} />
        薪资项目库
      </Title>

      {/* Stats Cards */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card>
            <Statistic
              title="总项数"
              value={totalCount}
              prefix={<AppstoreOutlined style={{ color: TX_PRIMARY }} />}
              suffix="项"
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="已启用"
              value={enabledCount || totalCount}
              prefix={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
              suffix="项"
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="自定义"
              value={customCount}
              prefix={<PlusOutlined style={{ color: '#1890ff' }} />}
              suffix="项"
              valueStyle={{ color: '#1890ff' }}
            />
          </Card>
        </Col>
      </Row>

      {/* Category Tabs */}
      <Tabs
        activeKey={activeTab}
        onChange={(key) => {
          setActiveTab(key);
          actionRef.current?.reload();
        }}
        items={tabItems}
        style={{ marginBottom: 0 }}
      />

      {/* Main Table */}
      <ProTable<SalaryItemRow>
        actionRef={actionRef}
        rowKey="item_code"
        columns={columns}
        scroll={{ x: 1200 }}
        search={false}
        options={{ density: true, fullScreen: true }}
        headerTitle={
          <Space>
            <Text type="secondary">
              {activeTab === 'all' ? '全部薪资项' : CATEGORY_LABELS[activeTab]}
            </Text>
          </Space>
        }
        toolBarRender={() => [
          <Button
            key="init"
            icon={<ThunderboltOutlined />}
            onClick={() => setInitModalOpen(true)}
          >
            一键初始化
          </Button>,
          <ModalForm<{
            item_code: string;
            item_name: string;
            category: string;
            tax_type: string;
            calc_rule: string;
            formula: string;
            default_value_fen: number;
            description: string;
          }>
            key="add"
            title="新建自定义薪资项"
            trigger={
              <Button type="primary" icon={<PlusOutlined />}>
                新建薪资项
              </Button>
            }
            onFinish={async (values) => {
              try {
                await txFetchData('/api/v1/org/salary-items/custom', {
                  method: 'POST',
                  body: JSON.stringify({
                    ...values,
                    default_value_fen: Math.round((values.default_value_fen || 0) * 100),
                  }),
                });
                message.success('自定义薪资项创建成功');
                actionRef.current?.reload();
                return true;
              } catch (err: unknown) {
                const msg = err instanceof Error ? err.message : '创建失败';
                message.error(msg);
                return false;
              }
            }}
          >
            <ProFormText
              name="item_code"
              label="项目编码"
              placeholder="如 CUSTOM_001"
              rules={[{ required: true, message: '请输入项目编码' }]}
            />
            <ProFormText
              name="item_name"
              label="项目名称"
              rules={[{ required: true, message: '请输入项目名称' }]}
            />
            <ProFormSelect
              name="category"
              label="分类"
              rules={[{ required: true, message: '请选择分类' }]}
              options={Object.entries(CATEGORY_LABELS).map(([k, v]) => ({
                value: k,
                label: v,
              }))}
            />
            <ProFormSelect
              name="tax_type"
              label="税前加减"
              initialValue="pre_tax_add"
              options={[
                { value: 'pre_tax_add', label: '税前加' },
                { value: 'pre_tax_sub', label: '税前减' },
                { value: 'other', label: '其他' },
              ]}
            />
            <ProFormSelect
              name="calc_rule"
              label="计算规则"
              initialValue="manual"
              options={[
                { value: 'fixed', label: '固定值' },
                { value: 'formula', label: '公式' },
                { value: 'manual', label: '手动填写' },
              ]}
            />
            <ProFormText name="formula" label="公式" placeholder="如 base_salary_fen * 0.1" />
            <ProFormDigit
              name="default_value_fen"
              label="默认值(元)"
              min={0}
              fieldProps={{ precision: 2 }}
            />
            <ProFormTextArea name="description" label="说明" />
          </ModalForm>,
        ]}
        request={async () => {
          try {
            const params = activeTab !== 'all' ? `?category=${activeTab}` : '';
            const data = await txFetchData<{ items: SalaryItemRow[]; total: number }>(
              `/api/v1/org/salary-items${params}`,
            );
            // Update counts
            const items = data.items || [];
            if (activeTab === 'all') {
              setTotalCount(items.length);
              setEnabledCount(items.filter((i) => i.is_enabled !== false).length);
              setCustomCount(items.filter((i) => i.is_system === false).length);
            }
            return { data: items, total: items.length, success: true };
          } catch {
            return { data: [], total: 0, success: true };
          }
        }}
        pagination={{
          defaultPageSize: 20,
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 项`,
        }}
      />

      {/* Init Modal */}
      <Modal
        title="一键初始化薪资项"
        open={initModalOpen}
        onCancel={() => setInitModalOpen(false)}
        onOk={handleInit}
        confirmLoading={initLoading}
        okText="确认初始化"
      >
        <div style={{ marginBottom: 16 }}>
          <Text>选择适合您门店的薪资模板，系统将为您初始化标准薪资项目：</Text>
        </div>
        <Select
          style={{ width: '100%' }}
          value={initTemplate}
          onChange={setInitTemplate}
          options={[
            { value: 'standard', label: '标准中餐 — 适用于中餐正餐门店' },
            { value: 'seafood', label: '海鲜酒楼 — 适用于高端海鲜/酒楼餐饮' },
            { value: 'fast_food', label: '快餐 — 适用于快餐、小吃等轻餐饮' },
          ]}
        />
        <div style={{ marginTop: 12 }}>
          <Text type="secondary">
            初始化后，系统将根据模板启用/禁用对应薪资项并设置默认值。您也可以后续自行调整。
          </Text>
        </div>
      </Modal>
    </div>
  );
}
