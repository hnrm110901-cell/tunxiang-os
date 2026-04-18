/**
 * ContractSigningPage -- 签署管理
 * 域F - 组织人事 - 电子签约
 *
 * 功能：
 *  1. 顶部统计卡片（总数/已完成/待签/已终止/即将到期）
 *  2. ProTable 签署记录列表 + 状态筛选
 *  3. 发起签署 ModalForm
 *  4. 员工签署/企业盖章/终止操作按钮
 *
 * API 前缀: /api/v1/e-signature
 */

import { useEffect, useRef, useState } from 'react';
import {
  Button,
  Card,
  Col,
  message,
  Modal,
  Row,
  Space,
  Statistic,
  Tag,
  Typography,
} from 'antd';
import {
  ModalForm,
  ProFormDatePicker,
  ProFormSelect,
  ProFormText,
  ProTable,
} from '@ant-design/pro-components';
import type { ActionType, ProColumns } from '@ant-design/pro-components';
import {
  AuditOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  EditOutlined,
  PlusOutlined,
  SendOutlined,
} from '@ant-design/icons';
import type {
  ContractStats,
  ContractTemplate,
  SigningRecord,
} from '../../../api/contractApi';
import {
  companySignContract,
  employeeSignContract,
  fetchContractStats,
  fetchContractTemplates,
  fetchSigningRecords,
  initiateContractSigning,
  terminateContract,
} from '../../../api/contractApi';

const { Title } = Typography;
const TX_PRIMARY = '#FF6B35';

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  draft:            { label: '草稿',     color: 'default' },
  pending_sign:     { label: '待签署',   color: 'gold' },
  employee_signed:  { label: '员工已签', color: 'blue' },
  completed:        { label: '已完成',   color: 'green' },
  expired:          { label: '已过期',   color: 'red' },
  terminated:       { label: '已终止',   color: 'default' },
};

const TYPE_COLOR: Record<string, string> = {
  labor: 'blue',
  confidentiality: 'purple',
  non_compete: 'red',
  internship: 'cyan',
  part_time: 'green',
};

