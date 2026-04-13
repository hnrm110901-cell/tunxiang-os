/**
 * 企业挂账管理后台
 * 域A — 交易履约 → 企业挂账
 *
 * Tab1: 企业列表（搜索、新建、调整额度、停用、侧抽屉签单记录）
 * Tab2: 签单记录（筛选、汇总）
 * Tab3: 月结对账（生成月结账单）
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Divider,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Progress,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined, ExclamationCircleOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import {
  createEnterprise,
  disableEnterprise,
  getAuditTrail,
  listEnterprises,
  monthlySettlement,
  updateEnterprise,
  updateEnterpriseCreditLimit,
} from '../../api/enterpriseAdminApi';
import type {
  EnterpriseAccount,
  EnterpriseSignRecord,
  EnterpriseStatement,
} from '../../api/enterpriseAdminApi';
import { txFetchData } from '../../api';
import { formatPrice } from '@tx-ds/utils';

const { Title, Text } = Typography;
const { confirm } = Modal;

// ─── 工具函数 ───

/** @deprecated Use formatPrice from @tx-ds/utils */
function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

function yuanToFen(yuan: number): number {
  return Math.round(yuan * 100);
}

// ─── 状态 Tag ───

function StatusTag({ status }: { status: string }) {
  return status === 'active' ? (
    <Tag color="green">正常</Tag>
  ) : (
    <Tag color="default">已停用</Tag>
  );
}

function SignStatusTag({ status }: { status: string }) {
  return status === 'paid' ? (
    <Tag color="green">已还款</Tag>
  ) : (
    <Tag color="orange">未还款</Tag>
  );
}

// ─── Tab1：企业列表 ───

