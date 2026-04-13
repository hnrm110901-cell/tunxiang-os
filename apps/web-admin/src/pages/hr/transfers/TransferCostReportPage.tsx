/**
 * TransferCostReportPage — 借调成本分摊报表
 * 域F · 组织人事 · 成本分摊
 *
 * 功能：
 *  1. 筛选条件：门店选择 + 月份选择
 *  2. 三个Tab：明细分摊表 / 薪资汇总表 / 成本分析表
 *  3. 明细表：ProTable展示每个借调员工各店工时和成本
 *  4. 汇总表：按门店汇总
 *  5. 分析表：实际vs预算、环比变化
 *
 * API:
 *  GET /api/v1/transfers/cost-report?store_id=xxx&month=2026-04
 */

import { useEffect, useState } from 'react';
import {
  Card,
  Col,
  DatePicker,
  message,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { DollarOutlined } from '@ant-design/icons';
import dayjs from 'dayjs';
import { txFetchData } from '../../../api';
import type {
  CostReportResult,
  DetailReport,
  StoreAnalysis,
  StoreSummary,
} from '../../../api/transferApi';
import { fetchCostReport } from '../../../api/transferApi';

const { Title, Text } = Typography;
const TX_PRIMARY = '#FF6B35';

/** 分转元 */
const fen2yuan = (fen: number): string => (fen / 100).toFixed(2);

// ─── 主组件 ──────────────────────────────────────────────

export default function TransferCostReportPage() {
  const [storeId, setStoreId] = useState<string>('');
  const [month, setMonth] = useState<string>(dayjs().format('YYYY-MM'));
  const [stores, setStores] = useState<{ store_id: string; store_name: string }[]>([]);
  const [report, setReport] = useState<CostReportResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('detail');

  useEffect(() => {
    (async () => {
      try {
        const res = await txFetchData<{ store_id: string; store_name: string }[]>('/api/v1/org/stores');
        const list = res ?? [];
        setStores(list);
        if (list.length > 0) setStoreId(list[0].store_id);
      } catch {
        message.error('加载门店列表失败');
      }
    })();
  }, []);

  useEffect(() => {
    if (storeId && month) {
      loadReport();
    }
  }, [storeId, month]);

  const loadReport = async () => {
    if (!storeId || !month) return;
    setLoading(true);
    try {
      const data = await fetchCostReport(storeId, month);
      setReport(data);
    } catch {
      message.error('加载报表失败');
      setReport(null);
    } finally {
      setLoading(false);
    }
  };

  // ── 明细表 ────────────────────────────────────────────

  const detailColumns: ColumnsType<DetailReport & { key: string }> = [
    { title: '员工', dataIndex: 'employee_name', width: 100 },
    {
      title: '总工时(h)',
      dataIndex: 'total_hours',
      width: 100,
      render: (v: number) => v.toFixed(1),
    },
    {
      title: '总成本(元)',
      dataIndex: 'total_cost_fen',
      width: 120,
      render: (v: number) => fen2yuan(v),
    },
    {
      title: '门店明细',
      key: 'store_detail',
      render: (_, record) => (
        <Space direction="vertical" size={0}>
          {record.stores.map((s) => (
            <Text key={s.store_id} style={{ fontSize: 12 }}>
              {s.store_id.slice(0, 8)}...：
              {s.hours.toFixed(1)}h / {(s.ratio * 100).toFixed(1)}% /
              {fen2yuan(s.total_fen)}元
            </Text>
          ))}
        </Space>
      ),
    },
  ];

  // ── 汇总表 ────────────────────────────────────────────

  interface SummaryRow {
    key: string;
    store_id: string;
    employee_count: number;
    total_wage_fen: number;
    total_social_fen: number;
    total_bonus_fen: number;
    grand_total_fen: number;
  }

  const summaryColumns: ColumnsType<SummaryRow> = [
    { title: '门店', dataIndex: 'store_id', width: 160, ellipsis: true },
    { title: '人数', dataIndex: 'employee_count', width: 80 },
    { title: '工资(元)', dataIndex: 'total_wage_fen', width: 120, render: (v: number) => fen2yuan(v) },
    { title: '社保(元)', dataIndex: 'total_social_fen', width: 120, render: (v: number) => fen2yuan(v) },
    { title: '奖金(元)', dataIndex: 'total_bonus_fen', width: 120, render: (v: number) => fen2yuan(v) },
    {
      title: '合计(元)',
      dataIndex: 'grand_total_fen',
      width: 120,
      render: (v: number) => <Text strong>{fen2yuan(v)}</Text>,
    },
  ];

  const summaryData: SummaryRow[] = report?.summary?.stores
    ? Object.entries(report.summary.stores).map(([sid, s]) => ({
        key: sid,
        store_id: sid,
        ...(s as StoreSummary),
      }))
    : [];

  // ── 分析表 ────────────────────────────────────────────

  interface AnalysisRow {
    key: string;
    store_id: string;
    actual_fen: number;
    budget_fen: number;
    variance_fen: number;
    variance_rate: number;
    last_period_fen: number;
    mom_change_fen: number;
    mom_rate: number;
  }

  const analysisColumns: ColumnsType<AnalysisRow> = [
    { title: '门店', dataIndex: 'store_id', width: 160, ellipsis: true },
    { title: '实际(元)', dataIndex: 'actual_fen', width: 110, render: (v: number) => fen2yuan(v) },
    { title: '预算(元)', dataIndex: 'budget_fen', width: 110, render: (v: number) => fen2yuan(v) },
    {
      title: '偏差(元)',
      dataIndex: 'variance_fen',
      width: 110,
      render: (v: number) => (
        <Text style={{ color: v > 0 ? '#ff4d4f' : '#52c41a' }}>
          {v > 0 ? '+' : ''}{fen2yuan(v)}
        </Text>
      ),
    },
    {
      title: '偏差率',
      dataIndex: 'variance_rate',
      width: 90,
      render: (v: number) => {
        const pct = (v * 100).toFixed(1);
        const overBudget = v > 0;
        return (
          <Tag color={overBudget ? 'red' : 'green'}>
            {overBudget ? '+' : ''}{pct}%
          </Tag>
        );
      },
    },
    { title: '上期(元)', dataIndex: 'last_period_fen', width: 110, render: (v: number) => fen2yuan(v) },
    {
      title: '环比',
      dataIndex: 'mom_rate',
      width: 90,
      render: (v: number) => {
        const pct = (v * 100).toFixed(1);
        return (
          <Text style={{ color: v > 0 ? '#ff4d4f' : '#52c41a' }}>
            {v > 0 ? '+' : ''}{pct}%
          </Text>
        );
      },
    },
  ];

  const analysisData: AnalysisRow[] = report?.analysis?.stores
    ? Object.entries(report.analysis.stores).map(([sid, s]) => ({
        key: sid,
        store_id: sid,
        ...(s as StoreAnalysis),
      }))
    : [];

  // ── Render ────────────────────────────────────────────

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <DollarOutlined style={{ color: TX_PRIMARY, marginRight: 8 }} />
            借调成本分摊报表
          </Title>
        </Col>
        <Col>
          <Space>
            <Select
              value={storeId}
              onChange={setStoreId}
              style={{ width: 200 }}
              placeholder="选择门店"
              options={stores.map((s) => ({ label: s.store_name, value: s.store_id }))}
            />
            <DatePicker
              picker="month"
              value={dayjs(month, 'YYYY-MM')}
              onChange={(d) => d && setMonth(d.format('YYYY-MM'))}
              allowClear={false}
            />
          </Space>
        </Col>
      </Row>

      {/* 汇总统计 */}
      {report && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={8}>
            <Card>
              <Statistic
                title="总实际成本"
                value={fen2yuan(report.analysis?.total_actual_fen ?? 0)}
                prefix="&yen;"
                valueStyle={{ color: TX_PRIMARY }}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card>
              <Statistic
                title="总预算"
                value={fen2yuan(report.analysis?.total_budget_fen ?? 0)}
                prefix="&yen;"
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card>
              <Statistic
                title="总偏差"
                value={fen2yuan(report.analysis?.total_variance_fen ?? 0)}
                prefix="&yen;"
                valueStyle={{
                  color: (report.analysis?.total_variance_fen ?? 0) > 0 ? '#ff4d4f' : '#52c41a',
                }}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* 三表Tab */}
      <Card>
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: 'detail',
              label: '明细分摊表',
              children: (
                <Table
                  columns={detailColumns}
                  dataSource={(report?.detail ?? []).map((d) => ({ ...d, key: d.employee_id }))}
                  loading={loading}
                  pagination={false}
                  size="middle"
                />
              ),
            },
            {
              key: 'summary',
              label: '薪资汇总表',
              children: (
                <Table
                  columns={summaryColumns}
                  dataSource={summaryData}
                  loading={loading}
                  pagination={false}
                  size="middle"
                  summary={() =>
                    report?.summary ? (
                      <Table.Summary.Row>
                        <Table.Summary.Cell index={0}>
                          <Text strong>合计</Text>
                        </Table.Summary.Cell>
                        <Table.Summary.Cell index={1}>-</Table.Summary.Cell>
                        <Table.Summary.Cell index={2}>-</Table.Summary.Cell>
                        <Table.Summary.Cell index={3}>-</Table.Summary.Cell>
                        <Table.Summary.Cell index={4}>-</Table.Summary.Cell>
                        <Table.Summary.Cell index={5}>
                          <Text strong>{fen2yuan(report.summary.grand_total_fen)}</Text>
                        </Table.Summary.Cell>
                      </Table.Summary.Row>
                    ) : undefined
                  }
                />
              ),
            },
            {
              key: 'analysis',
              label: '成本分析表',
              children: (
                <Table
                  columns={analysisColumns}
                  dataSource={analysisData}
                  loading={loading}
                  pagination={false}
                  size="middle"
                />
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
}
