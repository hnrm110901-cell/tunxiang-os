/**
 * PayrollRecordsPage — 月度薪资管理
 * 域F · 组织人事 · HR Admin
 *
 * 功能：
 *  - ProTable 展示薪资单列表（员工名/门店/薪资周期/应发/实发/状态/操作）
 *  - 状态 Tag 颜色：draft=灰 / approved=蓝 / paid=绿 / voided=红
 *  - 一键计算：ModalForm（员工ID/年/月），POST /calculate
 *  - 批量审批：多选 draft 状态，批量 approve
 *  - 详情抽屉：查看 line_items 明细
 *  - 作废：Popconfirm 二次确认
 *
 * API 基地址: /api/v1/payroll/records
 * X-Tenant-ID 通过 txFetchData 统一注入
 */

import { useRef, useState } from 'react';
import { formatPrice } from '@tx-ds/utils';
import {
  Button,
  Descriptions,
  Drawer,
  Popconfirm,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  CalculatorOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormDigit,
  ProFormSelect,
  ProTable,
} from '@ant-design/pro-components';
import type { ColumnsType } from 'antd/es/table';
import { txFetchData } from '../../api';

const { Title } = Typography;

// ─── 类型 ────────────────────────────────────────────────────────────────────

type RecordStatus = 'draft' | 'approved' | 'paid' | 'voided';

interface PayrollRecord {
  id: string;
  employee_id: string;
  employee_name: string;
  store_id: string;
  store_name?: string;
  pay_year: number;
  pay_month: number;
  gross_amount: number;   // fen — 应发
  net_amount: number;     // fen — 实发
  status: RecordStatus;
  created_at: string;
}

interface PayrollLineItem {
  id: string;
  item_type: string;
  item_name: string;
  amount: number;         // fen
  note?: string;
}

interface RecordListResp {
  items: PayrollRecord[];
  total: number;
}

// ─── 枚举 ────────────────────────────────────────────────────────────────────

const STATUS_TAG: Record<RecordStatus, { color: string; label: string }> = {
  draft:    { color: 'default', label: '草稿'  },
  approved: { color: 'blue',    label: '已审批' },
  paid:     { color: 'green',   label: '已发放' },
  voided:   { color: 'red',     label: '已作废' },
};

const STATUS_ENUM: Record<string, { text: string; status: string }> = {
  draft:    { text: '草稿',   status: 'Default'   },
  approved: { text: '已审批', status: 'Processing' },
  paid:     { text: '已发放', status: 'Success'    },
  voided:   { text: '已作废', status: 'Error'      },
};

// ─── 金额工具 ─────────────────────────────────────────────────────────────────

/** @deprecated Use formatPrice from @tx-ds/utils */
const fenToYuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

// ─── 页面组件 ─────────────────────────────────────────────────────────────────

