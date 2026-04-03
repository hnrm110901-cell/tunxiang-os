/**
 * AI 财务稽核页面 — Finance Audit (tx-brain Agent)
 * 调用 POST /api/v1/brain/finance/audit
 * 功能: 搜索触发区 + 稽核结果展示区 + 历史记录区
 */
import { useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  DatePicker,
  Empty,
  List,
  Modal,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { txFetch } from '../../api';

const { Title, Text, Paragraph } = Typography;

// ─── 常量 ───

const MOCK_STORES = [
  { value: 'store_001', label: '尝在一起·芙蓉路店' },
  { value: 'store_002', label: '尝在一起·五一广场店' },
  { value: 'store_003', label: '最黔线·解放西路店' },
  { value: 'store_004', label: '尚宫厨·麓谷店' },
];

// Mock 财务数据 payload（后续接真实 API）
const MOCK_FINANCE_PAYLOAD = {
  revenue_fen: 120000000,       // 120万
  cost_fen: 72000000,           // 72万
  discount_total_fen: 8000000,  // 8万
  void_count: 3,
  void_amount_fen: 150000,
  cash_actual_fen: 5000000,
  cash_expected_fen: 5050000,
  high_discount_orders: [],
  total_order_count: 280,
};

// ─── 类型定义 ───

type RiskLevel = 'critical' | 'high' | 'medium' | 'low';
type AnomalySeverity = 'info' | 'warn' | 'critical';

interface HardConstraints {
  margin_ok: boolean;
  void_rate_ok: boolean;
  cash_diff_ok: boolean;
}

interface AnomalyItem {
  type: string;
  description: string;
  severity: AnomalySeverity;
  amount_fen?: number;
}

interface AuditResult {
  risk_level: RiskLevel;
  score: number;
  source: 'claude' | 'fallback';
  hard_constraints: HardConstraints;
  anomalies: AnomalyItem[];
  suggestions: string[];
  audit_date?: string;
  store_id?: string;
  store_name?: string;
  audited_at?: string;
}

interface HistoryRecord {
  id: string;
  audit_date: string;
  store_id: string;
  store_name: string;
  risk_level: RiskLevel;
  score: number;
  result: AuditResult;
}

// ─── 颜色映射 ───

const RISK_COLOR: Record<RiskLevel, string> = {
  critical: '#A32D2D',
  high: '#BA7517',
  medium: '#9B8000',
  low: '#0F6E56',
};

const RISK_LABEL: Record<RiskLevel, string> = {
  critical: '严重风险',
  high: '高风险',
  medium: '中等风险',
  low: '低风险',
};

const SEVERITY_COLOR: Record<AnomalySeverity, string> = {
  info: 'default',
  warn: 'orange',
  critical: 'red',
};

const SEVERITY_LABEL: Record<AnomalySeverity, string> = {
  info: '信息',
  warn: '警告',
  critical: '严重',
};

// ─── 工具函数 ───

function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

function loadHistory(): HistoryRecord[] {
  try {
    const raw = localStorage.getItem('tx_finance_audit_history');
    return raw ? (JSON.parse(raw) as HistoryRecord[]) : [];
  } catch {
    return [];
  }
}

function saveHistory(record: HistoryRecord): void {
  const history = loadHistory();
  const updated = [record, ...history].slice(0, 20);
  localStorage.setItem('tx_finance_audit_history', JSON.stringify(updated));
}

// ─── 子组件：风险等级卡 ───

function RiskLevelCard({ result }: { result: AuditResult }) {
  const bg = RISK_COLOR[result.risk_level];
  const label = RISK_LABEL[result.risk_level];

  return (
    <div style={{
      background: bg,
      borderRadius: 8,
      padding: '24px 32px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginBottom: 24,
    }}>
      <div>
        <Text style={{ color: 'rgba(255,255,255,0.7)', fontSize: 13 }}>综合风险等级</Text>
        <div style={{ fontSize: 32, fontWeight: 700, color: '#fff', marginTop: 4 }}>
          {label}
        </div>
      </div>
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 48, fontWeight: 700, color: '#fff', lineHeight: 1 }}>
          {result.score}
        </div>
        <div style={{ color: 'rgba(255,255,255,0.7)', fontSize: 12, marginTop: 4 }}>AI 评分 (0-100)</div>
      </div>
      <div style={{ textAlign: 'right' }}>
        <Tag color={result.source === 'claude' ? 'blue' : 'default'} style={{ fontSize: 12 }}>
          {result.source === 'claude' ? '🤖 Claude AI' : '🔄 规则引擎'}
        </Tag>
        <div style={{ color: 'rgba(255,255,255,0.6)', fontSize: 11, marginTop: 6 }}>分析来源</div>
      </div>
    </div>
  );
}

