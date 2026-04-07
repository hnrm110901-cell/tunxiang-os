/**
 * 折扣守护Agent预警面板
 * P3-01: 会员折扣频率检测 + 客位连续折扣预警
 *
 * 适用场景：日结监控页 / 总部驾驶舱嵌入组件
 * 终端：Admin（总部管理后台）
 * 技术栈：Ant Design 5.x + ProComponents
 */
import React, { useEffect, useState, useCallback } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  Divider,
  Modal,
  Progress,
  Row,
  Spin,
  Statistic,
  Tag,
  Timeline,
  Tooltip,
  Typography,
} from 'antd';
import {
  AlertOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  EyeOutlined,
  ExclamationCircleOutlined,
  RiseOutlined,
  SafetyCertificateOutlined,
  StopOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { StatisticCard } from '@ant-design/pro-components';

const { Text, Title } = Typography;

// ─── 类型定义 ────────────────────────────────────────────────────────────────

interface HighFreqMember {
  member_id: string;
  name: string;
  discount_count: number;
  total_saved_fen: number;
  risk_level: 'low' | 'medium' | 'high';
  latest_discount: string;
  note: string;
}

interface RelatedEmployee {
  id: string;
  name: string;
  count: number;
}

interface SuspiciousTable {
  table_id: string;
  table_name: string;
  consecutive_discount_days: number;
  discount_count: number;
  related_employees: RelatedEmployee[];
  anomaly_score: number;
  note: string;
}

interface SummaryData {
  today: {
    checks: number;
    alerts: number;
    intercepted_fen: number;
  };
  realtime_session: {
    total_checks: number;
    total_alerts: number;
    intercepted_amount_fen: number;
  };
  top3_risky_employees: Array<{
    employee_id: string;
    name: string;
    suspicious_operations: number;
  }>;
  top3_risky_tables: Array<{
    table_id: string;
    table_name: string;
    anomaly_score: number;
    consecutive_days: number;
  }>;
}

interface DiscountGuardPanelProps {
  tenantId: string;
  storeId?: string;
  /** 是否显示"查看完整报告"按钮，默认 true */
  showReportLink?: boolean;
  /** 自定义报告页路径，默认 /agent/discount-guard */
  reportPath?: string;
  /** 自动刷新间隔（秒），0 = 不自动刷新，默认 60 */
  refreshInterval?: number;
}

// ─── 工具函数 ────────────────────────────────────────────────────────────────

const API_BASE = '/api/v1/agent/discount-guard';

const buildHeaders = (tenantId: string) => ({
  'Content-Type': 'application/json',
  'X-Tenant-ID': tenantId,
});

const riskLevelConfig = {
  high: { color: '#A32D2D', bg: '#FFF0F0', label: '高风险', icon: <StopOutlined /> },
  medium: { color: '#BA7517', bg: '#FFFBF0', label: '中风险', icon: <ExclamationCircleOutlined /> },
  low: { color: '#0F6E56', bg: '#F0FFF8', label: '低风险', icon: <CheckCircleOutlined /> },
};

const formatYuan = (fen: number): string => `¥${(fen / 100).toFixed(0)}`;

const anomalyScoreColor = (score: number): string => {
  if (score >= 0.8) return '#A32D2D';
  if (score >= 0.6) return '#BA7517';
  return '#0F6E56';
};

// ─── 子组件：高频会员列表 ─────────────────────────────────────────────────────

interface MemberListProps {
  members: HighFreqMember[];
  loading: boolean;
  onDetail: (member: HighFreqMember) => void;
}

const MemberList: React.FC<MemberListProps> = ({ members, loading, onDetail }) => {
  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '32px 0' }}>
        <Spin size="small" />
      </div>
    );
  }

  if (members.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '24px 0', color: '#B4B2A9' }}>
        <SafetyCertificateOutlined style={{ fontSize: 24, marginBottom: 8 }} />
        <div>暂无高频会员预警</div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {members.map((m) => {
        const cfg = riskLevelConfig[m.risk_level];
        return (
          <div
            key={m.member_id}
            style={{
              padding: '10px 12px',
              borderRadius: 6,
              border: `1px solid ${cfg.color}33`,
              background: cfg.bg,
              cursor: 'pointer',
              transition: 'box-shadow 200ms ease',
            }}
            onClick={() => onDetail(m)}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLDivElement).style.boxShadow = '0 4px 12px rgba(0,0,0,0.08)';
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLDivElement).style.boxShadow = 'none';
            }}
          >
            <Row align="middle" justify="space-between">
              <Col flex="auto">
                <Row align="middle" gutter={8}>
                  <Col>
                    <Tag
                      color={cfg.color}
                      icon={cfg.icon}
                      style={{ borderRadius: 4, fontSize: 12 }}
                    >
                      {cfg.label}
                    </Tag>
                  </Col>
                  <Col>
                    <Text strong style={{ fontSize: 14, color: '#2C2C2A' }}>
                      {m.name}
                    </Text>
                  </Col>
                </Row>
                <Row style={{ marginTop: 4 }} gutter={16}>
                  <Col>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      近30天 <Text strong style={{ color: cfg.color }}>{m.discount_count}次</Text>
                    </Text>
                  </Col>
                  <Col>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      累计减免{' '}
                      <Text strong style={{ color: cfg.color }}>
                        {formatYuan(m.total_saved_fen)}
                      </Text>
                    </Text>
                  </Col>
                </Row>
              </Col>
              <Col>
                <Tooltip title="查看详情">
                  <Button
                    type="text"
                    size="small"
                    icon={<EyeOutlined />}
                    style={{ color: '#185FA5' }}
                  />
                </Tooltip>
              </Col>
            </Row>
          </div>
        );
      })}
    </div>
  );
};

