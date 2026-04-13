/**
 * TaxFilingPage -- 薪税申报管理
 * 域F . 组织人事 . 薪税申报
 *
 * 功能：
 *  - 顶部统计：本年已申报月数 / 总个税额 / 总申报人次
 *  - Tab1「申报操作」：选择月份+门店 -> 生成预览 -> 提交申报
 *  - Tab2「申报记录」：ProTable 历史列表
 *  - Tab3「年度汇总」：选择员工 -> 12个月累计 + 年度合计
 *
 * API: /api/v1/tax-filing/*
 */

import { useRef, useState, useCallback, useEffect } from 'react';
import {
  Card,
  Col,
  Row,
  Statistic,
  Typography,
  Tabs,
  Tag,
  Button,
  DatePicker,
  Select,
  Space,
  Modal,
  message,
  Steps,
  Descriptions,
  Empty,
  Spin,
} from 'antd';
import {
  AccountBookOutlined,
  CalendarOutlined,
  TeamOutlined,
  SendOutlined,
  ReloadOutlined,
  EyeOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  SyncOutlined,
  FileTextOutlined,
} from '@ant-design/icons';
import { ProColumns, ProTable } from '@ant-design/pro-components';
import type { ActionType } from '@ant-design/pro-components';
import { txFetchData } from '../../../api';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const TX_PRIMARY = '#FF6B35';

// ---- Types ----------------------------------------------------------------

interface FilingStats {
  year: number;
  filed_months: number;
  total_tax_fen: number;
  total_headcount: number;
}

interface FilingEmployee {
  employee_id: string;
  emp_name: string;
  id_card_no_masked: string;
  taxable_income_fen: number;
  tax_fen: number;
  cumulative_income_fen: number;
  cumulative_tax_fen: number;
}

interface GenerateResult {
  declaration_id: string;
  month: string;
  store_name: string;
  employee_count: number;
  total_tax_fen: number;
  employees: FilingEmployee[];
  status: string;
}

interface FilingRecord {
  declaration_id: string;
  month: string;
  store_name: string;
  employee_count: number;
  total_tax_fen: number;
  status: string;
  submitted_at: string | null;
}

interface AnnualMonth {
  month: string;
  taxable_fen: number;
  tax_fen: number;
}

interface AnnualSummary {
  year: number;
  employee_id: string;
  emp_name: string;
  months: AnnualMonth[];
  total_taxable_fen: number;
  total_tax_fen: number;
  avg_monthly_tax_fen: number;
}

// ---- Helpers --------------------------------------------------------------

const fenToYuan = (fen: number) => `\u00a5${(fen / 100).toFixed(2)}`;

const statusMap: Record<string, { color: string; label: string }> = {
  draft: { color: 'default', label: '\u8349\u7a3f' },
  generated: { color: 'processing', label: '\u5df2\u751f\u6210' },
  submitted: { color: 'success', label: '\u5df2\u63d0\u4ea4' },
  accepted: { color: 'success', label: '\u5df2\u53d7\u7406' },
  rejected: { color: 'error', label: '\u88ab\u9000\u56de' },
  completed: { color: 'success', label: '\u7533\u62a5\u5b8c\u6210' },
};

// ---- Component ------------------------------------------------------------

export default function TaxFilingPage() {
  const [activeTab, setActiveTab] = useState('operate');
  const [stats, setStats] = useState<FilingStats>({
    year: dayjs().year(),
    filed_months: 0,
    total_tax_fen: 0,
    total_headcount: 0,
  });
  const historyRef = useRef<ActionType>(null);

  // Load stats
  const loadStats = useCallback(async () => {
    try {
      const data = await txFetchData<FilingStats>('/api/v1/tax-filing/stats');
      setStats(data);
    } catch {
      // stats are best-effort
    }
  }, []);

  useEffect(() => {
    loadStats();
  }, [loadStats]);

  return (
    <div style={{ padding: 24 }}>
      <Title level={3}>
        <AccountBookOutlined style={{ color: TX_PRIMARY, marginRight: 8 }} />
        薪税申报管理
      </Title>

      {/* Stats Cards */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={8}>
          <Card>
            <Statistic
              title="本年已申报月数"
              value={stats.filed_months}
              suffix="/ 12 月"
              prefix={<CalendarOutlined style={{ color: TX_PRIMARY }} />}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="总个税额"
              value={(stats.total_tax_fen / 100).toFixed(2)}
              prefix={<AccountBookOutlined style={{ color: '#52c41a' }} />}
              suffix="元"
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="总申报人次"
              value={stats.total_headcount}
              prefix={<TeamOutlined style={{ color: '#1890ff' }} />}
              suffix="人次"
            />
          </Card>
        </Col>
      </Row>

      {/* Tabs */}
      <Card>
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
          {
            key: 'operate',
            label: '申报操作',
            children: <FilingOperateTab onSuccess={loadStats} />,
          },
          {
            key: 'history',
            label: '申报记录',
            children: <FilingHistoryTab actionRef={historyRef} />,
          },
          {
            key: 'annual',
            label: '年度汇总',
            children: <AnnualSummaryTab />,
          },
        ]} />
      </Card>
    </div>
  );
}