// ─── 子组件：三条硬约束 ───

function HardConstraintsRow({ constraints }: { constraints: HardConstraints }) {
  const items: Array<{ key: keyof HardConstraints; label: string; desc: string }> = [
    { key: 'margin_ok', label: '毛利底线', desc: '单笔毛利不低于设定阈值' },
    { key: 'void_rate_ok', label: '作废率合规', desc: '作废单比例在合理区间' },
    { key: 'cash_diff_ok', label: '现金差异', desc: '实收与应收差额在允许范围内' },
  ];

  return (
    <Row gutter={16} style={{ marginBottom: 24 }}>
      {items.map(({ key, label, desc }) => {
        const ok = constraints[key];
        return (
          <Col span={8} key={key}>
            <Card
              size="small"
              style={{
                borderColor: ok ? '#0F6E56' : '#A32D2D',
                borderWidth: 2,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{
                  fontSize: 24,
                  color: ok ? '#0F6E56' : '#A32D2D',
                }}>
                  {ok ? '✓' : '✗'}
                </span>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{label}</div>
                  <div style={{ color: '#5F5E5A', fontSize: 12 }}>{desc}</div>
                  <Badge
                    status={ok ? 'success' : 'error'}
                    text={ok ? '通过' : '异常'}
                    style={{ fontSize: 12 }}
                  />
                </div>
              </div>
            </Card>
          </Col>
        );
      })}
    </Row>
  );
}

// ─── 子组件：异常项 Table ───

function AnomalyTable({ anomalies }: { anomalies: AnomalyItem[] }) {
  const columns: ColumnsType<AnomalyItem> = [
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 120,
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
    },
    {
      title: '严重程度',
      dataIndex: 'severity',
      key: 'severity',
      width: 100,
      render: (sev: AnomalySeverity) => (
        <Tag color={SEVERITY_COLOR[sev]}>{SEVERITY_LABEL[sev]}</Tag>
      ),
    },
    {
      title: '涉及金额',
      dataIndex: 'amount_fen',
      key: 'amount_fen',
      width: 120,
      render: (val?: number) =>
        val != null ? `¥${fenToYuan(val)} 元` : '-',
    },
  ];

  if (anomalies.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={
          <Text style={{ color: '#0F6E56', fontWeight: 500 }}>
            ✅ 未发现财务异常，经营状况良好
          </Text>
        }
      />
    );
  }

  return (
    <Table
      columns={columns}
      dataSource={anomalies}
      rowKey={(r, idx) => `${r.type}_${idx}`}
      pagination={false}
      size="small"
    />
  );
}

// ─── 主页面 ───

