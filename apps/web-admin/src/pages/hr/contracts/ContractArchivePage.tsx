/**
 * ContractArchivePage -- 合同归档查询
 * 域F - 组织人事 - 电子签约
 *
 * 功能：
 *  1. 已完成合同列表（归档查询）
 *  2. 到期提醒列表（30/60/90天可切换）
 *  3. 合同详情抽屉
 *
 * API 前缀: /api/v1/e-signature
 */

import { useEffect, useRef, useState } from 'react';
import {
  Card,
  Descriptions,
  Drawer,
  message,
  Segmented,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import { ProTable } from '@ant-design/pro-components';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import {
  AlertOutlined,
  FolderOpenOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import type {
  ExpiringContract,
  SigningRecord,
  SigningRecordDetail,
} from '../../../api/contractApi';
import {
  fetchExpiringContracts,
  fetchSigningDetail,
  fetchSigningRecords,
} from '../../../api/contractApi';

const { Title, Text } = Typography;
const TX_PRIMARY = '#FF6B35';

const TYPE_COLOR: Record<string, string> = {
  labor: 'blue',
  confidentiality: 'purple',
  non_compete: 'red',
  internship: 'cyan',
  part_time: 'green',
};

export default function ContractArchivePage() {
  const actionRef = useRef<ActionType>();
  const [expiringDays, setExpiringDays] = useState<number>(30);
  const [expiringList, setExpiringList] = useState<ExpiringContract[]>([]);
  const [expiringLoading, setExpiringLoading] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailData, setDetailData] = useState<SigningRecordDetail | null>(null);

  const loadExpiring = async (days: number) => {
    setExpiringLoading(true);
    try {
      const items = await fetchExpiringContracts(days);
      setExpiringList(items);
    } catch {
      message.error('加载到期提醒失败');
    } finally {
      setExpiringLoading(false);
    }
  };

  useEffect(() => {
    loadExpiring(expiringDays);
  }, [expiringDays]);

  const openDetail = async (recordId: string) => {
    try {
      const detail = await fetchSigningDetail(recordId);
      setDetailData(detail);
      setDetailOpen(true);
    } catch {
      message.error('加载合同详情失败');
    }
  };

  // ─── 归档列表列 ─────────────────────────────────────────

  const archiveColumns: ProColumns<SigningRecord>[] = [
    {
      title: '合同编号',
      dataIndex: 'contract_no',
      width: 200,
      copyable: true,
    },
    {
      title: '员工',
      dataIndex: 'employee_name',
      width: 100,
    },
    {
      title: '合同类型',
      dataIndex: 'contract_type',
      width: 120,
      render: (_, record) => (
        <Tag color={TYPE_COLOR[record.contract_type] || 'default'}>
          {record.contract_type_label}
        </Tag>
      ),
    },
    {
      title: '合同期限',
      key: 'period',
      width: 200,
      search: false,
      render: (_, record) =>
        record.start_date && record.end_date
          ? `${record.start_date.slice(0, 10)} ~ ${record.end_date.slice(0, 10)}`
          : '-',
    },
    {
      title: '员工签署',
      dataIndex: 'signed_at',
      valueType: 'dateTime',
      width: 170,
      search: false,
    },
    {
      title: '企业盖章',
      dataIndex: 'company_signed_at',
      valueType: 'dateTime',
      width: 170,
      search: false,
    },
    {
      title: '操作',
      valueType: 'option',
      width: 80,
      render: (_, record) => (
        <a onClick={() => openDetail(record.id)}>查看</a>
      ),
    },
  ];

  // ─── 到期提醒列 ─────────────────────────────────────────

  const expiringColumns = [
    {
      title: '合同编号',
      dataIndex: 'contract_no',
      key: 'contract_no',
      width: 200,
    },
    {
      title: '员工',
      dataIndex: 'employee_name',
      key: 'employee_name',
      width: 100,
    },
    {
      title: '合同类型',
      dataIndex: 'contract_type_label',
      key: 'contract_type_label',
      width: 120,
      render: (text: string, record: ExpiringContract) => (
        <Tag color={TYPE_COLOR[record.contract_type] || 'default'}>{text}</Tag>
      ),
    },
    {
      title: '到期日期',
      dataIndex: 'end_date',
      key: 'end_date',
      width: 120,
      render: (text: string) => text?.slice(0, 10),
    },
    {
      title: '剩余天数',
      dataIndex: 'days_remaining',
      key: 'days_remaining',
      width: 100,
      render: (days: number) => (
        <Tag color={days <= 7 ? 'red' : days <= 14 ? 'orange' : 'gold'}>
          {days} 天
        </Tag>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Title level={4}>
        <FolderOpenOutlined style={{ color: TX_PRIMARY, marginRight: 8 }} />
        合同归档与到期提醒
      </Title>

      {/* 到期提醒 */}
      <Card
        title={
          <Space>
            <AlertOutlined style={{ color: '#fa8c16' }} />
            <span>到期提醒</span>
          </Space>
        }
        extra={
          <Segmented
            value={expiringDays}
            onChange={(v) => setExpiringDays(Number(v))}
            options={[
              { label: '30天', value: 30 },
              { label: '60天', value: 60 },
              { label: '90天', value: 90 },
            ]}
          />
        }
        style={{ marginBottom: 16 }}
      >
        <Table
          dataSource={expiringList}
          columns={expiringColumns}
          rowKey="id"
          loading={expiringLoading}
          pagination={false}
          size="small"
          locale={{ emptyText: '暂无即将到期合同' }}
        />
      </Card>

      {/* 已完成合同归档 */}
      <ProTable<SigningRecord>
        actionRef={actionRef}
        rowKey="id"
        columns={archiveColumns}
        headerTitle="已完成合同归档"
        search={{ labelWidth: 'auto' }}
        request={async (params) => {
          try {
            const result = await fetchSigningRecords({
              status: 'completed',
              page: params.current || 1,
              size: params.pageSize || 20,
            });
            return { data: result.items, total: result.total, success: true };
          } catch {
            message.error('加载归档记录失败');
            return { data: [], total: 0, success: false };
          }
        }}
        pagination={{ pageSize: 20 }}
      />

      {/* 合同详情抽屉 */}
      <Drawer
        title="合同详情"
        open={detailOpen}
        onClose={() => {
          setDetailOpen(false);
          setDetailData(null);
        }}
        width={640}
      >
        {detailData && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="合同编号">{detailData.contract_no}</Descriptions.Item>
            <Descriptions.Item label="员工">{detailData.employee_name}</Descriptions.Item>
            <Descriptions.Item label="合同类型">
              <Tag color={TYPE_COLOR[detailData.contract_type] || 'default'}>
                {detailData.contract_type_label}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={detailData.status === 'completed' ? 'green' : 'default'}>
                {detailData.status_label}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="合同期限">
              {detailData.start_date?.slice(0, 10)} ~ {detailData.end_date?.slice(0, 10)}
            </Descriptions.Item>
            <Descriptions.Item label="员工签署时间">
              {detailData.signed_at || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="企业盖章时间">
              {detailData.company_signed_at || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="第三方签章ID">
              {detailData.e_sign_doc_id || '-'}
            </Descriptions.Item>
            {detailData.content_snapshot && (
              <Descriptions.Item label="合同内容快照">
                <div
                  style={{
                    maxHeight: 300,
                    overflow: 'auto',
                    padding: 8,
                    background: '#fafafa',
                    border: '1px solid #f0f0f0',
                    borderRadius: 4,
                  }}
                  dangerouslySetInnerHTML={{ __html: detailData.content_snapshot }}
                />
              </Descriptions.Item>
            )}
          </Descriptions>
        )}
      </Drawer>
    </div>
  );
}