export function PayrollRecordsPage() {
  const actionRef = useRef<ActionType>(null);
  const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>([]);
  const [drawerRecord, setDrawerRecord] = useState<PayrollRecord | null>(null);
  const [lineItems, setLineItems] = useState<PayrollLineItem[]>([]);
  const [drawerLoading, setDrawerLoading] = useState(false);
  const [messageApi, contextHolder] = message.useMessage();

  // ─── 列定义 ─────────────────────────────────────────────────────────────────

  const columns: ProColumns<PayrollRecord>[] = [
    {
      title: '员工',
      dataIndex: 'employee_name',
      width: 100,
    },
    {
      title: '门店',
      dataIndex: 'store_id',
      renderText: (_, r) => r.store_name || r.store_id,
      width: 140,
    },
    {
      title: '薪资周期',
      key: 'period',
      width: 110,
      hideInSearch: true,
      render: (_, r) => `${r.pay_year}年${String(r.pay_month).padStart(2, '0')}月`,
    },
    {
      title: '年',
      dataIndex: 'pay_year',
      valueType: 'digit',
      hideInTable: true,
    },
    {
      title: '月',
      dataIndex: 'pay_month',
      valueType: 'digit',
      hideInTable: true,
    },
    {
      title: '应发金额',
      dataIndex: 'gross_amount',
      hideInSearch: true,
      width: 110,
      renderText: (v: number) => fenToYuan(v),
    },
    {
      title: '实发金额',
      dataIndex: 'net_amount',
      hideInSearch: true,
      width: 110,
      renderText: (v: number) => fenToYuan(v),
    },
    {
      title: '状态',
      dataIndex: 'status',
      valueType: 'select',
      valueEnum: STATUS_ENUM,
      width: 90,
      render: (_, r) => {
        const cfg = STATUS_TAG[r.status] ?? { color: 'default', label: r.status };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: '操作',
      valueType: 'option',
      width: 160,
      render: (_, record) => [
        <a key="detail" onClick={() => handleOpenDrawer(record)}>
          详情
        </a>,
        record.status === 'draft' && (
          <a
            key="approve"
            onClick={() => handleApprove([record.id])}
            style={{ color: '#185FA5' }}
          >
            审批
          </a>
        ),
        (record.status === 'draft' || record.status === 'approved') && (
          <Popconfirm
            key="void"
            title="确认作废此薪资单？此操作不可恢复。"
            onConfirm={() => handleVoid(record.id)}
            okText="确认作废"
            okButtonProps={{ danger: true }}
            cancelText="取消"
          >
            <a style={{ color: '#A32D2D' }}>作废</a>
          </Popconfirm>
        ),
      ].filter(Boolean),
    },
  ];

  // ─── 数据请求 ────────────────────────────────────────────────────────────────

  const handleRequest = async (params: {
    employee_name?: string;
    store_id?: string;
    status?: string;
    pay_year?: number;
    pay_month?: number;
    current?: number;
    pageSize?: number;
  }) => {
    const query = new URLSearchParams();
    if (params.employee_name) query.set('employee_name', params.employee_name);
    if (params.store_id)      query.set('store_id', params.store_id);
    if (params.status)        query.set('status', params.status);
    if (params.pay_year)      query.set('pay_year', String(params.pay_year));
    if (params.pay_month)     query.set('pay_month', String(params.pay_month));
    query.set('page',  String(params.current  ?? 1));
    query.set('size',  String(params.pageSize ?? 20));

    try {
      const data = await txFetchData<RecordListResp>(
        `/api/v1/payroll/records?${query.toString()}`,
      );
      return { data: data.items, total: data.total, success: true };
    } catch (err) {
      messageApi.error(`加载薪资单失败：${(err as Error).message}`);
      return { data: [], total: 0, success: false };
    }
  };

  // ─── 一键计算 ────────────────────────────────────────────────────────────────

  const handleCalculate = async (values: {
    employee_id: string;
    pay_year: number;
    pay_month: number;
  }) => {
    try {
      await txFetchData('/api/v1/payroll/calculate', {
        method: 'POST',
        body: JSON.stringify(values),
      });
      messageApi.success('薪资计算成功，已生成草稿');
      actionRef.current?.reload();
      return true;
    } catch (err) {
      messageApi.error(`计算失败：${(err as Error).message}`);
      return false;
    }
  };

  // ─── 审批（单条 / 批量）────────────────────────────────────────────────────

  const handleApprove = async (ids: string[]) => {
    try {
      await Promise.all(
        ids.map((id) =>
          txFetchData(`/api/v1/payroll/records/${id}/approve`, { method: 'POST' }),
        ),
      );
      messageApi.success(`已审批 ${ids.length} 条薪资单`);
      setSelectedRowKeys([]);
      actionRef.current?.reload();
    } catch (err) {
      messageApi.error(`审批失败：${(err as Error).message}`);
    }
  };

  // ─── 作废 ────────────────────────────────────────────────────────────────────

  const handleVoid = async (id: string) => {
    try {
      await txFetchData(`/api/v1/payroll/records/${id}/void`, { method: 'POST' });
      messageApi.success('薪资单已作废');
      actionRef.current?.reload();
    } catch (err) {
      messageApi.error(`作废失败：${(err as Error).message}`);
    }
  };

  // ─── 详情抽屉 ────────────────────────────────────────────────────────────────

  const handleOpenDrawer = async (record: PayrollRecord) => {
    setDrawerRecord(record);
    setDrawerLoading(true);
    setLineItems([]);
    try {
      const items = await txFetchData<PayrollLineItem[]>(
        `/api/v1/payroll/records/${record.id}/items`,
      );
      setLineItems(items);
    } catch (err) {
      messageApi.error(`加载明细失败：${(err as Error).message}`);
    } finally {
      setDrawerLoading(false);
    }
  };

  // ─── 明细列 ──────────────────────────────────────────────────────────────────

  const lineItemColumns: ColumnsType<PayrollLineItem> = [
    { title: '类型',   dataIndex: 'item_type', width: 100 },
    { title: '项目',   dataIndex: 'item_name', width: 140 },
    {
      title:  '金额',
      dataIndex: 'amount',
      width: 120,
      render: (v: number) => fenToYuan(v),
    },
    { title: '备注', dataIndex: 'note', ellipsis: true },
  ];

  // ─── 渲染 ────────────────────────────────────────────────────────────────────

  return (
    <>
      {contextHolder}

      <ProTable<PayrollRecord>
        headerTitle="月度薪资管理"
        rowKey="id"
        actionRef={actionRef}
        columns={columns}
        request={handleRequest}
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 20, showSizeChanger: true }}
        rowSelection={{
          selectedRowKeys,
          onChange: (keys) => setSelectedRowKeys(keys as string[]),
          getCheckboxProps: (r) => ({ disabled: r.status !== 'draft' }),
        }}
        toolBarRender={() => [
          selectedRowKeys.length > 0 && (
            <Button
              key="batch-approve"
              type="default"
              icon={<CheckCircleOutlined />}
              onClick={() => handleApprove(selectedRowKeys)}
            >
              批量审批（{selectedRowKeys.length}）
            </Button>
          ),
          <ModalForm
            key="calculate"
            title="一键计算薪资"
            trigger={
              <Button type="primary" icon={<CalculatorOutlined />}>
                一键计算
              </Button>
            }
            onFinish={handleCalculate}
            modalProps={{ destroyOnClose: true }}
            width={440}
          >
            <ProFormSelect
              name="employee_id"
              label="员工 ID"
              rules={[{ required: true, message: '请输入员工 ID' }]}
              showSearch
              fieldProps={{ placeholder: '输入员工 ID' }}
              // 实际项目可替换为 request 远程搜索
              options={[]}
              tooltip="输入员工 ID 后计算该员工当月薪资"
            />
            <ProFormDigit
              name="pay_year"
              label="年份"
              rules={[{ required: true }]}
              fieldProps={{ precision: 0, placeholder: '如 2026' }}
              min={2020}
              max={2099}
            />
            <ProFormDigit
              name="pay_month"
              label="月份"
              rules={[{ required: true }]}
              fieldProps={{ precision: 0, placeholder: '1~12' }}
              min={1}
              max={12}
            />
          </ModalForm>,
        ].filter(Boolean)}
      />

      {/* 详情抽屉 */}
      <Drawer
        title={
          drawerRecord
            ? `薪资单详情 · ${drawerRecord.employee_name} · ${drawerRecord.pay_year}年${String(drawerRecord.pay_month).padStart(2, '0')}月`
            : '薪资单详情'
        }
        open={!!drawerRecord}
        onClose={() => setDrawerRecord(null)}
        width={640}
        extra={
          drawerRecord && (
            <Tag color={STATUS_TAG[drawerRecord.status]?.color ?? 'default'}>
              {STATUS_TAG[drawerRecord.status]?.label ?? drawerRecord.status}
            </Tag>
          )
        }
      >
        {drawerRecord && (
          <>
            <Descriptions bordered column={2} size="small" style={{ marginBottom: 24 }}>
              <Descriptions.Item label="员工">{drawerRecord.employee_name}</Descriptions.Item>
              <Descriptions.Item label="门店">{drawerRecord.store_name || drawerRecord.store_id}</Descriptions.Item>
              <Descriptions.Item label="薪资周期">
                {drawerRecord.pay_year}年{String(drawerRecord.pay_month).padStart(2, '0')}月
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={STATUS_TAG[drawerRecord.status]?.color ?? 'default'}>
                  {STATUS_TAG[drawerRecord.status]?.label ?? drawerRecord.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="应发金额">
                <strong>{fenToYuan(drawerRecord.gross_amount)}</strong>
              </Descriptions.Item>
              <Descriptions.Item label="实发金额">
                <strong style={{ color: '#0F6E56' }}>{fenToYuan(drawerRecord.net_amount)}</strong>
              </Descriptions.Item>
            </Descriptions>

            <Title level={5}>薪资明细</Title>
            <Table<PayrollLineItem>
              rowKey="id"
              loading={drawerLoading}
              dataSource={lineItems}
              columns={lineItemColumns}
              pagination={false}
              size="small"
              bordered
              summary={(data) => {
                const total = data.reduce((s, r) => s + r.amount, 0);
                return (
                  <Table.Summary.Row>
                    <Table.Summary.Cell index={0} colSpan={2}>
                      <strong>合计</strong>
                    </Table.Summary.Cell>
                    <Table.Summary.Cell index={2}>
                      <strong>{fenToYuan(total)}</strong>
                    </Table.Summary.Cell>
                    <Table.Summary.Cell index={3} />
                  </Table.Summary.Row>
                );
              }}
            />

            {/* 快捷操作 */}
            {(drawerRecord.status === 'draft' || drawerRecord.status === 'approved') && (
              <Space style={{ marginTop: 16 }}>
                {drawerRecord.status === 'draft' && (
                  <Button
                    type="primary"
                    icon={<CheckCircleOutlined />}
                    onClick={() => {
                      handleApprove([drawerRecord.id]);
                      setDrawerRecord(null);
                    }}
                  >
                    审批通过
                  </Button>
                )}
                <Popconfirm
                  title="确认作废此薪资单？"
                  onConfirm={() => {
                    handleVoid(drawerRecord.id);
                    setDrawerRecord(null);
                  }}
                  okText="确认作废"
                  okButtonProps={{ danger: true }}
                  cancelText="取消"
                >
                  <Button danger>作废</Button>
                </Popconfirm>
              </Space>
            )}
          </>
        )}
      </Drawer>
    </>
  );
}