// ─── 子组件：异常桌台列表 ─────────────────────────────────────────────────────

interface TableListProps {
  tables: SuspiciousTable[];
  loading: boolean;
  onDetail: (table: SuspiciousTable) => void;
}

const TableList: React.FC<TableListProps> = ({ tables, loading, onDetail }) => {
  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '32px 0' }}>
        <Spin size="small" />
      </div>
    );
  }

  if (tables.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '24px 0', color: '#B4B2A9' }}>
        <SafetyCertificateOutlined style={{ fontSize: 24, marginBottom: 8 }} />
        <div>暂无异常桌台记录</div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {tables.map((t) => {
        const scoreColor = anomalyScoreColor(t.anomaly_score);
        const isCritical = t.anomaly_score >= 0.8;
        return (
          <div
            key={t.table_id}
            style={{
              padding: '10px 12px',
              borderRadius: 6,
              border: `1px solid ${scoreColor}33`,
              background: isCritical ? '#FFF0F0' : '#FFFBF0',
              cursor: 'pointer',
              transition: 'box-shadow 200ms ease',
              /* critical 预警脉冲动画 */
              animation: isCritical ? 'txPulse 1.5s infinite' : 'none',
            }}
            onClick={() => onDetail(t)}
          >
            <Row align="middle" justify="space-between">
              <Col flex="auto">
                <Row align="middle" gutter={8}>
                  <Col>
                    <Text strong style={{ fontSize: 14, color: '#2C2C2A' }}>
                      {t.table_name}
                    </Text>
                  </Col>
                  <Col>
                    <Tag color={scoreColor} style={{ borderRadius: 4, fontSize: 12 }}>
                      连续{t.consecutive_discount_days}天
                    </Tag>
                  </Col>
                </Row>
                <Row style={{ marginTop: 6 }} align="middle" gutter={8}>
                  <Col flex="auto">
                    <Tooltip title={`异常评分 ${(t.anomaly_score * 100).toFixed(0)}分`}>
                      <Progress
                        percent={Math.round(t.anomaly_score * 100)}
                        size="small"
                        strokeColor={scoreColor}
                        showInfo={false}
                        style={{ maxWidth: 120 }}
                      />
                    </Tooltip>
                  </Col>
                  <Col>
                    <Text style={{ fontSize: 12, color: scoreColor }}>
                      {(t.anomaly_score * 100).toFixed(0)}分
                    </Text>
                  </Col>
                </Row>
                {t.related_employees.length > 0 && (
                  <Row style={{ marginTop: 4 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      责任员工：
                      {t.related_employees
                        .map((e) => `${e.name}(${e.count}次)`)
                        .join('、')}
                    </Text>
                  </Row>
                )}
              </Col>
              <Col>
                <Tooltip title="查看详情">
                  <Button
                    type="text"
                    size="small"
                    icon={<EyeOutlined />}
                    style={{ color: '#185FA5' }}
                  />
                </Tooltip>
              </Col>
            </Row>
          </div>
        );
      })}
    </div>
  );
};

// ─── 主组件 ──────────────────────────────────────────────────────────────────