export default function ContractSigningPage() {
  const actionRef = useRef<ActionType>();
  const [stats, setStats] = useState<ContractStats | null>(null);
  const [initiateOpen, setInitiateOpen] = useState(false);
  const [templates, setTemplates] = useState<ContractTemplate[]>([]);
  const [terminateModalId, setTerminateModalId] = useState<string | null>(null);
  const [terminateReason, setTerminateReason] = useState('');

  useEffect(() => {
    fetchContractStats()
      .then(setStats)
      .catch(() => {});
    fetchContractTemplates()
      .then((r) => setTemplates(r.items || []))
      .catch(() => {});
  }, []);

  const reloadAll = () => {
    actionRef.current?.reload();
    fetchContractStats().then(setStats).catch(() => {});
  };

  const columns: ProColumns<SigningRecord>[] = [
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
      title: '状态',
      dataIndex: 'status',
      width: 120,
      render: (_, record) => {
        const s = STATUS_MAP[record.status] || { label: record.status, color: 'default' };
        return <Tag color={s.color}>{s.label}</Tag>;
      },
      valueEnum: Object.fromEntries(
        Object.entries(STATUS_MAP).map(([k, v]) => [k, { text: v.label }]),
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
      title: '创建时间',
      dataIndex: 'created_at',
      valueType: 'dateTime',
      width: 170,
      search: false,
    },
    {
      title: '操作',
      valueType: 'option',
      width: 240,
      render: (_, record) => (
        <Space size={4}>
          {record.status === 'pending_sign' && (
            <Button
              size="small"
              icon={<EditOutlined />}
              onClick={async () => {
                try {
                  await employeeSignContract(record.id);
                  message.success('员工签署完成');
                  reloadAll();
                } catch {
                  message.error('签署失败');
                }
              }}
            >
              员工签署
            </Button>
          )}
          {record.status === 'employee_signed' && (
            <Button
              size="small"
              type="primary"
              icon={<CheckCircleOutlined />}
              style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
              onClick={async () => {
                const signerId = localStorage.getItem('tx_user_id');
                if (!signerId) {
                  message.error('无法获取当前用户ID，请重新登录后再操作');
                  return;
                }
                try {
                  await companySignContract(record.id, signerId);
                  message.success('企业盖章完成，合同已生效');
                  reloadAll();
                } catch {
                  message.error('盖章失败');
                }
              }}
            >
              企业盖章
            </Button>
          )}
          {['pending_sign', 'employee_signed', 'completed'].includes(record.status) && (
            <Button
              size="small"
              danger
              icon={<CloseCircleOutlined />}
              onClick={() => setTerminateModalId(record.id)}
            >
              终止
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Title level={4}>
        <AuditOutlined style={{ color: TX_PRIMARY, marginRight: 8 }} />
        签署管理
      </Title>

      {/* 统计卡片 */}
      {stats && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={4}>
            <Card size="small">
              <Statistic title="合同总数" value={stats.total} />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small">
              <Statistic title="已完成" value={stats.completed} valueStyle={{ color: '#52c41a' }} />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small">
              <Statistic title="待签署" value={stats.pending} valueStyle={{ color: '#faad14' }} />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small">
              <Statistic title="已终止" value={stats.terminated} />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small">
              <Statistic title="已过期" value={stats.expired} valueStyle={{ color: '#ff4d4f' }} />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small">
              <Statistic
                title="30天内到期"
                value={stats.expiring_30d}
                valueStyle={{ color: '#fa8c16' }}
              />
            </Card>
          </Col>
        </Row>
      )}

      <ProTable<SigningRecord>
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        headerTitle="签署记录"
        search={{ labelWidth: 'auto' }}
        toolBarRender={() => [
          <Button
            key="initiate"
            type="primary"
            icon={<SendOutlined />}
            onClick={() => setInitiateOpen(true)}
            style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
          >
            发起签署
          </Button>,
        ]}
        request={async (params) => {
          try {
            const result = await fetchSigningRecords({
              status: params.status,
              page: params.current || 1,
              size: params.pageSize || 20,
            });
            return { data: result.items, total: result.total, success: true };
          } catch {
            message.error('加载签署记录失败');
            return { data: [], total: 0, success: false };
          }
        }}
        pagination={{ pageSize: 20 }}
      />

      {/* 发起签署 */}
      <ModalForm
        title="发起合同签署"
        open={initiateOpen}
        onOpenChange={setInitiateOpen}
        width={600}
        onFinish={async (values) => {
          try {
            const result = await initiateContractSigning({
              template_id: values.template_id,
              employee_id: values.employee_id,
              start_date: values.start_date,
              end_date: values.end_date,
              store_id: values.store_id || undefined,
            });
            message.success(`签署已发起，合同编号: ${result.contract_no}`);
            reloadAll();
            return true;
          } catch {
            message.error('发起签署失败');
            return false;
          }
        }}
      >
        <ProFormSelect
          name="template_id"
          label="合同模板"
          rules={[{ required: true, message: '请选择模板' }]}
          options={templates
            .filter((t) => t.is_active)
            .map((t) => ({
              label: `${t.template_name} (${t.contract_type_label})`,
              value: t.id,
            }))}
          placeholder="选择合同模板"
        />
        <ProFormText
          name="employee_id"
          label="员工ID"
          rules={[{ required: true, message: '请输入员工ID' }]}
          placeholder="员工UUID"
        />
        <ProFormText
          name="store_id"
          label="门店ID(可选)"
          placeholder="门店UUID"
        />
        <ProFormDatePicker
          name="start_date"
          label="合同开始日期"
          rules={[{ required: true, message: '请选择开始日期' }]}
          fieldProps={{ format: 'YYYY-MM-DD' }}
        />
        <ProFormDatePicker
          name="end_date"
          label="合同结束日期"
          rules={[{ required: true, message: '请选择结束日期' }]}
          fieldProps={{ format: 'YYYY-MM-DD' }}
        />
      </ModalForm>

      {/* 终止确认 */}
      <Modal
        title="终止合同"
        open={!!terminateModalId}
        onCancel={() => {
          setTerminateModalId(null);
          setTerminateReason('');
        }}
        onOk={async () => {
          if (!terminateModalId || !terminateReason.trim()) {
            message.warning('请输入终止原因');
            return;
          }
          try {
            await terminateContract(terminateModalId, terminateReason.trim());
            message.success('合同已终止');
            setTerminateModalId(null);
            setTerminateReason('');
            reloadAll();
          } catch {
            message.error('终止失败');
          }
        }}
      >
        <p>请输入终止原因：</p>
        <input
          style={{ width: '100%', padding: 8, border: '1px solid #d9d9d9', borderRadius: 4 }}
          value={terminateReason}
          onChange={(e) => setTerminateReason(e.target.value)}
          placeholder="终止原因"
        />
      </Modal>
    </div>
  );
}
