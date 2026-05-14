/**
 * doc_number 规则配置 + fallback 健康度仪表板
 *
 * 域：供应链 / 单号规则
 * 路由：/supply/doc-number-rules
 * 来源 issue：#592（PR #586 §19 round-2 follow-up → PR-03D admin UI）
 *
 * 功能（最小可用 — 见 docs/operations/doc-number-fallback-runbook.md）：
 *   1. 当前 doc_number 模板列表（read-only，按 doc_type 分组）
 *   2. 进程级 fallback Counter snapshot（GET /api/v1/doc-number/fallback-stats）
 *      - 总数 + by_service + by_doc_type + by_combo 表
 *      - 颜色编码：0 = success；1-9 = warning；≥10 = danger
 *   3. Prometheus 时序看板 + 告警规则文档链接
 *
 * 不在本页范围（issue #592 提到但 YAGNI 拒绝）：
 *   - "运维补单号"工具 — 风险大（侵入 Tier 1 单据），需单独 PR + 创始人决策
 *   - 24h 历史趋势 — 这是 Prometheus + Grafana 的职责，本页只给 snapshot
 */
import { useEffect, useState, useCallback } from 'react';
import {
  Card,
  Table,
  Tag,
  Button,
  Space,
  Typography,
  Alert,
  Statistic,
  Row,
  Col,
  message,
  Spin,
} from 'antd';
import {
  ReloadOutlined,
  ExclamationCircleOutlined,
  CheckCircleOutlined,
  WarningOutlined,
  LinkOutlined,
} from '@ant-design/icons';
import { txFetchData } from '../../api/client';

const { Title, Text, Paragraph } = Typography;

// ─── 类型 ─────────────────────────────────────────────────────────────────────

interface ComboRow {
  service: string;
  doc_type: string;
  value: number;
}

interface FallbackStatsResponse {
  total: number;
  by_service: Record<string, number>;
  by_doc_type: Record<string, number>;
  by_combo: ComboRow[];
  note: string;
}

// ─── 颜色阈值（与 docs/operations/doc-number-fallback-runbook.md §告警规则 一致） ──

function severityColor(value: number): 'default' | 'warning' | 'error' {
  if (value <= 0) return 'default';
  if (value < 10) return 'warning';
  return 'error';
}

function severityIcon(value: number) {
  if (value <= 0) return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
  if (value < 10) return <WarningOutlined style={{ color: '#faad14' }} />;
  return <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />;
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export function DocNumberRulesPage() {
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState<FallbackStatsResponse | null>(null);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErrMsg(null);
    try {
      const data = await txFetchData<FallbackStatsResponse>(
        '/api/v1/doc-number/fallback-stats',
      );
      setStats(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrMsg(msg);
      message.error(`加载 fallback 统计失败: ${msg}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const total = stats?.total ?? 0;

  return (
    <div style={{ padding: 24 }}>
      <Space style={{ marginBottom: 16, justifyContent: 'space-between', width: '100%' }}>
        <Title level={3} style={{ margin: 0 }}>
          单号规则 & Fallback 健康度
        </Title>
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
          刷新
        </Button>
      </Space>

      <Alert
        type="info"
        showIcon
        message="数据范围"
        description={
          <>
            <Text>
              下表显示当前 tx-supply 进程的 doc_number 生成 fallback Counter 快照（pod 重启清零）。
              历史趋势 + 告警规则配置见{' '}
            </Text>
            <a
              href="/docs/operations/doc-number-fallback-runbook.md"
              target="_blank"
              rel="noreferrer"
            >
              <LinkOutlined /> Fallback Runbook
            </a>
            <Text>。Prometheus 指标名：</Text>
            <Text code>tx_supply_doc_number_fallback_null_count</Text>
            <Text>。</Text>
          </>
        }
        style={{ marginBottom: 16 }}
      />

      {errMsg && (
        <Alert
          type="error"
          showIcon
          message="加载失败"
          description={errMsg}
          style={{ marginBottom: 16 }}
          closable
          onClose={() => setErrMsg(null)}
        />
      )}

      <Spin spinning={loading}>
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col xs={24} md={8}>
            <Card>
              <Statistic
                title="累计 fallback 次数（进程级）"
                value={total}
                prefix={severityIcon(total)}
                valueStyle={{
                  color:
                    total <= 0
                      ? '#52c41a'
                      : total < 10
                        ? '#faad14'
                        : '#ff4d4f',
                }}
              />
              <Text type="secondary">阈值：5min 内 ≥ 10 触发 PagerDuty</Text>
            </Card>
          </Col>
          <Col xs={24} md={8}>
            <Card title="按 service 维度" size="small">
              {stats && Object.keys(stats.by_service).length > 0 ? (
                <Space direction="vertical" style={{ width: '100%' }}>
                  {Object.entries(stats.by_service).map(([svc, v]) => (
                    <Space key={svc} style={{ justifyContent: 'space-between', width: '100%' }}>
                      <Text>{svc}</Text>
                      <Tag color={severityColor(v)}>{v}</Tag>
                    </Space>
                  ))}
                </Space>
              ) : (
                <Text type="secondary">无 fallback 记录</Text>
              )}
            </Card>
          </Col>
          <Col xs={24} md={8}>
            <Card title="按 doc_type 维度" size="small">
              {stats && Object.keys(stats.by_doc_type).length > 0 ? (
                <Space direction="vertical" style={{ width: '100%' }}>
                  {Object.entries(stats.by_doc_type).map(([dt, v]) => (
                    <Space key={dt} style={{ justifyContent: 'space-between', width: '100%' }}>
                      <Text>{dt}</Text>
                      <Tag color={severityColor(v)}>{v}</Tag>
                    </Space>
                  ))}
                </Space>
              ) : (
                <Text type="secondary">无 fallback 记录</Text>
              )}
            </Card>
          </Col>
        </Row>

        <Card title="完整明细（service × doc_type）">
          <Table<ComboRow>
            rowKey={(r) => `${r.service}__${r.doc_type}`}
            dataSource={stats?.by_combo ?? []}
            pagination={false}
            size="small"
            columns={[
              {
                title: 'service',
                dataIndex: 'service',
                key: 'service',
                render: (v: string) => <Text code>{v}</Text>,
              },
              {
                title: 'doc_type',
                dataIndex: 'doc_type',
                key: 'doc_type',
                render: (v: string) => <Text code>{v}</Text>,
              },
              {
                title: 'fallback 次数',
                dataIndex: 'value',
                key: 'value',
                align: 'right',
                render: (v: number) => (
                  <Tag color={severityColor(v)} icon={severityIcon(v)}>
                    {v}
                  </Tag>
                ),
              },
            ]}
            locale={{ emptyText: '当前进程无 fallback 记录（健康）' }}
          />
        </Card>

        {stats?.note && (
          <Paragraph type="secondary" style={{ marginTop: 16 }}>
            {stats.note}
          </Paragraph>
        )}
      </Spin>
    </div>
  );
}

export default DocNumberRulesPage;
