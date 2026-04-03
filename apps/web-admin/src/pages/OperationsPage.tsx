/**
 * OperationsPage — 运营总览
 * 当日运营节点状态 / 异常数 / 待审批数 / 快速导航
 */

import React, { useEffect, useState, useCallback } from 'react';
import { txFetch } from '../api';

// ─── 类型定义 ───

interface OpsNode {
  code: string;
  name: string;
  scheduled_time: string;
  actual_time: string | null;
  status: 'completed' | 'in_progress' | 'pending' | 'skipped' | 'overdue';
  operator?: string;
  note?: string;
}

interface DailyReviewStatus {
  date: string;
  store_id: string;
  store_name: string;
  overall_status: 'on_track' | 'delayed' | 'at_risk' | 'completed';
  progress_pct: number;
  nodes: OpsNode[];
}

interface AlertCount {
  total: number;
  critical: number;
  warning: number;
  info: number;
}

interface ApprovalCount {
  pending: number;
  urgent: number;
}

// ─── 样式 ───

const containerStyle: React.CSSProperties = {
  backgroundColor: '#0d1e28',
  color: '#E0E0E0',
  minHeight: '100vh',
  padding: '24px 32px',
  fontFamily: 'system-ui, -apple-system, sans-serif',
};

const headerStyle: React.CSSProperties = {
  fontSize: '24px',
  fontWeight: 700,
  color: '#FFFFFF',
  marginBottom: '4px',
};

const subtitleStyle: React.CSSProperties = {
  fontSize: '13px',
  color: '#8899A6',
  marginBottom: '24px',
};

const summaryRowStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(3, 1fr)',
  gap: '16px',
  marginBottom: '24px',
};

const summaryCardStyle: React.CSSProperties = {
  backgroundColor: '#1a2a33',
  borderRadius: '12px',
  padding: '20px',
  border: '1px solid #1E3A47',
};

const mainGridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '1fr 320px',
  gap: '20px',
};

const cardStyle: React.CSSProperties = {
  backgroundColor: '#1a2a33',
  borderRadius: '12px',
  padding: '20px',
  border: '1px solid #1E3A47',
};

const cardTitleStyle: React.CSSProperties = {
  fontSize: '15px',
  fontWeight: 600,
  color: '#4FC3F7',
  marginBottom: '16px',
};

const nodeRowStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'flex-start',
  gap: '12px',
  padding: '10px 0',
  borderBottom: '1px solid #1E3A47',
  fontSize: '13px',
};

const loadingStyle: React.CSSProperties = {
  color: '#8899A6',
  fontSize: '13px',
  padding: '20px 0',
  textAlign: 'center',
};

const errorStyle: React.CSSProperties = {
  color: '#EF5350',
  fontSize: '13px',
  padding: '12px',
  backgroundColor: 'rgba(239,83,80,0.08)',
  borderRadius: '8px',
  marginBottom: '12px',
};

const navBtnStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  width: '100%',
  backgroundColor: '#0d1e28',
  border: '1px solid #1E3A47',
  color: '#E0E0E0',
  padding: '11px 14px',
  borderRadius: '8px',
  cursor: 'pointer',
  fontSize: '13px',
  marginBottom: '8px',
  textAlign: 'left',
};

// ─── 工具函数 ───

function nodeStatusColor(status: OpsNode['status']): string {
  switch (status) {
    case 'completed': return '#66BB6A';
    case 'in_progress': return '#4FC3F7';
    case 'overdue': return '#EF5350';
    case 'skipped': return '#8899A6';
    default: return '#8899A6';
  }
}

function nodeStatusLabel(status: OpsNode['status']): string {
  const map: Record<string, string> = {
    completed: '已完成',
    in_progress: '进行中',
    pending: '待执行',
    skipped: '已跳过',
    overdue: '已逾期',
  };
  return map[status] ?? status;
}

function overallStatusLabel(status: DailyReviewStatus['overall_status']): string {
  const map: Record<string, string> = {
    on_track: '正常推进',
    delayed: '有所延误',
    at_risk: '存在风险',
    completed: '全部完成',
  };
  return map[status] ?? status;
}

function overallStatusColor(status: DailyReviewStatus['overall_status']): string {
  switch (status) {
    case 'on_track': return '#4FC3F7';
    case 'completed': return '#66BB6A';
    case 'delayed': return '#FFA726';
    case 'at_risk': return '#EF5350';
    default: return '#8899A6';
  }
}

// ─── 运营节点时间线 ───

function NodeDot({ status }: { status: OpsNode['status'] }) {
  const color = nodeStatusColor(status);
  const isActive = status === 'in_progress';
  return (
    <div
      style={{
        width: '12px',
        height: '12px',
        borderRadius: '50%',
        backgroundColor: color,
        flexShrink: 0,
        marginTop: '2px',
        boxShadow: isActive ? `0 0 6px ${color}` : 'none',
      }}
    />
  );
}

// ─── 主组件 ───