const DiscountGuardPanel: React.FC<DiscountGuardPanelProps> = ({
  tenantId,
  storeId,
  showReportLink = true,
  reportPath = '/agent/discount-guard',
  refreshInterval = 60,
}) => {
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [members, setMembers] = useState<HighFreqMember[]>([]);
  const [tables, setTables] = useState<SuspiciousTable[]>([]);
  const [loadingSummary, setLoadingSummary] = useState(true);
  const [loadingMembers, setLoadingMembers] = useState(true);
  const [loadingTables, setLoadingTables] = useState(true);
  const [detailMember, setDetailMember] = useState<HighFreqMember | null>(null);
  const [detailTable, setDetailTable] = useState<SuspiciousTable | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  const storeQuery = storeId ? `&store_id=${storeId}` : '';

  const fetchSummary = useCallback(async () => {
    setLoadingSummary(true);
    try {
      const res = await fetch(
        `${API_BASE}/summary?tenant_id=${tenantId}${storeQuery}`,
        { headers: buildHeaders(tenantId) },
      );
      const json = await res.json();
      if (json.ok) setSummary(json.data);
    } finally {
      setLoadingSummary(false);
    }
  }, [tenantId, storeQuery]);

  const fetchMembers = useCallback(async () => {
    setLoadingMembers(true);
    try {
      const res = await fetch(
        `${API_BASE}/member-frequency?tenant_id=${tenantId}${storeQuery}&days=30&threshold=3`,
        { headers: buildHeaders(tenantId) },
      );
      const json = await res.json();
      if (json.ok) setMembers(json.data.high_frequency_members ?? []);
    } finally {
      setLoadingMembers(false);
    }
  }, [tenantId, storeQuery]);

  const fetchTables = useCallback(async () => {
    setLoadingTables(true);
    try {
      const res = await fetch(
        `${API_BASE}/table-pattern?tenant_id=${tenantId}${storeQuery}&days=7&min_consecutive=2`,
        { headers: buildHeaders(tenantId) },
      );
      const json = await res.json();
      if (json.ok) setTables(json.data.suspicious_tables ?? []);
    } finally {
      setLoadingTables(false);
    }
  }, [tenantId, storeQuery]);

  const refresh = useCallback(() => {
    void fetchSummary();
    void fetchMembers();
    void fetchTables();
    setLastRefresh(new Date());
  }, [fetchSummary, fetchMembers, fetchTables]);

  // 初始加载
  useEffect(() => {
    refresh();
  }, [refresh]);

  // 自动刷新
  useEffect(() => {
    if (refreshInterval <= 0) return;
    const timer = setInterval(refresh, refreshInterval * 1000);
    return () => clearInterval(timer);
  }, [refresh, refreshInterval]);

  const todayChecks = summary?.today.checks ?? 0;
  const todayAlerts = summary?.today.alerts ?? 0;
  const todayIntercepted = summary?.today.intercepted_fen ?? 0;
  const alertRate = todayChecks > 0 ? ((todayAlerts / todayChecks) * 100).toFixed(1) : '0';

  return (
    <>
      {/* 全局脉冲动画样式 */}
      <style>{`
        @keyframes txPulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.75; }
        }
      `}</style>

      <Card
        title={
          <Row align="middle" gutter={8}>
            <Col>
              <AlertOutlined style={{ color: '#FF6B35', fontSize: 16 }} />
            </Col>
            <Col>
              <span style={{ fontSize: 15, fontWeight: 600, color: '#2C2C2A' }}>
                折扣守护 · 智能预警
              </span>
            </Col>
            {todayAlerts > 0 && (
              <Col>
                <Badge
                  count={todayAlerts}
                  style={{ backgroundColor: '#A32D2D' }}
                  overflowCount={99}
                />
              </Col>
            )}
          </Row>
        }
        extra={
          <Row align="middle" gutter={8}>
            <Col>
              <Text type="secondary" style={{ fontSize: 12 }}>
                <ClockCircleOutlined style={{ marginRight: 4 }} />
                {lastRefresh.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}更新
              </Text>
            </Col>
            <Col>
              <Button size="small" onClick={refresh} style={{ borderColor: '#FF6B35', color: '#FF6B35' }}>
                刷新
              </Button>
            </Col>
          </Row>
        }
        style={{
          borderRadius: 8,
          boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
        }}
        bodyStyle={{ padding: '16px 20px' }}
      >
        {/* 顶部统计卡片 */}
        <Row gutter={12} style={{ marginBottom: 20 }}>
          <Col span={8}>
            <StatisticCard
              statistic={{
                title: '今日已检查',
                value: todayChecks,
                suffix: '笔',
                icon: <SafetyCertificateOutlined style={{ color: '#185FA5' }} />,
              }}
              loading={loadingSummary}
              style={{ borderRadius: 6, border: '1px solid #E8E6E1' }}
            />
          </Col>
          <Col span={8}>
            <StatisticCard
              statistic={{
                title: '预警笔数',
                value: todayAlerts,
                suffix: `笔 (${alertRate}%)`,
                valueStyle: todayAlerts > 0 ? { color: '#A32D2D' } : {},
                icon: <ExclamationCircleOutlined style={{ color: todayAlerts > 0 ? '#A32D2D' : '#0F6E56' }} />,
              }}
              loading={loadingSummary}
              style={{
                borderRadius: 6,
                border: `1px solid ${todayAlerts > 0 ? '#A32D2D44' : '#E8E6E1'}`,
                background: todayAlerts > 0 ? '#FFF8F8' : undefined,
              }}
            />
          </Col>
          <Col span={8}>
            <StatisticCard
              statistic={{
                title: '节省金额',
                value: formatYuan(todayIntercepted),
                description: (
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    因拦截避免的异常折扣
                  </Text>
                ),
                icon: <RiseOutlined style={{ color: '#0F6E56' }} />,
              }}
              loading={loadingSummary}
              style={{ borderRadius: 6, border: '1px solid #E8E6E1' }}
            />
          </Col>
        </Row>

        <Divider style={{ margin: '0 0 16px' }} />

        {/* 两栏内容 */}
        <Row gutter={20}>
          {/* 左栏：高频会员预警 */}
          <Col span={12}>
            <div style={{ marginBottom: 10 }}>
              <Row align="middle" justify="space-between">
                <Col>
                  <Row align="middle" gutter={6}>
                    <Col>
                      <UserOutlined style={{ color: '#A32D2D' }} />
                    </Col>
                    <Col>
                      <Text strong style={{ fontSize: 13 }}>
                        高频会员预警
                      </Text>
                    </Col>
                    <Col>
                      <Badge
                        count={members.length}
                        style={{
                          backgroundColor: members.length > 0 ? '#A32D2D' : '#0F6E56',
                          fontSize: 11,
                        }}
                      />
                    </Col>
                  </Row>
                </Col>
                <Col>
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    近30天 / 阈值3次
                  </Text>
                </Col>
              </Row>
            </div>
            <MemberList
              members={members}
              loading={loadingMembers}
              onDetail={setDetailMember}
            />
          </Col>

          {/* 右栏：异常桌台列表 */}
          <Col span={12}>
            <div style={{ marginBottom: 10 }}>
              <Row align="middle" justify="space-between">
                <Col>
                  <Row align="middle" gutter={6}>
                    <Col>
                      <AlertOutlined style={{ color: '#BA7517' }} />
                    </Col>
                    <Col>
                      <Text strong style={{ fontSize: 13 }}>
                        异常桌台预警
                      </Text>
                    </Col>
                    <Col>
                      <Badge
                        count={tables.length}
                        style={{
                          backgroundColor: tables.length > 0 ? '#BA7517' : '#0F6E56',
                          fontSize: 11,
                        }}
                      />
                    </Col>
                  </Row>
                </Col>
                <Col>
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    近7天 / 连续≥2天
                  </Text>
                </Col>
              </Row>
            </div>
            <TableList
              tables={tables}
              loading={loadingTables}
              onDetail={setDetailTable}
            />
          </Col>
        </Row>

        {/* 底部：完整报告 */}
        {showReportLink && (
          <>
            <Divider style={{ margin: '16px 0 12px' }} />
            <Row justify="center">
              <Col>
                <Button
                  type="primary"
                  icon={<EyeOutlined />}
                  onClick={() => window.open(reportPath, '_blank')}
                  style={{ backgroundColor: '#FF6B35', borderColor: '#FF6B35', borderRadius: 6 }}
                >
                  查看完整折扣守护报告
                </Button>
              </Col>
            </Row>
          </>
        )}
      </Card>

      {/* 会员详情弹窗 */}
      <Modal
        title={
          <Row align="middle" gutter={8}>
            <Col>
              <UserOutlined style={{ color: '#A32D2D' }} />
            </Col>
            <Col>会员折扣频率详情</Col>
          </Row>
        }
        open={detailMember !== null}
        onCancel={() => setDetailMember(null)}
        footer={
          <Button type="primary" onClick={() => setDetailMember(null)}
            style={{ backgroundColor: '#FF6B35', borderColor: '#FF6B35' }}>
            关闭
          </Button>
        }
        width={480}
      >
        {detailMember && (
          <div>
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={12}>
                <Statistic
                  title="会员姓名"
                  value={detailMember.name}
                  valueStyle={{ fontSize: 16 }}
                />
              </Col>
              <Col span={12}>
                <Statistic
                  title="风险等级"
                  value={riskLevelConfig[detailMember.risk_level].label}
                  valueStyle={{
                    color: riskLevelConfig[detailMember.risk_level].color,
                    fontSize: 16,
                  }}
                />
              </Col>
            </Row>
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={12}>
                <Statistic
                  title="近30天折扣次数"
                  value={detailMember.discount_count}
                  suffix="次"
                  valueStyle={{ color: '#A32D2D' }}
                />
              </Col>
              <Col span={12}>
                <Statistic
                  title="累计减免金额"
                  value={formatYuan(detailMember.total_saved_fen)}
                  valueStyle={{ color: '#A32D2D' }}
                />
              </Col>
            </Row>
            <Divider />
            <Timeline
              items={[
                {
                  color: riskLevelConfig[detailMember.risk_level].color,
                  children: (
                    <>
                      <Text strong>最近折扣</Text>
                      <br />
                      <Text type="secondary">{detailMember.latest_discount}</Text>
                    </>
                  ),
                },
                {
                  color: '#185FA5',
                  children: (
                    <>
                      <Text strong>Agent分析</Text>
                      <br />
                      <Text type="secondary">{detailMember.note}</Text>
                    </>
                  ),
                },
              ]}
            />
          </div>
        )}
      </Modal>

      {/* 桌台详情弹窗 */}
      <Modal
        title={
          <Row align="middle" gutter={8}>
            <Col>
              <AlertOutlined style={{ color: '#BA7517' }} />
            </Col>
            <Col>桌台异常折扣详情</Col>
          </Row>
        }
        open={detailTable !== null}
        onCancel={() => setDetailTable(null)}
        footer={
          <Button type="primary" onClick={() => setDetailTable(null)}
            style={{ backgroundColor: '#FF6B35', borderColor: '#FF6B35' }}>
            关闭
          </Button>
        }
        width={480}
      >
        {detailTable && (
          <div>
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={12}>
                <Statistic
                  title="桌台"
                  value={detailTable.table_name}
                  valueStyle={{ fontSize: 16 }}
                />
              </Col>
              <Col span={12}>
                <Statistic
                  title="连续折扣天数"
                  value={detailTable.consecutive_discount_days}
                  suffix="天"
                  valueStyle={{ color: anomalyScoreColor(detailTable.anomaly_score) }}
                />
              </Col>
            </Row>
            <div style={{ marginBottom: 16 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>异常评分</Text>
              <Progress
                percent={Math.round(detailTable.anomaly_score * 100)}
                strokeColor={anomalyScoreColor(detailTable.anomaly_score)}
                style={{ marginTop: 4 }}
              />
            </div>
            <Divider />
            <Title level={5} style={{ fontSize: 13, marginBottom: 8 }}>
              关联员工操作记录
            </Title>
            {detailTable.related_employees.map((emp) => (
              <Row
                key={emp.id}
                justify="space-between"
                align="middle"
                style={{
                  padding: '8px 12px',
                  background: '#F8F7F5',
                  borderRadius: 6,
                  marginBottom: 6,
                }}
              >
                <Col>
                  <UserOutlined style={{ marginRight: 6, color: '#5F5E5A' }} />
                  <Text>{emp.name}</Text>
                </Col>
                <Col>
                  <Tag color="#BA7517">{emp.count}次</Tag>
                </Col>
              </Row>
            ))}
            <Divider />
            <div
              style={{
                padding: '10px 12px',
                background: '#FFF3ED',
                borderRadius: 6,
                borderLeft: '3px solid #FF6B35',
              }}
            >
              <Text style={{ fontSize: 13, color: '#2C2C2A' }}>
                <AlertOutlined style={{ color: '#FF6B35', marginRight: 6 }} />
                {detailTable.note}
              </Text>
            </div>
          </div>
        )}
      </Modal>
    </>
  );
};

export default DiscountGuardPanel;
