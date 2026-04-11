/**
 * AgentAutonomyPage — Agent 自治控制中心
 *
 * 9 个 Agent 卡片网格，支持自治等级调整（L1/L2/L3）
 * 等待确认操作列表 + 自治等级说明弹窗
 *
 * 纯 Mock 数据 + Ant Design 5.x
 */
import { useCallback, useMemo, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import {
  CheckOutlined,
  CloseOutlined,
  InfoCircleOutlined,
  RobotOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';

const { Title, Text, Paragraph } = Typography;

// ─── Design Tokens ───
const C = {
  primary: '#FF6B35',
  success: '#0F6E56',
  warning: '#BA7517',
  danger: '#A32D2D',
  info: '#185FA5',
  navy: '#1E2A3A',
  bgPrimary: '#FFFFFF',
  bgSecondary: '#F8F7F5',
  bgTertiary: '#F0EDE6',
  textPrimary: '#2C2C2A',
  textSub: '#5F5E5A',
  textMuted: '#B4B2A9',
  border: '#E8E6E1',
};

// ─── 自治等级定义 ───
interface AutonomyLevel {
  level: 'L1' | 'L2' | 'L3';
  label: string;
  color: string;
  description: string;
  detail: string;
}

const AUTONOMY_LEVELS: AutonomyLevel[] = [
  {
    level: 'L1',
    label: '人工确认',
    color: C.info,
    description: '所有决策需要人工确认后执行',
    detail: 'Agent 仅提供建议和分析，每项操作都需人工审批后才会执行。适合初期上线阶段，建立信任。',
  },
  {
    level: 'L2',
    label: '半自治',
    color: C.warning,
    description: '常规操作自动执行，关键决策需确认',
    detail: 'Agent 自动执行置信度 > 0.85 的常规操作（如常规库存补货、标准折扣审批），但金额超过阈值或异常情况仍需人工确认。',
  },
  {
    level: 'L3',
    label: '全自治',
    color: C.success,
    description: '所有决策自动执行，仅三条硬约束触发拦截',
    detail: 'Agent 全自动运行，仅当触发毛利底线/食安合规/客户体验三条硬约束时才暂停并请求人工介入。',
  },
];

// ─── 9 Agent 定义 ───
interface AgentInfo {
  id: string;
  name: string;
  icon: string;
  autonomyLevel: 'L1' | 'L2' | 'L3';
  auto24h: number;
  pending24h: number;
  effectLabel: string;
  effectValue: string;
  status: 'running' | 'paused' | 'error';
}

const MOCK_AGENTS: AgentInfo[] = [
  { id: 'discount_guard',  name: '折扣守护',  icon: '\u{1F6E1}\u{FE0F}', autonomyLevel: 'L3', auto24h: 47, pending24h: 2,  effectLabel: '本月拦截',     effectValue: '\u00A512,340', status: 'running' },
  { id: 'smart_menu',      name: '智能排菜',  icon: '\u{1F35C}',          autonomyLevel: 'L2', auto24h: 12, pending24h: 3,  effectLabel: '本月增量利润', effectValue: '\u00A58,920',  status: 'running' },
  { id: 'serve_dispatch',  name: '出餐调度',  icon: '\u26A1',             autonomyLevel: 'L3', auto24h: 186,pending24h: 0,  effectLabel: '超时减少',     effectValue: '34%',          status: 'running' },
  { id: 'member_insight',  name: '会员洞察',  icon: '\u{1F464}',          autonomyLevel: 'L2', auto24h: 8,  pending24h: 5,  effectLabel: '精准推荐率',   effectValue: '72.3%',        status: 'running' },
  { id: 'inventory_alert', name: '库存预警',  icon: '\u{1F4E6}',          autonomyLevel: 'L2', auto24h: 23, pending24h: 4,  effectLabel: '减少浪费',     effectValue: '\u00A53,200',  status: 'running' },
  { id: 'finance_audit',   name: '财务稽核',  icon: '\u{1F4B0}',          autonomyLevel: 'L1', auto24h: 0,  pending24h: 7,  effectLabel: '发现异常',     effectValue: '3笔',          status: 'running' },
  { id: 'store_inspect',   name: '巡店质检',  icon: '\u{1F50D}',          autonomyLevel: 'L1', auto24h: 0,  pending24h: 2,  effectLabel: '违规识别率',   effectValue: '91%',          status: 'paused'  },
  { id: 'smart_service',   name: '智能客服',  icon: '\u{1F4AC}',          autonomyLevel: 'L2', auto24h: 34, pending24h: 6,  effectLabel: '自动回复率',   effectValue: '78%',          status: 'running' },
  { id: 'private_ops',     name: '私域运营',  icon: '\u{1F4E3}',          autonomyLevel: 'L1', auto24h: 0,  pending24h: 3,  effectLabel: '触达会员',     effectValue: '2,340人',      status: 'running' },
];

// ─── 等待确认操作 ───
interface PendingAction {
  id: string;
  agentId: string;
  agentName: string;
  agentIcon: string;
  description: string;
  detail: string;
  confidence: number;
  impact: string;
  createdAt: string;
  priority: 'critical' | 'warning' | 'info';
}

const MOCK_PENDING: PendingAction[] = [
  { id: 'p1', agentId: 'finance_audit',   agentName: '财务稽核', agentIcon: '\u{1F4B0}', description: '\u5F02\u5E38\u8BA2\u5355\u5BA1\u6838', detail: '门店#003 昨日22:47有一笔\u00A52,880折扣，折扣率达62%，超出正常范围', confidence: 0.92, impact: '可能损失\u00A51,780', createdAt: '2026-04-09 08:12', priority: 'critical' },
  { id: 'p2', agentId: 'discount_guard',   agentName: '折扣守护', agentIcon: '\u{1F6E1}\u{FE0F}', description: '\u62E6\u622A\u8D85\u989D\u6298\u6263', detail: '门店#007 收银员申请满200减80，毛利将降至18%', confidence: 0.97, impact: '保护毛利\u00A5320', createdAt: '2026-04-09 09:35', priority: 'critical' },
  { id: 'p3', agentId: 'smart_menu',       agentName: '智能排菜', agentIcon: '\u{1F35C}', description: '\u83DC\u5355\u8C03\u6574\u5EFA\u8BAE', detail: '建议将"香辣蟹"从推荐位移除（近7天销量下降40%，退菜率12%）', confidence: 0.84, impact: '预计提升客单价\u00A55', createdAt: '2026-04-09 09:50', priority: 'warning' },
  { id: 'p4', agentId: 'inventory_alert',  agentName: '库存预警', agentIcon: '\u{1F4E6}', description: '\u7D27\u6025\u91C7\u8D2D\u5EFA\u8BAE', detail: '三文鱼库存仅剩6份，预计今日需求18份，建议紧急补货12份', confidence: 0.91, impact: '避免缺货损失约\u00A52,400', createdAt: '2026-04-09 10:05', priority: 'warning' },
  { id: 'p5', agentId: 'member_insight',   agentName: '会员洞察', agentIcon: '\u{1F464}', description: '\u6D41\u5931\u9884\u8B66\u53EC\u56DE', detail: '识别到28位高价值会员（月均消费>500）已30天未到店，建议发送定向优惠券', confidence: 0.88, impact: '预计召回8-12位', createdAt: '2026-04-09 10:20', priority: 'info' },
  { id: 'p6', agentId: 'smart_service',    agentName: '智能客服', agentIcon: '\u{1F4AC}', description: '\u590D\u6742\u6295\u8BC9\u8F6C\u4EBA\u5DE5', detail: '顾客"张女士"连续3次投诉菜品口味问题，AI置信度不足，建议转人工处理', confidence: 0.45, impact: '高价值客户维护', createdAt: '2026-04-09 10:30', priority: 'warning' },
  { id: 'p7', agentId: 'finance_audit',    agentName: '财务稽核', agentIcon: '\u{1F4B0}', description: '\u5F02\u5E38\u6536\u652F\u6838\u67E5', detail: '门店#005 本周原材料成本环比上升15%，但营收未同步增长', confidence: 0.86, impact: '需核实\u00A54,500差异', createdAt: '2026-04-09 10:45', priority: 'warning' },
  { id: 'p8', agentId: 'private_ops',      agentName: '私域运营', agentIcon: '\u{1F4E3}', description: '\u8425\u9500\u6587\u6848\u5BA1\u6279', detail: '已生成周末活动推文："小龙虾季狂欢——满3斤送1斤"，需确认后发布到3个社群', confidence: 0.82, impact: '预计触达1,200人', createdAt: '2026-04-09 11:00', priority: 'info' },
  { id: 'p9', agentId: 'store_inspect',    agentName: '巡店质检', agentIcon: '\u{1F50D}', description: '\u5DEB\u68C0\u5F02\u5E38\u62A5\u544A', detail: '门店#002 后厨地面清洁度评分72/100，低于标准线80分', confidence: 0.89, impact: '食安风险', createdAt: '2026-04-09 11:15', priority: 'warning' },
];

// ─── 组件 ───
export default function AgentAutonomyPage() {
  const [agents, setAgents] = useState<AgentInfo[]>(MOCK_AGENTS);
  const [pending, setPending] = useState<PendingAction[]>(MOCK_PENDING);
  const [levelModalOpen, setLevelModalOpen] = useState(false);
  const [detailModal, setDetailModal] = useState<PendingAction | null>(null);

  const totalAuto = useMemo(() => agents.reduce((s, a) => s + a.auto24h, 0), [agents]);
  const totalPending = useMemo(() => pending.length, [pending]);

  const handleLevelChange = useCallback((agentId: string, newLevel: 'L1' | 'L2' | 'L3') => {
    setAgents(prev => prev.map(a => a.id === agentId ? { ...a, autonomyLevel: newLevel } : a));
    const agent = MOCK_AGENTS.find(a => a.id === agentId);
    message.success(`${agent?.name ?? agentId} 自治等级已调整为 ${newLevel}`);
  }, []);

  const handleApprove = useCallback((actionId: string) => {
    setPending(prev => prev.filter(p => p.id !== actionId));
    message.success('已批准执行');
  }, []);

  const handleReject = useCallback((actionId: string) => {
    setPending(prev => prev.filter(p => p.id !== actionId));
    message.warning('已拒绝');
  }, []);

  const handleBatchApprove = useCallback(() => {
    setPending([]);
    message.success(`已批量批准 ${pending.length} 项操作`);
  }, [pending.length]);

  const getLevelDef = (level: 'L1' | 'L2' | 'L3') => AUTONOMY_LEVELS.find(l => l.level === level)!;

  // ─── 渲染 ───
  return (
    <div style={{ padding: 24, background: C.bgSecondary, minHeight: '100vh' }}>
      {/* 页面标题 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <Title level={3} style={{ margin: 0, color: C.textPrimary }}>
            <RobotOutlined style={{ color: C.primary, marginRight: 8 }} />
            Agent 自治控制中心
          </Title>
          <Text style={{ color: C.textSub }}>管理 9 个 Agent 的自治等级与待确认操作</Text>
        </div>
        <Space>
          <Button icon={<InfoCircleOutlined />} onClick={() => setLevelModalOpen(true)}>
            自治等级说明
          </Button>
        </Space>
      </div>

      {/* 顶部统计 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card size="small" style={{ borderTop: `3px solid ${C.primary}` }}>
            <Statistic title="Agent 总数" value={9} prefix={<RobotOutlined />} valueStyle={{ color: C.primary }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" style={{ borderTop: `3px solid ${C.success}` }}>
            <Statistic title="24h 自动执行" value={totalAuto} suffix="次" valueStyle={{ color: C.success }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" style={{ borderTop: `3px solid ${C.warning}` }}>
            <Statistic title="等待确认" value={totalPending} suffix="项" valueStyle={{ color: C.warning }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" style={{ borderTop: `3px solid ${C.info}` }}>
            <Statistic title="全自治Agent" value={agents.filter(a => a.autonomyLevel === 'L3').length} suffix="个" valueStyle={{ color: C.info }} />
          </Card>
        </Col>
      </Row>

      {/* Agent 卡片网格 */}
      <Title level={5} style={{ color: C.textPrimary, marginBottom: 16 }}>Agent 列表</Title>
      <Row gutter={[16, 16]} style={{ marginBottom: 32 }}>
        {agents.map(agent => {
          const ld = getLevelDef(agent.autonomyLevel);
          return (
            <Col xs={24} sm={12} lg={8} key={agent.id}>
              <Card
                size="small"
                style={{
                  borderRadius: 8,
                  border: `1px solid ${C.border}`,
                  position: 'relative',
                  overflow: 'hidden',
                }}
                styles={{ body: { padding: 16 } }}
              >
                {/* 顶部色条 */}
                <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, background: ld.color }} />

                {/* Agent 名称 + 状态 */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                  <Space>
                    <span style={{ fontSize: 24 }}>{agent.icon}</span>
                    <div>
                      <Text strong style={{ fontSize: 15, color: C.textPrimary }}>{agent.name}</Text>
                      <br />
                      <Badge
                        status={agent.status === 'running' ? 'success' : agent.status === 'paused' ? 'warning' : 'error'}
                        text={<Text style={{ fontSize: 12, color: C.textMuted }}>{agent.status === 'running' ? '运行中' : agent.status === 'paused' ? '已暂停' : '异常'}</Text>}
                      />
                    </div>
                  </Space>
                  {/* 等级选择器 */}
                  <Select
                    value={agent.autonomyLevel}
                    onChange={(val) => handleLevelChange(agent.id, val)}
                    size="small"
                    style={{ width: 120 }}
                    options={AUTONOMY_LEVELS.map(l => ({
                      value: l.level,
                      label: (
                        <Space size={4}>
                          <span style={{
                            display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
                            background: l.color,
                          }} />
                          <span>{l.level} {l.label}</span>
                        </Space>
                      ),
                    }))}
                  />
                </div>

                {/* 24h 统计 */}
                <div style={{
                  display: 'flex', gap: 16, padding: '8px 12px',
                  background: C.bgSecondary, borderRadius: 6, marginBottom: 12,
                }}>
                  <div style={{ flex: 1, textAlign: 'center' }}>
                    <div style={{ fontSize: 20, fontWeight: 600, color: C.success }}>{agent.auto24h}</div>
                    <div style={{ fontSize: 12, color: C.textMuted }}>自动执行</div>
                  </div>
                  <div style={{ width: 1, background: C.border }} />
                  <div style={{ flex: 1, textAlign: 'center' }}>
                    <div style={{ fontSize: 20, fontWeight: 600, color: agent.pending24h > 0 ? C.warning : C.textMuted }}>{agent.pending24h}</div>
                    <div style={{ fontSize: 12, color: C.textMuted }}>等待确认</div>
                  </div>
                </div>

                {/* 效果指标 */}
                <div style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  padding: '6px 12px', background: `${C.info}08`, borderRadius: 6, border: `1px solid ${C.info}20`,
                }}>
                  <Text style={{ fontSize: 12, color: C.textSub }}>{agent.effectLabel}</Text>
                  <Text strong style={{ fontSize: 14, color: C.info }}>{agent.effectValue}</Text>
                </div>
              </Card>
            </Col>
          );
        })}
      </Row>

      {/* 等待确认操作列表 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={5} style={{ margin: 0, color: C.textPrimary }}>
          等待确认操作
          <Tag color="orange" style={{ marginLeft: 8 }}>{pending.length}</Tag>
        </Title>
        {pending.length > 0 && (
          <Button type="primary" icon={<CheckOutlined />} onClick={handleBatchApprove}
            style={{ background: C.success, borderColor: C.success }}>
            全部批准
          </Button>
        )}
      </div>

      <Card style={{ borderRadius: 8 }}>
        {pending.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 48, color: C.textMuted }}>
            <ThunderboltOutlined style={{ fontSize: 48, marginBottom: 16, opacity: 0.3 }} />
            <div>暂无等待确认的操作</div>
          </div>
        ) : (
          <Table
            dataSource={pending}
            rowKey="id"
            pagination={false}
            size="small"
            onRow={(record) => ({
              style: { cursor: 'pointer' },
              onClick: () => setDetailModal(record),
            })}
            columns={[
              {
                title: '优先级',
                dataIndex: 'priority',
                width: 80,
                render: (p: string) => {
                  const conf: Record<string, { color: string; text: string }> = {
                    critical: { color: C.danger, text: '紧急' },
                    warning: { color: C.warning, text: '重要' },
                    info: { color: C.info, text: '一般' },
                  };
                  const c = conf[p] ?? conf.info;
                  return <Tag style={{ color: c.color, borderColor: c.color, background: `${c.color}10` }}>{c.text}</Tag>;
                },
              },
              {
                title: 'Agent',
                dataIndex: 'agentName',
                width: 120,
                render: (name: string, r: PendingAction) => (
                  <Space size={4}>
                    <span>{r.agentIcon}</span>
                    <Text style={{ fontSize: 13 }}>{name}</Text>
                  </Space>
                ),
              },
              {
                title: '操作描述',
                dataIndex: 'description',
                render: (desc: string, r: PendingAction) => (
                  <div>
                    <Text strong style={{ fontSize: 13 }}>{desc}</Text>
                    <br />
                    <Text style={{ fontSize: 12, color: C.textSub }}>{r.detail}</Text>
                  </div>
                ),
              },
              {
                title: '置信度',
                dataIndex: 'confidence',
                width: 80,
                render: (v: number) => {
                  const color = v >= 0.9 ? C.success : v >= 0.7 ? C.warning : C.danger;
                  return <Text style={{ color, fontWeight: 600 }}>{(v * 100).toFixed(0)}%</Text>;
                },
              },
              {
                title: '影响',
                dataIndex: 'impact',
                width: 160,
                render: (v: string) => <Text style={{ fontSize: 12, color: C.textSub }}>{v}</Text>,
              },
              {
                title: '时间',
                dataIndex: 'createdAt',
                width: 140,
                render: (v: string) => <Text style={{ fontSize: 12, color: C.textMuted }}>{v}</Text>,
              },
              {
                title: '操作',
                width: 120,
                render: (_: unknown, r: PendingAction) => (
                  <Space>
                    <Tooltip title="批准">
                      <Button
                        type="primary" size="small" icon={<CheckOutlined />}
                        style={{ background: C.success, borderColor: C.success }}
                        onClick={(e) => { e.stopPropagation(); handleApprove(r.id); }}
                      />
                    </Tooltip>
                    <Tooltip title="拒绝">
                      <Button
                        danger size="small" icon={<CloseOutlined />}
                        onClick={(e) => { e.stopPropagation(); handleReject(r.id); }}
                      />
                    </Tooltip>
                  </Space>
                ),
              },
            ]}
          />
        )}
      </Card>

      {/* 自治等级说明弹窗 */}
      <Modal
        title={<><InfoCircleOutlined style={{ color: C.info, marginRight: 8 }} />自治等级说明</>}
        open={levelModalOpen}
        onCancel={() => setLevelModalOpen(false)}
        footer={<Button type="primary" onClick={() => setLevelModalOpen(false)}>了解了</Button>}
        width={640}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginTop: 16 }}>
          {AUTONOMY_LEVELS.map(l => (
            <div key={l.level} style={{
              padding: 16, borderRadius: 8,
              border: `1px solid ${l.color}40`,
              background: `${l.color}08`,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <span style={{
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  width: 32, height: 32, borderRadius: '50%',
                  background: l.color, color: '#fff', fontWeight: 700, fontSize: 13,
                }}>{l.level}</span>
                <Text strong style={{ fontSize: 16 }}>{l.label}</Text>
              </div>
              <Paragraph style={{ margin: 0, color: C.textSub, fontSize: 13 }}>{l.detail}</Paragraph>
            </div>
          ))}
        </div>
        <div style={{
          marginTop: 16, padding: 12, borderRadius: 8,
          background: `${C.danger}08`, border: `1px solid ${C.danger}20`,
        }}>
          <Text strong style={{ color: C.danger, fontSize: 13 }}>
            安全保障：无论哪个等级，三条硬约束（毛利底线/食安合规/客户体验）始终生效，不可绕过。
          </Text>
        </div>
      </Modal>

      {/* 操作详情弹窗 */}
      <Modal
        title={detailModal ? `${detailModal.agentIcon} ${detailModal.agentName} — ${detailModal.description}` : ''}
        open={!!detailModal}
        onCancel={() => setDetailModal(null)}
        footer={detailModal ? (
          <Space>
            <Button danger icon={<CloseOutlined />} onClick={() => { handleReject(detailModal.id); setDetailModal(null); }}>
              拒绝
            </Button>
            <Button type="primary" icon={<CheckOutlined />}
              style={{ background: C.success, borderColor: C.success }}
              onClick={() => { handleApprove(detailModal.id); setDetailModal(null); }}>
              批准执行
            </Button>
          </Space>
        ) : null}
        width={560}
      >
        {detailModal && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 8 }}>
            <div style={{ padding: 12, background: C.bgSecondary, borderRadius: 6 }}>
              <Text style={{ color: C.textSub, fontSize: 13 }}>{detailModal.detail}</Text>
            </div>
            <Row gutter={16}>
              <Col span={8}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 11, color: C.textMuted }}>置信度</div>
                  <div style={{
                    fontSize: 20, fontWeight: 700,
                    color: detailModal.confidence >= 0.9 ? C.success : detailModal.confidence >= 0.7 ? C.warning : C.danger,
                  }}>{(detailModal.confidence * 100).toFixed(0)}%</div>
                </div>
              </Col>
              <Col span={8}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 11, color: C.textMuted }}>预估影响</div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: C.textPrimary }}>{detailModal.impact}</div>
                </div>
              </Col>
              <Col span={8}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 11, color: C.textMuted }}>提交时间</div>
                  <div style={{ fontSize: 13, color: C.textPrimary }}>{detailModal.createdAt}</div>
                </div>
              </Col>
            </Row>
            <div style={{
              padding: 8, borderRadius: 6, background: `${C.info}08`,
              border: `1px solid ${C.info}20`, fontSize: 12, color: C.info,
            }}>
              {detailModal.priority === 'critical'
                ? '此为紧急操作，建议优先处理。'
                : '此操作经 Agent 分析后推荐，请根据业务判断是否执行。'}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
