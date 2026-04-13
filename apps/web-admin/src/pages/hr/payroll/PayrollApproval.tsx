/**
 * PayrollApproval — 薪资审批 (P0)
 * 域F · 组织人事 · HR Admin
 *
 * 功能：
 *  - ProTable展示待审批薪资单（员工/月份/应发/实发/状态）
 *  - 批量审批：勾选多行后一键审批
 *  - 详情弹窗：展示薪资明细（基本工资+绩效+补贴-社保-公积金-个税=实发）
 *
 * API: GET  /api/v1/payroll/records?status=pending_approval
 *      POST /api/v1/payroll/records/{id}/approve
 */

import { useRef, useState } from 'react';
import {
  Button,
  Descriptions,
  Modal,
  Space,
  Tag,
  Typography,
  message,
} from 'antd';
import { CheckCircleOutlined, EyeOutlined } from '@ant-design/icons';
import {
  ActionType,
  ProColumns,
  ProTable,
} from '@ant-design/pro-components';
import { txFetchData } from '../../../api';
import { formatPrice } from '@tx-ds/utils';

const { Title } = Typography;

// ─── Types ───────────────────────────────────────────────────────────────────

type ApprovalStatus = 'pending_approval' | 'approved' | 'rejected';

interface PayrollItem {
  id: string;
  employee_id: string;
  employee_name: string;
  store_name: string;
  pay_year: number;
  pay_month: number;
  base_salary_fen: number;
  performance_fen: number;
  allowance_fen: number;
  social_insurance_fen: number;
  housing_fund_fen: number;
  tax_fen: number;
  gross_amount_fen: number;
  net_amount_fen: number;
  status: ApprovalStatus;
  created_at: string;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

/** @deprecated Use formatPrice from @tx-ds/utils */
const fenToYuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

const STATUS_TAG: Record<ApprovalStatus, { color: string; label: string }> = {
  pending_approval: { color: 'warning', label: '待审批' },
  approved: { color: 'success', label: '已审批' },
  rejected: { color: 'error', label: '已拒绝' },
};

// ─── Component ───────────────────────────────────────────────────────────────

export default function PayrollApproval() {
  const actionRef = useRef<ActionType>(null);
  const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>([]);
  const [detailVisible, setDetailVisible] = useState(false);
  const [detailRecord, setDetailRecord] = useState<PayrollItem | null>(null);
  const [batchLoading, setBatchLoading] = useState(false);
  const [messageApi, contextHolder] = message.useMessage();

  // ─── 批量审批 ────────────────────────────────────────────────────────────

  const handleBatchApprove = async () => {
    if (selectedRowKeys.length === 0) {
      messageApi.warning('请先选择要审批的薪资单');
      return;
    }
    setBatchLoading(true);
    try {
      let successCount = 0;
      for (const id of selectedRowKeys) {
        const res = await txFetchData(`/api/v1/payroll/records/${id}/approve`, {
          method: 'POST',
        }) as { ok: boolean };
        if (res.ok) successCount++;
      }
      messageApi.success(`成功审批 ${successCount} 条薪资单`);
      setSelectedRowKeys([]);
      actionRef.current?.reload();
    } catch (err) {
      messageApi.error('批量审批失败');
    } finally {
      setBatchLoading(false);
    }
  };

  // ─── Columns ─────────────────────────────────────────────────────────────

  const columns: ProColumns<PayrollItem>[] = [
    { title: '员工', dataIndex: 'employee_name', width: 100 },
    { title: '门店', dataIndex: 'store_name', width: 140, hideInSearch: true },
    {
      title: '薪资周期',
      key: 'period',
      width: 110,
      hideInSearch: true,
      render: (_, r) => `${r.pay_year}年${String(r.pay_month).padStart(2, '0')}月`,
    },
    {
      title: '应发',
      dataIndex: 'gross_amount_fen',
      width: 110,
      hideInSearch: true,
      renderText: (v: number) => fenToYuan(v),
    },
    {
      title: '实发',
      dataIndex: 'net_amount_fen',
      width: 110,
      hideInSearch: true,
      renderText: (v: number) => fenToYuan(v),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      valueEnum: {
        pending_approval: { text: '待审批', status: 'Warning' },
        approved: { text: '已审批', status: 'Success' },
        rejected: { text: '已拒绝', status: 'Error' },
      },
      render: (_, r) => {
        const t = STATUS_TAG[r.status];
        return <Tag color={t.color}>{t.label}</Tag>;
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 140,
      hideInSearch: true,
      render: (_, r) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => {
              setDetailRecord(r);
              setDetailVisible(true);
            }}
          >
            详情
          </Button>
          {r.status === 'pending_approval' && (
            <Button
              type="link"
              size="small"
              icon={<CheckCircleOutlined />}
              onClick={async () => {
                const res = await txFetchData(`/api/v1/payroll/records/${r.id}/approve`, {
                  method: 'POST',
                }) as { ok: boolean };
                if (res.ok) {
                  messageApi.success('审批通过');
                  actionRef.current?.reload();
                }
              }}
            >
              审批
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      {contextHolder}
      <Title level={4}>薪资审批</Title>

      <ProTable<PayrollItem>
        headerTitle="待审批薪资单"
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        search={{ labelWidth: 80 }}
        rowSelection={{
          selectedRowKeys,
          onChange: (keys) => setSelectedRowKeys(keys as string[]),
          getCheckboxProps: (r) => ({
            disabled: r.status !== 'pending_approval',
          }),
        }}
        toolBarRender={() => [
          <Button
            key="batch"
            type="primary"
            icon={<CheckCircleOutlined />}
            loading={batchLoading}
            disabled={selectedRowKeys.length === 0}
            onClick={handleBatchApprove}
            style={{ backgroundColor: '#FF6B35', borderColor: '#FF6B35' }}
          >
            批量审批 ({selectedRowKeys.length})
          </Button>,
        ]}
        request={async (params) => {
          const query = new URLSearchParams();
          query.set('status', 'pending_approval');
          if (params.employee_name) query.set('employee_name', params.employee_name);
          query.set('page', String(params.current ?? 1));
          query.set('size', String(params.pageSize ?? 20));
          try {
            const res = await txFetchData(`/api/v1/payroll/records?${query}`) as {
              ok: boolean;
              data: { items: PayrollItem[]; total: number };
            };
            if (res.ok) {
              return { data: res.data.items, total: res.data.total, success: true };
            }
          } catch { /* fallback */ }
          return { data: [], total: 0, success: true };
        }}
        pagination={{ defaultPageSize: 20 }}
      />

      {/* ── 详情弹窗 ── */}
      <Modal
        title="薪资明细"
        open={detailVisible}
        onCancel={() => setDetailVisible(false)}
        footer={null}
        width={600}
      >
        {detailRecord && (
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="员工">{detailRecord.employee_name}</Descriptions.Item>
            <Descriptions.Item label="门店">{detailRecord.store_name}</Descriptions.Item>
            <Descriptions.Item label="薪资周期">
              {detailRecord.pay_year}年{String(detailRecord.pay_month).padStart(2, '0')}月
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={STATUS_TAG[detailRecord.status].color}>
                {STATUS_TAG[detailRecord.status].label}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="基本工资">{fenToYuan(detailRecord.base_salary_fen)}</Descriptions.Item>
            <Descriptions.Item label="绩效工资">{fenToYuan(detailRecord.performance_fen)}</Descriptions.Item>
            <Descriptions.Item label="补贴">{fenToYuan(detailRecord.allowance_fen)}</Descriptions.Item>
            <Descriptions.Item label="社保(扣)">{fenToYuan(detailRecord.social_insurance_fen)}</Descriptions.Item>
            <Descriptions.Item label="公积金(扣)">{fenToYuan(detailRecord.housing_fund_fen)}</Descriptions.Item>
            <Descriptions.Item label="个税(扣)">{fenToYuan(detailRecord.tax_fen)}</Descriptions.Item>
            <Descriptions.Item label="应发合计" span={2}>
              <span style={{ fontWeight: 'bold', fontSize: 16 }}>
                {fenToYuan(detailRecord.gross_amount_fen)}
              </span>
            </Descriptions.Item>
            <Descriptions.Item label="实发合计" span={2}>
              <span style={{ fontWeight: 'bold', fontSize: 16, color: '#FF6B35' }}>
                {fenToYuan(detailRecord.net_amount_fen)}
              </span>
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </div>
  );
}