// ---- Tab 1: Filing Operate ------------------------------------------------

function FilingOperateTab({ onSuccess }: { onSuccess: () => void }) {
  const [month, setMonth] = useState<string>(dayjs().format('YYYY-MM'));
  const [storeId, setStoreId] = useState<string>('');
  const [stores, setStores] = useState<{ value: string; label: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [preview, setPreview] = useState<GenerateResult | null>(null);
  const [step, setStep] = useState(0);

  // Load stores
  useEffect(() => {
    (async () => {
      try {
        const data = await txFetchData<{ items: { id: string; store_name: string }[]; total: number }>(
          '/api/v1/org/stores?page=1&size=100'
        );
        setStores(
          (data.items || []).map((s) => ({ value: s.id, label: s.store_name }))
        );
      } catch {
        // fallback: no stores
      }
    })();
  }, []);

  const handleGenerate = async () => {
    if (!storeId) {
      message.warning('请选择门店');
      return;
    }
    setLoading(true);
    try {
      const data = await txFetchData<GenerateResult>('/api/v1/tax-filing/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ month, store_id: storeId }),
      });
      setPreview(data);
      setStep(1);
      message.success(`已生成 ${data.employee_count} 人申报数据`);
    } catch (err: any) {
      message.error(err?.message || '生成失败');
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async () => {
    if (!preview?.declaration_id) return;
    setSubmitting(true);
    try {
      await txFetchData('/api/v1/tax-filing/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ declaration_id: preview.declaration_id }),
      });
      setStep(2);
      message.success('申报提交成功');
      onSuccess();
    } catch (err: any) {
      message.error(err?.message || '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleReset = () => {
    setPreview(null);
    setStep(0);
  };

  const previewColumns: ProColumns<FilingEmployee>[] = [
    { title: '姓名', dataIndex: 'emp_name', width: 100 },
    { title: '身份证（脱敏）', dataIndex: 'id_card_no_masked', width: 180 },
    {
      title: '应发工资',
      dataIndex: 'taxable_income_fen',
      width: 120,
      render: (_, r) => fenToYuan(r.taxable_income_fen),
      align: 'right',
    },
    {
      title: '当月应纳税',
      dataIndex: 'tax_fen',
      width: 120,
      render: (_, r) => <Text type="danger">{fenToYuan(r.tax_fen)}</Text>,
      align: 'right',
    },
    {
      title: '累计收入',
      dataIndex: 'cumulative_income_fen',
      width: 120,
      render: (_, r) => fenToYuan(r.cumulative_income_fen),
      align: 'right',
    },
    {
      title: '累计已缴税',
      dataIndex: 'cumulative_tax_fen',
      width: 120,
      render: (_, r) => fenToYuan(r.cumulative_tax_fen),
      align: 'right',
    },
  ];

  return (
    <div>
      {/* Steps */}
      <Steps
        current={step}
        style={{ marginBottom: 24 }}
        items={[
          { title: '选择月份门店', icon: <CalendarOutlined /> },
          { title: '预览确认', icon: <EyeOutlined /> },
          { title: '提交完成', icon: <CheckCircleOutlined /> },
        ]}
      />

      {step === 0 && (
        <Card>
          <Space size="large">
            <div>
              <Text strong style={{ marginRight: 8 }}>申报月份：</Text>
              <DatePicker
                picker="month"
                value={dayjs(month, 'YYYY-MM')}
                onChange={(d) => d && setMonth(d.format('YYYY-MM'))}
                allowClear={false}
              />
            </div>
            <div>
              <Text strong style={{ marginRight: 8 }}>门店：</Text>
              <Select
                style={{ width: 240 }}
                placeholder="选择门店"
                value={storeId || undefined}
                onChange={setStoreId}
                options={stores}
                showSearch
                filterOption={(input, opt) =>
                  (opt?.label ?? '').toLowerCase().includes(input.toLowerCase())
                }
              />
            </div>
            <Button
              type="primary"
              icon={<FileTextOutlined />}
              loading={loading}
              onClick={handleGenerate}
              style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
            >
              生成预览
            </Button>
          </Space>
        </Card>
      )}

      {step === 1 && preview && (
        <div>
          <Card style={{ marginBottom: 16 }}>
            <Descriptions column={4} bordered size="small">
              <Descriptions.Item label="月份">{preview.month}</Descriptions.Item>
              <Descriptions.Item label="门店">{preview.store_name}</Descriptions.Item>
              <Descriptions.Item label="人数">{preview.employee_count}</Descriptions.Item>
              <Descriptions.Item label="总个税">
                <Text type="danger" strong>{fenToYuan(preview.total_tax_fen)}</Text>
              </Descriptions.Item>
            </Descriptions>
          </Card>

          <ProTable<FilingEmployee>
            columns={previewColumns}
            dataSource={preview.employees}
            rowKey="employee_id"
            search={false}
            toolBarRender={false}
            pagination={{ pageSize: 10 }}
            size="small"
          />

          <div style={{ marginTop: 16, textAlign: 'center' }}>
            <Space>
              <Button onClick={handleReset}>返回修改</Button>
              <Button
                type="primary"
                icon={<SendOutlined />}
                loading={submitting}
                onClick={handleSubmit}
                style={{ background: TX_PRIMARY, borderColor: TX_PRIMARY }}
              >
                确认提交申报
              </Button>
            </Space>
          </div>
        </div>
      )}

      {step === 2 && (
        <Card style={{ textAlign: 'center', padding: 40 }}>
          <CheckCircleOutlined style={{ fontSize: 48, color: '#52c41a' }} />
          <Title level={4} style={{ marginTop: 16 }}>申报提交成功</Title>
          <Text type="secondary">
            {preview?.month} 月份 {preview?.employee_count} 人个税申报已提交至税务局
          </Text>
          <div style={{ marginTop: 24 }}>
            <Button type="primary" onClick={handleReset}>继续申报</Button>
          </div>
        </Card>
      )}
    </div>
  );
}

// ---- Tab 2: Filing History ------------------------------------------------

function FilingHistoryTab({ actionRef }: { actionRef: React.RefObject<ActionType | undefined> }) {
  const columns: ProColumns<FilingRecord>[] = [
    { title: '月份', dataIndex: 'month', width: 100 },
    { title: '门店', dataIndex: 'store_name', width: 160 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (_, r) => {
        const s = statusMap[r.status] || { color: 'default', label: r.status };
        return <Tag color={s.color}>{s.label}</Tag>;
      },
    },
    {
      title: '人数',
      dataIndex: 'employee_count',
      width: 80,
      align: 'right',
    },
    {
      title: '总个税',
      dataIndex: 'total_tax_fen',
      width: 120,
      render: (_, r) => fenToYuan(r.total_tax_fen),
      align: 'right',
    },
    {
      title: '提交时间',
      dataIndex: 'submitted_at',
      width: 180,
      render: (_, r) => r.submitted_at ? dayjs(r.submitted_at).format('YYYY-MM-DD HH:mm') : '-',
    },
    {
      title: '操作',
      width: 120,
      render: (_, r) => (
        <Space>
          {r.status === 'rejected' && (
            <Button
              size="small"
              icon={<ReloadOutlined />}
              onClick={() => handleRetry(r.declaration_id)}
            >
              重试
            </Button>
          )}
        </Space>
      ),
    },
  ];

  const handleRetry = async (id: string) => {
    try {
      await txFetchData(`/api/v1/tax-filing/${id}/retry`, { method: 'POST' });
      message.success('重试已提交');
      actionRef.current?.reload();
    } catch (err: any) {
      message.error(err?.message || '重试失败');
    }
  };

  return (
    <ProTable<FilingRecord>
      actionRef={actionRef}
      columns={columns}
      rowKey="declaration_id"
      search={false}
      request={async () => {
        try {
          const data = await txFetchData<{ items: FilingRecord[]; total: number }>(
            '/api/v1/tax-filing/history'
          );
          return { data: data.items || [], total: data.total || 0, success: true };
        } catch {
          return { data: [], total: 0, success: true };
        }
      }}
      pagination={{ pageSize: 10 }}
    />
  );
}

// ---- Tab 3: Annual Summary ------------------------------------------------

function AnnualSummaryTab() {
  const [employeeId, setEmployeeId] = useState('');
  const [year, setYear] = useState(dayjs().year());
  const [loading, setLoading] = useState(false);
  const [summary, setSummary] = useState<AnnualSummary | null>(null);
  const [employees, setEmployees] = useState<{ value: string; label: string }[]>([]);

  // Load employees
  useEffect(() => {
    (async () => {
      try {
        const data = await txFetchData<{ items: { id: string; emp_name: string }[]; total: number }>(
          '/api/v1/employees?page=1&size=200'
        );
        setEmployees(
          (data.items || []).map((e) => ({ value: e.id, label: e.emp_name }))
        );
      } catch {
        // fallback
      }
    })();
  }, []);

  const handleQuery = async () => {
    if (!employeeId) {
      message.warning('请选择员工');
      return;
    }
    setLoading(true);
    try {
      const data = await txFetchData<AnnualSummary>(
        `/api/v1/tax-filing/annual-summary/${employeeId}?year=${year}`
      );
      setSummary(data);
    } catch (err: any) {
      message.error(err?.message || '查询失败');
    } finally {
      setLoading(false);
    }
  };

  const monthColumns: ProColumns<AnnualMonth>[] = [
    { title: '月份', dataIndex: 'month', width: 100 },
    {
      title: '应税收入',
      dataIndex: 'taxable_fen',
      width: 140,
      render: (_, r) => fenToYuan(r.taxable_fen),
      align: 'right',
    },
    {
      title: '应纳个税',
      dataIndex: 'tax_fen',
      width: 140,
      render: (_, r) => (
        <Text type={r.tax_fen > 0 ? 'danger' : undefined}>
          {fenToYuan(r.tax_fen)}
        </Text>
      ),
      align: 'right',
    },
  ];

  return (
    <div>
      <Card style={{ marginBottom: 16 }}>
        <Space size="large">
          <div>
            <Text strong style={{ marginRight: 8 }}>员工：</Text>
            <Select
              style={{ width: 200 }}
              placeholder="选择员工"
              value={employeeId || undefined}
              onChange={setEmployeeId}
              options={employees}
              showSearch
              filterOption={(input, opt) =>
                (opt?.label ?? '').toLowerCase().includes(input.toLowerCase())
              }
            />
          </div>
          <div>
            <Text strong style={{ marginRight: 8 }}>年度：</Text>
            <DatePicker
              picker="year"
              value={dayjs().year(year)}
              onChange={(d) => d && setYear(d.year())}
              allowClear={false}
            />
          </div>
          <Button type="primary" onClick={handleQuery} loading={loading}>
            查询
          </Button>
        </Space>
      </Card>

      {loading && <Spin style={{ display: 'block', margin: '40px auto' }} />}

      {!loading && !summary && (
        <Empty description="请选择员工和年度后查询" />
      )}

      {!loading && summary && (
        <>
          <Card style={{ marginBottom: 16 }}>
            <Descriptions column={4} bordered size="small">
              <Descriptions.Item label="员工">{summary.emp_name}</Descriptions.Item>
              <Descriptions.Item label="年度">{summary.year}</Descriptions.Item>
              <Descriptions.Item label="累计应税">
                {fenToYuan(summary.total_taxable_fen)}
              </Descriptions.Item>
              <Descriptions.Item label="累计个税">
                <Text type="danger" strong>{fenToYuan(summary.total_tax_fen)}</Text>
              </Descriptions.Item>
            </Descriptions>
          </Card>

          <ProTable<AnnualMonth>
            columns={monthColumns}
            dataSource={summary.months}
            rowKey="month"
            search={false}
            toolBarRender={false}
            pagination={false}
            size="small"
            summary={() => (
              <ProTable.Summary fixed>
                <ProTable.Summary.Row>
                  <ProTable.Summary.Cell index={0}>
                    <Text strong>年度合计</Text>
                  </ProTable.Summary.Cell>
                  <ProTable.Summary.Cell index={1} align="right">
                    <Text strong>{fenToYuan(summary.total_taxable_fen)}</Text>
                  </ProTable.Summary.Cell>
                  <ProTable.Summary.Cell index={2} align="right">
                    <Text strong type="danger">{fenToYuan(summary.total_tax_fen)}</Text>
                  </ProTable.Summary.Cell>
                </ProTable.Summary.Row>
                <ProTable.Summary.Row>
                  <ProTable.Summary.Cell index={0}>
                    <Text type="secondary">月均</Text>
                  </ProTable.Summary.Cell>
                  <ProTable.Summary.Cell index={1} align="right">
                    <Text type="secondary">-</Text>
                  </ProTable.Summary.Cell>
                  <ProTable.Summary.Cell index={2} align="right">
                    <Text type="secondary">{fenToYuan(summary.avg_monthly_tax_fen)}</Text>
                  </ProTable.Summary.Cell>
                </ProTable.Summary.Row>
              </ProTable.Summary>
            )}
          />
        </>
      )}
    </div>
  );
}
