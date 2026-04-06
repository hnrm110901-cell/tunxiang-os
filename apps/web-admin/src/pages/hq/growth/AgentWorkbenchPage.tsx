/**
 * AgentWorkbenchPage — 私域复购Agent工作台（核心页面）
 * 路由: /hq/growth/agent-workbench
 * 顶部统计 + 左侧建议列表 + 右侧建议详情 + 底部操作
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Card, Tag, Button, Space, Row, Col, Statistic, List, Spin, Modal, Input, message,
} from 'antd';
import {
  RobotOutlined, CheckCircleOutlined, CloseCircleOutlined,
  SendOutlined, ReloadOutlined, ExclamationCircleOutlined,
} from '@ant-design/icons';
import { txFetch } from '../../../api';
import { reviewSuggestion, publishSuggestion } from '../../../api/growthHubApi';
import type { AgentSuggestion } from '../../../api/growthHubApi';

// ---- 颜色常量 ----
const PAGE_BG = '#0d1e28';
const CARD_BG = '#142833';
const BORDER = '#1e3a4a';
const TEXT_PRIMARY = '#e8e8e8';
const TEXT_SECONDARY = '#8899a6';
const BRAND_ORANGE = '#FF6B35';
const SUCCESS_GREEN = '#52c41a';
const WARNING_ORANGE = '#faad14';
const DANGER_RED = '#ff4d4f';
const INFO_BLUE = '#1890ff';

const PRIORITY_COLORS: Record<string, string> = {
  critical: 'red', high: 'orange', medium: 'blue', low: 'default',
};

const PRIORITY_LABELS: Record<string, string> = {
  critical: '紧急', high: '高', medium: '中', low: '低',
};

const REVIEW_STATE_COLORS: Record<string, string> = {
  pending_review: 'orange',
  approved: 'green',
  rejected: 'red',
  published: 'cyan',
};

const REVIEW_STATE_LABELS: Record<string, string> = {
  pending_review: '待审核',
  approved: '已通过',
  rejected: '已退回',
  published: '已发布',
};

const SUGGESTION_TYPE_LABELS: Record<string, string> = {
  journey_recommendation: '旅程推荐',
  offer_recommendation: '权益推荐',
  channel_recommendation: '渠道推荐',
  reactivation: '沉默激活',
  service_repair: '服务修复',
  upsell: '提频升单',
  cross_sell: '交叉推荐',
};

// ---- 约束校验模拟 ----
function getConstraintStatus(): { margin: boolean; frequency: boolean; experience: boolean } {
  return { margin: true, frequency: true, experience: true };
}

// ---- 组件 ----
export function AgentWorkbenchPage() {
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<AgentSuggestion[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [rejectNote, setRejectNote] = useState('');
  const [rejectModalOpen, setRejectModalOpen] = useState(false);

  const fetchSuggestions = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await txFetch<{ items: AgentSuggestion[]; total: number }>(
        '/api/v1/growth/agent-suggestions?review_state=pending_review&page=1&size=50'
      );
      if (resp.data) {
        setSuggestions(resp.data.items);
        if (resp.data.items.length > 0 && !selectedId) {
          setSelectedId(resp.data.items[0].id);
        }
      }
    } catch (err) {
      console.error('fetch suggestions error', err);
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  useEffect(() => { fetchSuggestions(); }, [fetchSuggestions]);

  const selected = useMemo(
    () => suggestions.find((s) => s.id === selectedId) || null,
    [suggestions, selectedId]
  );

  // 统计数据
  const stats = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10);
    const todayItems = suggestions.filter((s) => s.created_at?.slice(0, 10) === today);
    return {
      todayCount: todayItems.length,
      pendingCount: suggestions.filter((s) => s.review_state === 'pending_review').length,
      publishedCount: suggestions.filter((s) => s.review_state === 'published').length,
      hitCount: 0, // 到店命中需要后端聚合
    };
  }, [suggestions]);

  const constraints = useMemo(() => getConstraintStatus(), []);

  const handleApprove = async () => {
    if (!selected) return;
    setActionLoading(true);
    try {
      await reviewSuggestion(selected.id, {
        review_result: 'approved',
        reviewer_id: 'current_user',
      });
      message.success('已通过审核');
      fetchSuggestions();
    } catch (err) {
      message.error('审核失败');
    } finally {
      setActionLoading(false);
    }
  };

  const handleReject = async () => {
    if (!selected) return;
    setActionLoading(true);
    try {
      await reviewSuggestion(selected.id, {
        review_result: 'rejected',
        reviewer_id: 'current_user',
        reviewer_note: rejectNote,
      });
      message.success('已退回');
      setRejectModalOpen(false);
      setRejectNote('');
      fetchSuggestions();
    } catch (err) {
      message.error('退回失败');
    } finally {
      setActionLoading(false);
    }
  };

  const handlePublish = async () => {
    if (!selected) return;
    setActionLoading(true);
    try {
      await publishSuggestion(selected.id);
      message.success('已发布执行');
      fetchSuggestions();
    } catch (err) {
      message.error('发布失败');
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div style={{ padding: 24, background: PAGE_BG, minHeight: '100vh' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2 style={{ color: TEXT_PRIMARY, margin: 0 }}>
          <RobotOutlined style={{ marginRight: 8 }} />Agent工作台
        </h2>
        <Button
          icon={<ReloadOutlined />}
          onClick={fetchSuggestions}
          style={{ borderColor: BORDER, color: TEXT_SECONDARY }}
        >
          刷新
        </Button>
      </div>

      {/* 顶部统计 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        {[
          { title: '今日建议数', value: stats.todayCount, color: INFO_BLUE },
          { title: '待审核', value: stats.pendingCount, color: WARNING_ORANGE },
          { title: '已发布', value: stats.publishedCount, color: SUCCESS_GREEN },
          { title: '已命中到店', value: stats.hitCount, color: BRAND_ORANGE },
        ].map((item) => (
          <Col span={6} key={item.title}>
            <Card style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}>
              <Statistic
                title={<span style={{ color: TEXT_SECONDARY }}>{item.title}</span>}
                value={item.value}
                valueStyle={{ color: item.color, fontSize: 28 }}
              />
            </Card>
          </Col>
        ))}
      </Row>

      {/* 主从布局 */}
      <Row gutter={16}>
        {/* 左侧建议列表 */}
        <Col span={8}>
          <Card
            title={<span style={{ color: TEXT_PRIMARY }}>建议列表</span>}
            style={{ background: CARD_BG, border: `1px solid ${BORDER}` }}
            styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
            bodyStyle={{ padding: 0, maxHeight: 'calc(100vh - 320px)', overflow: 'auto' }}
          >
            {loading ? (
              <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
            ) : suggestions.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 40, color: TEXT_SECONDARY }}>暂无待处理建议</div>
            ) : (
              <List
                dataSource={suggestions}
                renderItem={(item) => (
                  <List.Item
                    onClick={() => setSelectedId(item.id)}
                    style={{
                      padding: '12px 16px', cursor: 'pointer',
                      background: selectedId === item.id ? 'rgba(255,107,53,0.1)' : 'transparent',
                      borderLeft: selectedId === item.id ? `3px solid ${BRAND_ORANGE}` : '3px solid transparent',
                      borderBottom: `1px solid ${BORDER}`,
                      transition: 'background 0.15s',
                    }}
                  >
                    <div style={{ width: '100%' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                        <Space size={4}>
                          <Tag color={PRIORITY_COLORS[item.priority] || 'default'}>
                            {PRIORITY_LABELS[item.priority] || item.priority}
                          </Tag>
                          <Tag>
                            {SUGGESTION_TYPE_LABELS[item.suggestion_type] || item.suggestion_type}
                          </Tag>
                        </Space>
                      </div>
                      <div style={{ color: TEXT_PRIMARY, fontSize: 13, marginBottom: 4, lineHeight: 1.4 }}>
                        {item.explanation_summary.length > 60
                          ? item.explanation_summary.slice(0, 60) + '...'
                          : item.explanation_summary}
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span style={{ color: TEXT_SECONDARY, fontSize: 11 }}>
                          {item.customer_id?.slice(0, 8) || '全局'}
                        </span>
                        <span style={{ color: TEXT_SECONDARY, fontSize: 11 }}>
                          {item.created_at?.slice(5, 16)?.replace('T', ' ')}
                        </span>
                      </div>
                    </div>
                  </List.Item>
                )}
              />
            )}
          </Card>
        </Col>

        {/* 右侧建议详情 */}
        <Col span={16}>
          {selected ? (
            <Card
              title={
                <Space>
                  <Tag color={PRIORITY_COLORS[selected.priority] || 'default'}>
                    {PRIORITY_LABELS[selected.priority] || selected.priority}
                  </Tag>
                  <Tag>{SUGGESTION_TYPE_LABELS[selected.suggestion_type] || selected.suggestion_type}</Tag>
                  <Tag color={REVIEW_STATE_COLORS[selected.review_state] || 'default'}>
                    {REVIEW_STATE_LABELS[selected.review_state] || selected.review_state}
                  </Tag>
                  {selected.requires_human_review && <Tag color="red">需人工审核</Tag>}
                </Space>
              }
              style={{ background: CARD_BG, border: `1px solid ${BORDER}`, marginBottom: 16 }}
              styles={{ header: { borderBottom: `1px solid ${BORDER}` } }}
            >
              {/* 为什么建议 */}
              <div style={{ marginBottom: 20 }}>
                <div style={{ color: TEXT_SECONDARY, fontSize: 12, marginBottom: 6, fontWeight: 600 }}>
                  为什么建议
                </div>
                <div style={{
                  padding: '12px 16px', borderRadius: 6, background: 'rgba(24,144,255,0.08)',
                  border: `1px solid rgba(24,144,255,0.2)`, color: TEXT_PRIMARY, fontSize: 14, lineHeight: 1.6,
                }}>
                  {selected.explanation_summary}
                </div>
              </div>

              {/* 建议做什么 */}
              <div style={{ marginBottom: 20 }}>
                <div style={{ color: TEXT_SECONDARY, fontSize: 12, marginBottom: 6, fontWeight: 600 }}>
                  建议做什么
                </div>
                <Space wrap>
                  {selected.mechanism_type && (
                    <Card size="small" style={{ background: 'rgba(19,194,194,0.08)', border: `1px solid rgba(19,194,194,0.2)` }}>
                      <div style={{ color: TEXT_SECONDARY, fontSize: 11 }}>机制类型</div>
                      <div style={{ color: TEXT_PRIMARY, fontWeight: 600 }}>{selected.mechanism_type}</div>
                    </Card>
                  )}
                  {selected.recommended_channel && (
                    <Card size="small" style={{ background: 'rgba(24,144,255,0.08)', border: `1px solid rgba(24,144,255,0.2)` }}>
                      <div style={{ color: TEXT_SECONDARY, fontSize: 11 }}>推荐渠道</div>
                      <div style={{ color: TEXT_PRIMARY, fontWeight: 600 }}>{selected.recommended_channel}</div>
                    </Card>
                  )}
                  {selected.recommended_offer_type && (
                    <Card size="small" style={{ background: 'rgba(255,107,53,0.08)', border: `1px solid rgba(255,107,53,0.2)` }}>
                      <div style={{ color: TEXT_SECONDARY, fontSize: 11 }}>推荐权益</div>
                      <div style={{ color: TEXT_PRIMARY, fontWeight: 600 }}>{selected.recommended_offer_type}</div>
                    </Card>
                  )}
                </Space>
              </div>

              {/* 风险是什么 */}
              {selected.risk_summary && (
                <div style={{ marginBottom: 20 }}>
                  <div style={{ color: TEXT_SECONDARY, fontSize: 12, marginBottom: 6, fontWeight: 600 }}>
                    风险是什么
                  </div>
                  <div style={{
                    padding: '12px 16px', borderRadius: 6, background: 'rgba(255,77,79,0.08)',
                    border: `1px solid rgba(255,77,79,0.2)`, color: WARNING_ORANGE, fontSize: 13, lineHeight: 1.5,
                  }}>
                    <ExclamationCircleOutlined style={{ marginRight: 6 }} />
                    {selected.risk_summary}
                  </div>
                </div>
              )}

              {/* 预计结果 */}
              {selected.expected_outcome_json && Object.keys(selected.expected_outcome_json).length > 0 && (
                <div style={{ marginBottom: 20 }}>
                  <div style={{ color: TEXT_SECONDARY, fontSize: 12, marginBottom: 6, fontWeight: 600 }}>
                    预计结果
                  </div>
                  <Row gutter={12}>
                    {Object.entries(selected.expected_outcome_json).map(([key, val]) => (
                      <Col span={8} key={key}>
                        <Card size="small" style={{ background: 'rgba(82,196,26,0.08)', border: `1px solid rgba(82,196,26,0.2)`, textAlign: 'center' }}>
                          <div style={{ color: TEXT_SECONDARY, fontSize: 11 }}>{key}</div>
                          <div style={{ color: SUCCESS_GREEN, fontSize: 20, fontWeight: 700 }}>
                            {typeof val === 'number' && val < 1 ? `${(val * 100).toFixed(1)}%` : val}
                          </div>
                        </Card>
                      </Col>
                    ))}
                  </Row>
                </div>
              )}

              {/* 约束校验 */}
              <div style={{ marginBottom: 20 }}>
                <div style={{ color: TEXT_SECONDARY, fontSize: 12, marginBottom: 6, fontWeight: 600 }}>
                  约束校验
                </div>
                <Space>
                  <Tag color={constraints.margin ? 'green' : 'red'} icon={constraints.margin ? <CheckCircleOutlined /> : <CloseCircleOutlined />}>
                    毛利底线
                  </Tag>
                  <Tag color={constraints.frequency ? 'green' : 'red'} icon={constraints.frequency ? <CheckCircleOutlined /> : <CloseCircleOutlined />}>
                    频控检查
                  </Tag>
                  <Tag color={constraints.experience ? 'green' : 'red'} icon={constraints.experience ? <CheckCircleOutlined /> : <CloseCircleOutlined />}>
                    客户体验
                  </Tag>
                </Space>
              </div>

              {/* Agent来源 */}
              {selected.created_by_agent && (
                <div style={{ color: TEXT_SECONDARY, fontSize: 12 }}>
                  来源Agent: <Tag>{selected.created_by_agent}</Tag>
                  创建时间: {selected.created_at?.slice(0, 16)?.replace('T', ' ')}
                </div>
              )}
            </Card>
          ) : (
            <Card style={{ background: CARD_BG, border: `1px solid ${BORDER}`, textAlign: 'center', padding: 80 }}>
              <RobotOutlined style={{ fontSize: 48, color: TEXT_SECONDARY, marginBottom: 16 }} />
              <div style={{ color: TEXT_SECONDARY, fontSize: 14 }}>从左侧选择一条建议查看详情</div>
            </Card>
          )}

          {/* 底部操作按钮 */}
          {selected && selected.review_state === 'pending_review' && (
            <Card style={{ background: CARD_BG, border: `1px solid ${BORDER}` }} bodyStyle={{ padding: '12px 16px' }}>
              <Space>
                <Button
                  type="primary"
                  icon={<CheckCircleOutlined />}
                  loading={actionLoading}
                  onClick={handleApprove}
                  style={{ background: SUCCESS_GREEN, borderColor: SUCCESS_GREEN }}
                >
                  采纳并审核通过
                </Button>
                <Button
                  danger
                  icon={<CloseCircleOutlined />}
                  onClick={() => setRejectModalOpen(true)}
                >
                  退回
                </Button>
                <Button
                  type="primary"
                  icon={<SendOutlined />}
                  loading={actionLoading}
                  onClick={handlePublish}
                  style={{ background: BRAND_ORANGE, borderColor: BRAND_ORANGE }}
                >
                  直接发布执行
                </Button>
              </Space>
            </Card>
          )}
        </Col>
      </Row>

      {/* 退回原因弹窗 */}
      <Modal
        title="退回建议"
        open={rejectModalOpen}
        onOk={handleReject}
        onCancel={() => { setRejectModalOpen(false); setRejectNote(''); }}
        confirmLoading={actionLoading}
        okText="确认退回"
        cancelText="取消"
      >
        <div style={{ marginBottom: 8, color: TEXT_SECONDARY }}>请输入退回原因:</div>
        <Input.TextArea
          rows={3}
          value={rejectNote}
          onChange={(e) => setRejectNote(e.target.value)}
          placeholder="退回原因..."
        />
      </Modal>
    </div>
  );
}