function EnterpriseListTab() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<EnterpriseAccount[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [searchName, setSearchName] = useState('');

  // 新建/编辑 Modal
  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<EnterpriseAccount | null>(null);
  const [createForm] = Form.useForm();
  const [createLoading, setCreateLoading] = useState(false);

  // 调整额度 Modal
  const [creditOpen, setCreditOpen] = useState(false);
  const [creditTarget, setCreditTarget] = useState<EnterpriseAccount | null>(null);
  const [creditForm] = Form.useForm();
  const [creditLoading, setCreditLoading] = useState(false);

  // 签单记录抽屉
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerEnterprise, setDrawerEnterprise] = useState<EnterpriseAccount | null>(null);
  const [signRecords, setSignRecords] = useState<EnterpriseSignRecord[]>([]);
  const [signLoading, setSignLoading] = useState(false);

  const load = useCallback(async (pg = 1, name = '') => {
    setLoading(true);
    try {
      const res = await listEnterprises({ page: pg, size: 20, name: name || undefined });
      setData(res.items ?? []);
      setTotal(res.total ?? 0);
    } catch (e) {
      console.error('[EnterprisePage] list error', e);
      message.error('加载企业列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(1, '');
  }, [load]);

  const handleSearch = () => {
    setPage(1);
    void load(1, searchName);
  };

  const handleCreate = () => {
    setEditTarget(null);
    createForm.resetFields();
    setCreateOpen(true);
  };

  const handleEdit = (record: EnterpriseAccount) => {
    setEditTarget(record);
    createForm.setFieldsValue({
      name: record.name,
      contact: record.contact,
      credit_limit_yuan: record.credit_limit_fen / 100,
    });
    setCreateOpen(true);
  };

  const handleCreateSubmit = async () => {
    const values = await createForm.validateFields();
    setCreateLoading(true);
    try {
      if (editTarget) {
        await updateEnterprise(editTarget.id, {
          name: values.name,
          contact: values.contact,
          credit_limit_fen: yuanToFen(values.credit_limit_yuan),
        });
        message.success('企业信息更新成功');
      } else {
        await createEnterprise({
          name: values.name,
          contact: values.contact,
          credit_limit_fen: yuanToFen(values.credit_limit_yuan),
          billing_cycle: 'monthly',
        });
        message.success('企业创建成功');
      }
      setCreateOpen(false);
      void load(page, searchName);
    } catch (e) {
      console.error('[EnterprisePage] create/edit error', e);
      message.error(editTarget ? '更新失败，请重试' : '创建失败，请重试');
    } finally {
      setCreateLoading(false);
    }
  };

  const handleCreditLimit = (record: EnterpriseAccount) => {
    setCreditTarget(record);
    creditForm.setFieldsValue({ credit_limit_yuan: record.credit_limit_fen / 100 });
    setCreditOpen(true);
  };

  const handleCreditSubmit = async () => {
    if (!creditTarget) return;
    const values = await creditForm.validateFields();
    setCreditLoading(true);
    try {
      await updateEnterpriseCreditLimit(creditTarget.id, yuanToFen(values.credit_limit_yuan));
      message.success('额度调整成功');
      setCreditOpen(false);
      void load(page, searchName);
    } catch (e) {
      console.error('[EnterprisePage] credit limit error', e);
      message.error('额度调整失败，请重试');
    } finally {
      setCreditLoading(false);
    }
  };

  const handleDisable = (record: EnterpriseAccount) => {
    confirm({
      title: `确认停用「${record.name}」？`,
      icon: <ExclamationCircleOutlined />,
      content: '停用后该企业将无法继续挂账，已有签单记录不受影响。',
      okText: '确认停用',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await disableEnterprise(record.id);
          message.success('企业已停用');
          void load(page, searchName);
        } catch (e) {
          console.error('[EnterprisePage] disable error', e);
          message.error('停用失败，请重试');
        }
      },
    });
  };

  const handleOpenDrawer = async (record: EnterpriseAccount) => {
    setDrawerEnterprise(record);
    setDrawerOpen(true);
    setSignLoading(true);
    try {
      const month = dayjs().format('YYYY-MM');
      const statement = await getAuditTrail(record.id, month);
      setSignRecords(statement.sign_records ?? []);
    } catch {
      setSignRecords([]);
    } finally {
      setSignLoading(false);
    }
  };

  const columns: ColumnsType<EnterpriseAccount> = [
    {
      title: '企业名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record) => (
        <a onClick={() => handleOpenDrawer(record)}>{name}</a>
      ),
    },
    { title: '联系人', dataIndex: 'contact', key: 'contact', width: 100 },
    {
      title: '信用额度(元)',
      dataIndex: 'credit_limit_fen',
      key: 'credit_limit_fen',
      width: 130,
      render: (val: number) => `¥${fenToYuan(val)}`,
    },
    {
      title: '已用额度(元)',
      dataIndex: 'used_credit_fen',
      key: 'used_credit_fen',
      width: 130,
      render: (val: number) => (
        <Text style={{ color: val > 0 ? '#BA7517' : undefined }}>
          ¥{fenToYuan(val)}
        </Text>
      ),
    },
    {
      title: '剩余额度',
      key: 'remaining',
      width: 160,
      render: (_, record) => {
        const used = record.used_credit_fen;
        const limit = record.credit_limit_fen;
        const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
        const status = pct >= 90 ? 'exception' : pct >= 70 ? 'normal' : 'success';
        return (
          <div style={{ minWidth: 120 }}>
            <Progress
              percent={pct}
              status={status}
              size="small"
              format={() => `¥${fenToYuan(limit - used)}`}
            />
          </div>
        );
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 80,
      render: (s: string) => <StatusTag status={s} />,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 120,
      render: (v: string) => v?.slice(0, 10) ?? '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 180,
      render: (_, record) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => handleEdit(record)}>
            编辑
          </Button>
          <Button type="link" size="small" onClick={() => handleCreditLimit(record)}>
            调整额度
          </Button>
          {record.status === 'active' && (
            <Button type="link" size="small" danger onClick={() => handleDisable(record)}>
              停用
            </Button>
          )}
        </Space>
      ),
    },
  ];

  const signColumns: ColumnsType<EnterpriseSignRecord> = [
    { title: '日期', dataIndex: 'biz_date', width: 100 },
    { title: '签单人', dataIndex: 'signer_name', width: 90 },
    {
      title: '金额(元)',
      dataIndex: 'amount_fen',
      render: (v: number) => `¥${fenToYuan(v)}`,
      width: 100,
    },
    { title: '桌台', dataIndex: 'table_no', width: 80 },
    { title: '订单号', dataIndex: 'order_id', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (s: string) => <SignStatusTag status={s} />,
    },
  ];

  return (
    <>
      {/* 搜索工具栏 */}
      <Card style={{ marginBottom: 16 }} styles={{ body: { padding: '16px 24px' } }}>
        <Space size={12} wrap>
          <Input.Search
            placeholder="搜索企业名称"
            value={searchName}
            onChange={(e) => setSearchName(e.target.value)}
            onSearch={handleSearch}
            allowClear
            style={{ width: 260 }}
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={handleCreate}
            style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
          >
            新建企业
          </Button>
        </Space>
      </Card>

      {/* 企业列表 */}
      <Table<EnterpriseAccount>
        columns={columns}
        dataSource={data}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          total,
          pageSize: 20,
          showSizeChanger: false,
          onChange: (pg) => {
            setPage(pg);
            void load(pg, searchName);
          },
        }}
        size="middle"
      />

      {/* 新建/编辑 Modal */}
      <Modal
        title={editTarget ? '编辑企业信息' : '新建企业客户'}
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={handleCreateSubmit}
        confirmLoading={createLoading}
        okText={editTarget ? '保存' : '创建'}
        width={480}
      >
        <Form form={createForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="name"
            label="企业名称"
            rules={[{ required: true, message: '请输入企业名称' }]}
          >
            <Input placeholder="如：XX集团有限公司" />
          </Form.Item>
          <Form.Item
            name="contact"
            label="联系人"
            rules={[{ required: true, message: '请输入联系人' }]}
          >
            <Input placeholder="联系人姓名" />
          </Form.Item>
          <Form.Item
            name="credit_limit_yuan"
            label="信用额度(元)"
            rules={[{ required: true, message: '请输入信用额度' }]}
          >
            <InputNumber
              min={0.01}
              precision={2}
              prefix="¥"
              placeholder="如：10000.00"
              style={{ width: '100%' }}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 调整额度 Modal */}
      <Modal
        title={`调整额度 — ${creditTarget?.name ?? ''}`}
        open={creditOpen}
        onCancel={() => setCreditOpen(false)}
        onOk={handleCreditSubmit}
        confirmLoading={creditLoading}
        okText="确认调整"
        width={420}
      >
        {creditTarget && (
          <div style={{ marginBottom: 16 }}>
            <Descriptions column={2} size="small">
              <Descriptions.Item label="当前额度">
                ¥{fenToYuan(creditTarget.credit_limit_fen)}
              </Descriptions.Item>
              <Descriptions.Item label="已用额度">
                ¥{fenToYuan(creditTarget.used_credit_fen)}
              </Descriptions.Item>
            </Descriptions>
          </div>
        )}
        <Form form={creditForm} layout="vertical">
          <Form.Item
            name="credit_limit_yuan"
            label="新信用额度(元)"
            rules={[{ required: true, message: '请输入新额度' }]}
          >
            <InputNumber
              min={0.01}
              precision={2}
              prefix="¥"
              style={{ width: '100%' }}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 签单记录 Drawer */}
      <Drawer
        title={`签单记录 — ${drawerEnterprise?.name ?? ''}`}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={680}
      >
        {drawerEnterprise && (
          <>
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={8}>
                <Statistic
                  title="信用额度"
                  value={fenToYuan(drawerEnterprise.credit_limit_fen)}
                  prefix="¥"
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="已用额度"
                  value={fenToYuan(drawerEnterprise.used_credit_fen)}
                  prefix="¥"
                  valueStyle={{ color: drawerEnterprise.used_credit_fen > 0 ? '#BA7517' : undefined }}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="剩余额度"
                  value={fenToYuan(drawerEnterprise.credit_limit_fen - drawerEnterprise.used_credit_fen)}
                  prefix="¥"
                  valueStyle={{ color: '#0F6E56' }}
                />
              </Col>
            </Row>
            <Divider style={{ margin: '12px 0' }} />
            <Spin spinning={signLoading}>
              <Table<EnterpriseSignRecord>
                columns={signColumns}
                dataSource={signRecords}
                rowKey="id"
                pagination={{ pageSize: 10, showSizeChanger: false }}
                size="small"
                locale={{ emptyText: '本月暂无签单记录' }}
              />
            </Spin>
          </>
        )}
      </Drawer>
    </>
  );
}