export function FinanceAuditPage() {
  const [storeId, setStoreId] = useState<string | undefined>(undefined);
  const [auditDate, setAuditDate] = useState<string | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AuditResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryRecord[]>(loadHistory);
  const [detailRecord, setDetailRecord] = useState<HistoryRecord | null>(null);

  // 提交稽核
  const handleAudit = async () => {
    if (!storeId) {
      setError('请先选择门店');
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const payload = {
        store_id: storeId,
        audit_date: auditDate || new Date().toISOString().slice(0, 10),
        ...MOCK_FINANCE_PAYLOAD,
      };

      const data = await txFetch<AuditResult>('/api/v1/brain/finance/audit', {
        method: 'POST',
        body: JSON.stringify(payload),
      });

      const enriched: AuditResult = {
        ...data,
        store_id: storeId,
        store_name: MOCK_STORES.find((s) => s.value === storeId)?.label || storeId,
        audit_date: payload.audit_date,
        audited_at: new Date().toISOString(),
      };

      setResult(enriched);

      // 存入 localStorage
      const record: HistoryRecord = {
        id: `audit_${Date.now()}`,
        audit_date: payload.audit_date,
        store_id: storeId,
        store_name: enriched.store_name || storeId,
        risk_level: enriched.risk_level,
        score: enriched.score,
        result: enriched,
      };
      saveHistory(record);
      setHistory(loadHistory());
    } catch (err) {
      setError(err instanceof Error ? err.message : '稽核请求失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  // 历史记录 Table 列
  const historyColumns: ColumnsType<HistoryRecord> = [
    {
      title: '日期',
      dataIndex: 'audit_date',
      key: 'audit_date',
      width: 120,
    },
    {
      title: '门店',
      dataIndex: 'store_name',
      key: 'store_name',
    },
    {
      title: '风险等级',
      dataIndex: 'risk_level',
      key: 'risk_level',
      width: 110,
      render: (level: RiskLevel) => (
        <Tag color={
          level === 'critical' ? 'red' :
          level === 'high' ? 'orange' :
          level === 'medium' ? 'gold' : 'green'
        }>
          {RISK_LABEL[level]}
        </Tag>
      ),
    },
    {
      title: 'AI评分',
      dataIndex: 'score',
      key: 'score',
      width: 80,
      render: (score: number) => <Text strong>{score}</Text>,
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_, record) => (
        <a onClick={() => setDetailRecord(record)}>查看详情</a>
      ),
    },
  ];

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      {/* 页面标题 */}
      <div style={{ marginBottom: 24 }}>
        <Title level={2} style={{ margin: 0, color: '#2C2C2A' }}>
          AI 财务稽核
        </Title>
        <Paragraph style={{ color: '#5F5E5A', margin: '8px 0 0', fontSize: 14 }}>
          由 tx-brain Claude 智能体驱动，自动分析门店每日财务数据，识别异常、评估风险并生成稽核建议。
        </Paragraph>
      </div>

      {/* 1. 搜索触发区 */}
      <Card
        title="发起稽核"
        style={{ marginBottom: 24 }}
        styles={{ body: { padding: '20px 24px' } }}
      >
        <Space size={12} wrap>
          <Select
            placeholder="选择门店"
            options={MOCK_STORES}
            value={storeId}
            onChange={setStoreId}
            style={{ width: 220 }}
            allowClear
          />
          <DatePicker
            placeholder="稽核日期（默认今日）"
            onChange={(_, dateStr) =>
              setAuditDate(Array.isArray(dateStr) ? dateStr[0] : dateStr)
            }
            style={{ width: 200 }}
          />
          <Button
            type="primary"
            loading={loading}
            onClick={handleAudit}
            style={{ background: '#FF6B35', borderColor: '#FF6B35' }}
          >
            🔍 开始 AI 稽核
          </Button>
        </Space>

        {error && (
          <Alert
            type="error"
            message={error}
            showIcon
            style={{ marginTop: 16 }}
            closable
            onClose={() => setError(null)}
          />
        )}
      </Card>

      {/* 2. 稽核结果展示区 */}
      {result && (
        <Card
          title={
            <Space>
              <span>稽核结果</span>
              <Text type="secondary" style={{ fontSize: 13 }}>
                {result.store_name} · {result.audit_date}
              </Text>
            </Space>
          }
          style={{ marginBottom: 24 }}
        >
          {/* 风险等级卡 */}
          <RiskLevelCard result={result} />

          {/* 三条硬约束 */}
          <Title level={5} style={{ marginBottom: 12 }}>三条硬约束校验</Title>
          <HardConstraintsRow constraints={result.hard_constraints} />

          {/* 异常项列表 */}
          <Title level={5} style={{ marginBottom: 12 }}>
            异常项列表
            {result.anomalies.length > 0 && (
              <Tag color="red" style={{ marginLeft: 8 }}>
                {result.anomalies.length} 条
              </Tag>
            )}
          </Title>
          <div style={{ marginBottom: 24 }}>
            <AnomalyTable anomalies={result.anomalies} />
          </div>

          {/* 审计建议 */}
          {result.suggestions.length > 0 && (
            <>
              <Title level={5} style={{ marginBottom: 12 }}>审计建议</Title>
              <List
                dataSource={result.suggestions}
                renderItem={(item) => (
                  <List.Item style={{ padding: '8px 0', borderBottom: '1px solid #F0EDE6' }}>
                    <Space align="start">
                      <span style={{ fontSize: 16 }}>💡</span>
                      <Text>{item}</Text>
                    </Space>
                  </List.Item>
                )}
                style={{ background: '#F8F7F5', borderRadius: 6, padding: '4px 16px' }}
              />
            </>
          )}
        </Card>
      )}

      {/* 3. 历史记录区 */}
      <Card title="历史稽核记录">
        {history.length === 0 ? (
          <Empty description="暂无历史记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <Table
            columns={historyColumns}
            dataSource={history}
            rowKey="id"
            pagination={{ pageSize: 10, showSizeChanger: false }}
            size="small"
          />
        )}
      </Card>

      {/* 详情 Modal */}
      <Modal
        title={
          detailRecord
            ? `稽核详情 — ${detailRecord.store_name} · ${detailRecord.audit_date}`
            : '稽核详情'
        }
        open={!!detailRecord}
        onCancel={() => setDetailRecord(null)}
        footer={[
          <Button key="close" onClick={() => setDetailRecord(null)}>
            关闭
          </Button>,
        ]}
        width={720}
      >
        {detailRecord && (
          <pre style={{
            background: '#F8F7F5',
            borderRadius: 6,
            padding: 16,
            fontSize: 12,
            overflow: 'auto',
            maxHeight: 480,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
          }}>
            {JSON.stringify(detailRecord.result, null, 2)}
          </pre>
        )}
      </Modal>
    </div>
  );
}