export function OperationsPage() {
  const [review, setReview] = useState<DailyReviewStatus | null>(null);
  const [reviewLoading, setReviewLoading] = useState(true);
  const [reviewError, setReviewError] = useState<string | null>(null);

  const [alertCount, setAlertCount] = useState<AlertCount | null>(null);
  const [alertLoading, setAlertLoading] = useState(true);

  const [approvalCount, setApprovalCount] = useState<ApprovalCount | null>(null);
  const [approvalLoading, setApprovalLoading] = useState(true);

  const loadAll = useCallback(async () => {
    // 当日运营节点状态
    setReviewLoading(true);
    setReviewError(null);
    try {
      const data = await txFetch<DailyReviewStatus>('/api/v1/ops/daily-review/status');
      setReview(data);
    } catch (e) {
      setReviewError(e instanceof Error ? e.message : '运营状态加载失败');
    } finally {
      setReviewLoading(false);
    }

    // 异常数
    setAlertLoading(true);
    try {
      const data = await txFetch<AlertCount>('/api/v1/ops/alerts/count');
      setAlertCount(data);
    } catch {
      setAlertCount(null);
    } finally {
      setAlertLoading(false);
    }

    // 待审批数
    setApprovalLoading(true);
    try {
      const data = await txFetch<ApprovalCount>('/api/v1/ops/approvals/count?status=pending');
      setApprovalCount(data);
    } catch {
      setApprovalCount(null);
    } finally {
      setApprovalLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  // 统计节点进度
  const completedNodes = review?.nodes.filter((n) => n.status === 'completed').length ?? 0;
  const totalNodes = review?.nodes.length ?? 0;

  return (
    <div style={containerStyle}>
      <h1 style={headerStyle}>运营总览</h1>
      <p style={subtitleStyle}>
        {new Date().toLocaleDateString('zh-CN', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}
        {review && ` · ${review.store_name}`}
      </p>

      {/* 汇总卡片 */}
      <div style={summaryRowStyle}>
        {/* 运营进度 */}
        <div style={summaryCardStyle}>
          <div style={{ fontSize: '12px', color: '#8899A6', marginBottom: '8px' }}>今日运营进度</div>
          {reviewLoading ? (
            <div style={{ ...loadingStyle, padding: '4px 0' }}>加载中...</div>
          ) : review ? (
            <>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px', marginBottom: '8px' }}>
                <span style={{ fontSize: '28px', fontWeight: 700, color: overallStatusColor(review.overall_status) }}>
                  {review.progress_pct}%
                </span>
                <span style={{ fontSize: '13px', color: '#8899A6' }}>
                  {completedNodes}/{totalNodes} 节点
                </span>
              </div>
              <div style={{ width: '100%', height: '6px', backgroundColor: '#1E3A47', borderRadius: '3px' }}>
                <div
                  style={{
                    width: `${review.progress_pct}%`,
                    height: '100%',
                    backgroundColor: overallStatusColor(review.overall_status),
                    borderRadius: '3px',
                    transition: 'width 0.6s ease',
                  }}
                />
              </div>
              <div style={{ marginTop: '8px', fontSize: '12px', color: overallStatusColor(review.overall_status) }}>
                {overallStatusLabel(review.overall_status)}
              </div>
            </>
          ) : (
            <div style={{ color: '#EF5350', fontSize: '13px' }}>数据不可用</div>
          )}
        </div>

        {/* 异常预警 */}
        <div style={summaryCardStyle}>
          <div style={{ fontSize: '12px', color: '#8899A6', marginBottom: '8px' }}>当前异常预警</div>
          {alertLoading ? (
            <div style={{ ...loadingStyle, padding: '4px 0' }}>加载中...</div>
          ) : alertCount ? (
            <>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px', marginBottom: '10px' }}>
                <span style={{ fontSize: '28px', fontWeight: 700, color: alertCount.total > 0 ? '#EF5350' : '#66BB6A' }}>
                  {alertCount.total}
                </span>
                <span style={{ fontSize: '13px', color: '#8899A6' }}>条异常</span>
              </div>
              <div style={{ display: 'flex', gap: '12px', fontSize: '12px' }}>
                <span style={{ color: '#EF5350' }}>严重 {alertCount.critical}</span>
                <span style={{ color: '#FFA726' }}>警告 {alertCount.warning}</span>
                <span style={{ color: '#4FC3F7' }}>提示 {alertCount.info}</span>
              </div>
            </>
          ) : (
            <div style={{ color: '#8899A6', fontSize: '13px' }}>暂无数据</div>
          )}
        </div>

        {/* 待审批 */}
        <div style={summaryCardStyle}>
          <div style={{ fontSize: '12px', color: '#8899A6', marginBottom: '8px' }}>待我审批</div>
          {approvalLoading ? (
            <div style={{ ...loadingStyle, padding: '4px 0' }}>加载中...</div>
          ) : approvalCount ? (
            <>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px', marginBottom: '10px' }}>
                <span style={{ fontSize: '28px', fontWeight: 700, color: approvalCount.pending > 0 ? '#FFA726' : '#66BB6A' }}>
                  {approvalCount.pending}
                </span>
                <span style={{ fontSize: '13px', color: '#8899A6' }}>待审批</span>
              </div>
              {approvalCount.urgent > 0 && (
                <div style={{ fontSize: '12px', color: '#EF5350' }}>
                  其中 {approvalCount.urgent} 条紧急
                </div>
              )}
              {approvalCount.pending === 0 && (
                <div style={{ fontSize: '12px', color: '#66BB6A' }}>全部处理完毕</div>
              )}
            </>
          ) : (
            <div style={{ color: '#8899A6', fontSize: '13px' }}>暂无数据</div>
          )}
        </div>
      </div>

      {/* 主体：时间轴 + 快速导航 */}
      <div style={mainGridStyle}>
        {/* 运营节点时间轴 */}
        <div style={cardStyle}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <div style={cardTitleStyle}>今日运营节点</div>
            {review && (
              <span
                style={{
                  fontSize: '12px',
                  color: overallStatusColor(review.overall_status),
                  backgroundColor: `${overallStatusColor(review.overall_status)}18`,
                  padding: '3px 10px',
                  borderRadius: '12px',
                }}
              >
                {overallStatusLabel(review.overall_status)}
              </span>
            )}
          </div>

          {reviewError && <div style={errorStyle}>{reviewError}</div>}

          {reviewLoading ? (
            <div style={loadingStyle}>加载节点数据...</div>
          ) : !review || review.nodes.length === 0 ? (
            <div style={loadingStyle}>今日暂无运营节点记录</div>
          ) : (
            review.nodes.map((node) => (
              <div key={node.code} style={nodeRowStyle}>
                <NodeDot status={node.status} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '2px' }}>
                    <span style={{ color: '#4FC3F7', fontWeight: 600, fontSize: '12px', width: '30px' }}>
                      {node.code}
                    </span>
                    <span style={{ fontWeight: 500 }}>{node.name}</span>
                    {node.status === 'in_progress' && (
                      <span
                        style={{
                          fontSize: '11px',
                          backgroundColor: 'rgba(79,195,247,0.15)',
                          color: '#4FC3F7',
                          padding: '1px 6px',
                          borderRadius: '4px',
                        }}
                      >
                        进行中
                      </span>
                    )}
                  </div>
                  {node.note && (
                    <div style={{ fontSize: '12px', color: '#8899A6', marginLeft: '38px' }}>
                      {node.note}
                    </div>
                  )}
                </div>
                <div style={{ textAlign: 'right', flexShrink: 0 }}>
                  <div style={{ color: '#8899A6', fontSize: '12px' }}>
                    计划 {node.scheduled_time}
                  </div>
                  {node.actual_time && (
                    <div style={{ color: '#E0E0E0', fontSize: '12px' }}>
                      实际 {node.actual_time}
                    </div>
                  )}
                </div>
                <span
                  style={{
                    fontSize: '12px',
                    color: nodeStatusColor(node.status),
                    backgroundColor: `${nodeStatusColor(node.status)}18`,
                    padding: '2px 8px',
                    borderRadius: '4px',
                    flexShrink: 0,
                    width: '56px',
                    textAlign: 'center',
                  }}
                >
                  {nodeStatusLabel(node.status)}
                </span>
              </div>
            ))
          )}
        </div>

        {/* 快速导航 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={cardStyle}>
            <div style={cardTitleStyle}>快速导航</div>
            {[
              { label: '交易管理', desc: '订单 / 支付 / 日结', path: '/trade', color: '#66BB6A' },
              { label: '门店巡检', desc: '门店健康 / 设备状态', path: '/store-health', color: '#4FC3F7' },
              { label: '审批中心', desc: `${approvalCount?.pending ?? '—'} 条待处理`, path: '/approvals', color: '#FFA726' },
              { label: '异常预警', desc: `${alertCount?.total ?? '—'} 条活跃告警`, path: '/alerts', color: '#EF5350' },
              { label: '财务报表', desc: '日结 / 月报 / 对账', path: '/finance', color: '#CE93D8' },
              { label: '供应链', desc: '库存 / 采购 / 验收', path: '/supply', color: '#80DEEA' },
            ].map((item) => (
              <button
                key={item.path}
                style={navBtnStyle}
                onClick={() => {
                  // 导航到子模块（由路由接管）
                  window.location.hash = item.path;
                }}
              >
                <div>
                  <div style={{ fontWeight: 500, marginBottom: '2px', color: '#E0E0E0' }}>
                    {item.label}
                  </div>
                  <div style={{ fontSize: '11px', color: '#8899A6' }}>{item.desc}</div>
                </div>
                <span style={{ color: item.color, fontSize: '16px' }}>›</span>
              </button>
            ))}
          </div>

          {/* 刷新按钮 */}
          <button
            onClick={loadAll}
            style={{
              backgroundColor: '#1E3A47',
              border: '1px solid #2a4a5a',
              color: '#4FC3F7',
              padding: '10px 20px',
              borderRadius: '8px',
              cursor: 'pointer',
              fontSize: '13px',
              width: '100%',
            }}
          >
            刷新运营数据
          </button>
        </div>
      </div>
    </div>
  );
}