// ─── Tab2：签单记录 ───

function SignRecordsTab() {
  const [loading, setLoading] = useState(false);
  const [records, setRecords] = useState<EnterpriseSignRecord[]>([]);
  const [enterprises, setEnterprises] = useState<Array<{ value: string; label: string }>>([]);
  const [filterEnterpriseId, setFilterEnterpriseId] = useState<string | undefined>();
  const [filterStatus, setFilterStatus] = useState<string | undefined>();
  const [filterMonth, setFilterMonth] = useState<string>(dayjs().format('YYYY-MM'));

  useEffect(() => {
    listEnterprises({ size: 100 })
      .then((res) =>
        setEnterprises(
          (res.items ?? []).map((e) => ({ value: e.id, label: e.name })),
        ),
      )
      .catch(() => setEnterprises([]));
  }, []);

  const load = useCallback(async () => {
    if (!filterEnterpriseId) {
      setRecords([]);
      return;
    }
    setLoading(true);
    try {
      const statement = await getAuditTrail(filterEnterpriseId, filterMonth);
      let items = statement.sign_records ?? [];
      if (filterStatus) {
        items = items.filter((r) => r.status === filterStatus);
      }
      setRecords(items);
    } catch {
      setRecords([]);
    } finally {
      setLoading(false);
    }
  }, [filterEnterpriseId, filterMonth, filterStatus]);

  useEffect(() => {
    void load();
  }, [load]);

  // 按企业汇总
  const totalUnpaidFen = records
    .filter((r) => r.status === 'unpaid')
    .reduce((sum, r) => sum + r.amount_fen, 0);

  const totalFen = records.reduce((sum, r) => sum + r.amount_fen, 0);

  const columns: ColumnsType<EnterpriseSignRecord> = [
    { title: '日期', dataIndex: 'biz_date', key: 'biz_date', width: 100 },
    {
      title: '企业',
      dataIndex: 'enterprise_name',
      key: 'enterprise_name',
      width: 160,
    },
    { title: '签单人', dataIndex: 'signer_name', key: 'signer_name', width: 90 },
    {
      title: '金额(元)',
      dataIndex: 'amount_fen',
      key: 'amount_fen',
      width: 110,
      render: (v: number) => `¥${fenToYuan(v)}`,
    },
    { title: '桌台', dataIndex: 'table_no', key: 'table_no', width: 80 },
    { title: '订单号', dataIndex: 'order_id', key: 'order_id', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (s: string) => <SignStatusTag status={s} />,
    },
    { title: '备注', dataIndex: 'notes', key: 'notes', ellipsis: true },
  ];

  return (
    <>
      {/* 筛选区 */}
      <Card style={{ marginBottom: 16 }} styles={{ body: { padding: '16px 24px' } }}>
        <Space size={12} wrap>
          <Select
            placeholder="选择企业"
            options={enterprises}
            value={filterEnterpriseId}
            onChange={setFilterEnterpriseId}
            allowClear
            showSearch
            filterOption={(input, opt) =>
              (opt?.label ?? '').toLowerCase().includes(input.toLowerCase())
            }
            style={{ width: 220 }}
          />
          <DatePicker.MonthPicker
            value={dayjs(filterMonth, 'YYYY-MM')}
            onChange={(_, m) => setFilterMonth(Array.isArray(m) ? m[0] : (m || dayjs().format('YYYY-MM')))}
            style={{ width: 140 }}
            allowClear={false}
          />
          <Select
            placeholder="签单状态"
            value={filterStatus}
            onChange={setFilterStatus}
            allowClear
            style={{ width: 130 }}
            options={[
              { value: 'unpaid', label: '未还款' },
              { value: 'paid', label: '已还款' },
            ]}
          />
        </Space>
      </Card>

      {/* 汇总 */}
      {records.length > 0 && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card styles={{ body: { padding: '16px 20px' } }}>
              <Statistic title="本期签单总额" value={fenToYuan(totalFen)} prefix="¥" />
            </Card>
          </Col>
          <Col span={6}>
            <Card styles={{ body: { padding: '16px 20px' } }}>
              <Statistic
                title="未还款金额"
                value={fenToYuan(totalUnpaidFen)}
                prefix="¥"
                valueStyle={{ color: totalUnpaidFen > 0 ? '#A32D2D' : '#0F6E56' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card styles={{ body: { padding: '16px 20px' } }}>
              <Statistic title="签单笔数" value={records.length} suffix="笔" />
            </Card>
          </Col>
        </Row>
      )}

      <Table<EnterpriseSignRecord>
        columns={columns}
        dataSource={records}
        rowKey="id"
        loading={loading}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        size="middle"
        locale={{ emptyText: filterEnterpriseId ? '暂无签单记录' : '请先选择企业' }}
      />
    </>
  );
}

// ─── Tab3：月结对账 ───

function MonthlyBillingTab() {
  const [enterprises, setEnterprises] = useState<Array<{ value: string; label: string }>>([]);
  const [selectedId, setSelectedId] = useState<string | undefined>();
  const [selectedMonth, setSelectedMonth] = useState<string>(dayjs().format('YYYY-MM'));
  const [statement, setStatement] = useState<EnterpriseStatement | null>(null);
  const [loadingStatement, setLoadingStatement] = useState(false);
  const [settlementLoading, setSettlementLoading] = useState(false);

  useEffect(() => {
    listEnterprises({ size: 100 })
      .then((res) =>
        setEnterprises(
          (res.items ?? []).map((e) => ({ value: e.id, label: e.name })),
        ),
      )
      .catch(() => setEnterprises([]));
  }, []);

  const handleLoadStatement = async () => {
    if (!selectedId) {
      message.warning('请选择企业');
      return;
    }
    setLoadingStatement(true);
    try {
      const res = await getAuditTrail(selectedId, selectedMonth);
      setStatement(res);
    } catch {
      message.error('加载对账明细失败');
    } finally {
      setLoadingStatement(false);
    }
  };

  const handleSettle = () => {
    if (!selectedId || !statement) return;
    confirm({
      title: `确认月结 — ${statement.enterprise_name} ${selectedMonth}？`,
      icon: <ExclamationCircleOutlined />,
      content: (
        <div>
          <p>本月签单合计：<Text strong>¥{fenToYuan(statement.total_fen)}</Text></p>
          <p>确认后将生成正式月结账单，并标记本月签单为「已结算」。</p>
        </div>
      ),
      okText: '确认月结',
      cancelText: '取消',
      onOk: async () => {
        setSettlementLoading(true);
        try {
          await monthlySettlement(selectedId, selectedMonth);
          message.success(`${selectedMonth} 月结完成`);
          void handleLoadStatement();
        } catch {
          message.error('月结操作失败，请重试');
        } finally {
          setSettlementLoading(false);
        }
      },
    });
  };

  const signColumns: ColumnsType<EnterpriseSignRecord> = [
    { title: '日期', dataIndex: 'biz_date', width: 100 },
    { title: '签单人', dataIndex: 'signer_name', width: 90 },
    {
      title: '金额(元)',
      dataIndex: 'amount_fen',
      render: (v: number) => `¥${fenToYuan(v)}`,
      width: 110,
    },
    { title: '桌台', dataIndex: 'table_no', width: 80 },
    { title: '订单号', dataIndex: 'order_id', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (s: string) => <SignStatusTag status={s} />,
    },
  ];

  return (
    <>
      {/* 筛选 */}
      <Card style={{ marginBottom: 24 }} styles={{ body: { padding: '16px 24px' } }}>
        <Space size={12} wrap>
          <Select
            placeholder="选择企业"
            options={enterprises}
            value={selectedId}
            onChange={(v) => { setSelectedId(v); setStatement(null); }}
            allowClear
            showSearch
            filterOption={(input, opt) =>
              (opt?.label ?? '').toLowerCase().includes(input.toLowerCase())
            }
            style={{ width: 240 }}
          />
          <DatePicker.MonthPicker
            value={dayjs(selectedMonth, 'YYYY-MM')}
            onChange={(_, m) => {
              setSelectedMonth(Array.isArray(m) ? m[0] : (m || dayjs().format('YYYY-MM')));
              setStatement(null);
            }}
            style={{ width: 140 }}
            allowClear={false}
          />
          <Button
            type="primary"
            onClick={handleLoadStatement}
            loading={loadingStatement}
            style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
          >
            查询明细
          </Button>
        </Space>
      </Card>

      {/* 对账明细 */}
      {statement && (
        <Card
          title={
            <Space>
              <span>月结对账明细</span>
              <Text type="secondary" style={{ fontSize: 13 }}>
                {statement.enterprise_name} · {selectedMonth}
              </Text>
            </Space>
          }
          extra={
            <Button
              type="primary"
              danger
              loading={settlementLoading}
              onClick={handleSettle}
              disabled={!statement.sign_records?.length}
            >
              确认月结
            </Button>
          }
        >
          {/* 汇总数字 */}
          <Row gutter={24} style={{ marginBottom: 24 }}>
            <Col span={6}>
              <Statistic
                title="本月签单总额"
                value={fenToYuan(statement.total_fen)}
                prefix="¥"
                valueStyle={{ color: '#FF6B35' }}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="签单笔数"
                value={statement.sign_records?.length ?? 0}
                suffix="笔"
              />
            </Col>
            {statement.bill && (
              <>
                <Col span={6}>
                  <Statistic
                    title="已还款"
                    value={fenToYuan(statement.bill.paid_fen)}
                    prefix="¥"
                    valueStyle={{ color: '#0F6E56' }}
                  />
                </Col>
                <Col span={6}>
                  <Statistic
                    title="账单状态"
                    value={
                      statement.bill.status === 'settled'
                        ? '已结清'
                        : statement.bill.status === 'partial'
                        ? '部分还款'
                        : '待还款'
                    }
                    valueStyle={{
                      color:
                        statement.bill.status === 'settled'
                          ? '#0F6E56'
                          : '#BA7517',
                      fontSize: 20,
                    }}
                  />
                </Col>
              </>
            )}
          </Row>

          <Divider style={{ margin: '0 0 16px' }} />

          {/* 签单明细表 */}
          <Table<EnterpriseSignRecord>
            columns={signColumns}
            dataSource={statement.sign_records ?? []}
            rowKey="id"
            pagination={{ pageSize: 20, showSizeChanger: false }}
            size="small"
            locale={{ emptyText: '本月暂无签单记录' }}
            summary={(rows) => {
              const total = rows.reduce((s, r) => s + r.amount_fen, 0);
              return total > 0 ? (
                <Table.Summary.Row>
                  <Table.Summary.Cell index={0} colSpan={2}>
                    <Text strong>合计</Text>
                  </Table.Summary.Cell>
                  <Table.Summary.Cell index={2}>
                    <Text strong style={{ color: '#FF6B35' }}>
                      ¥{fenToYuan(total)}
                    </Text>
                  </Table.Summary.Cell>
                  <Table.Summary.Cell index={3} colSpan={3} />
                </Table.Summary.Row>
              ) : null;
            }}
          />
        </Card>
      )}
    </>
  );
}

// ─── 主页面 ───

export function EnterprisePage() {
  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      {/* 页面标题 */}
      <div style={{ marginBottom: 24 }}>
        <Title level={2} style={{ margin: 0, color: '#2C2C2A' }}>
          企业挂账管理
        </Title>
        <Text style={{ color: '#5F5E5A', fontSize: 14 }}>
          管理协议企业客户信用额度、签单授权及月结对账
        </Text>
      </div>

      <Tabs
        defaultActiveKey="list"
        items={[
          {
            key: 'list',
            label: '企业列表',
            children: <EnterpriseListTab />,
          },
          {
            key: 'records',
            label: '签单记录',
            children: <SignRecordsTab />,
          },
          {
            key: 'billing',
            label: '月结对账',
            children: <MonthlyBillingTab />,
          },
        ]}
      />
    </div>
  );
}
