/**
 * LeaveApprovalBoard — 请假审批看板
 * 域F · 组织人事 · 请假管理
 *
 * 功能：
 *  1. 看板视图（三列：待审批/已通过/已拒绝）
 *  2. 每张卡片：员工名/请假类型/日期/时长
 *  3. 拖拽审批（拖到已通过列=通过，拖到已拒绝列=拒绝）
 *  4. 或点击卡片弹出审批ModalForm
 *
 * API:
 *  GET  /api/v1/leave-requests?status=pending
 *  GET  /api/v1/leave-requests?status=approved
 *  GET  /api/v1/leave-requests?status=rejected
 *  POST /api/v1/leave-requests/{id}/approve
 *  POST /api/v1/leave-requests/{id}/reject
 */

import { useEffect, useState, useCallback, DragEvent } from 'react';
import {
  Card,
  Col,
  Empty,
  message,
  Row,
  Select,
  Space,
  Tag,
  Typography,
  Badge,
  Button,
} from 'antd';
import {
  ModalForm,
  ProFormTextArea,
} from '@ant-design/pro-components';
import {
  CalendarOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { txFetch } from '../../../api';

const { Title, Text } = Typography;
const TX_PRIMARY = '#FF6B35';
const TX_SUCCESS = '#0F6E56';
const TX_DANGER  = '#A32D2D';
const TX_WARNING = '#BA7517';

// ─── Types ───────────────────────────────────────────────────────────────────

interface LeaveCard {
  id: string;
  employee_id: string;
  employee_name: string;
  leave_type: string;
  leave_type_label: string;
  start_time: string;
  end_time: string;
  duration_hours: number;
  reason: string;
  status: 'pending' | 'approved' | 'rejected';
}

// ─── 看板列配置 ──────────────────────────────────────────────────────────────

const BOARD_COLUMNS = [
  {
    key: 'pending',
    title: '待审批',
    icon: <ClockCircleOutlined />,
    color: TX_WARNING,
    badgeStatus: 'warning' as const,
  },
  {
    key: 'approved',
    title: '已通过',
    icon: <CheckCircleOutlined />,
    color: TX_SUCCESS,
    badgeStatus: 'success' as const,
  },
  {
    key: 'rejected',
    title: '已拒绝',
    icon: <CloseCircleOutlined />,
    color: TX_DANGER,
    badgeStatus: 'error' as const,
  },
];

// ─── 请假类型颜色 ────────────────────────────────────────────────────────────

const LEAVE_TYPE_COLOR: Record<string, string> = {
  annual: 'blue',
  personal: 'default',
  sick: 'orange',
  compensatory: 'cyan',
  maternity: 'purple',
  other: 'default',
};

// ─── 看板卡片子组件 ──────────────────────────────────────────────────────────

function BoardCard({
  card,
  onDragStart,
  onClick,
}: {
  card: LeaveCard;
  onDragStart: (e: DragEvent<HTMLDivElement>, card: LeaveCard) => void;
  onClick: (card: LeaveCard) => void;
}) {
  return (
    <Card
      size="small"
      hoverable
      draggable
      onDragStart={(e) => onDragStart(e, card)}
      onClick={() => onClick(card)}
      style={{ marginBottom: 8, cursor: 'grab' }}
      bodyStyle={{ padding: 12 }}
    >
      <div style={{ marginBottom: 4 }}>
        <Text strong>{card.employee_name}</Text>
        <Tag
          color={LEAVE_TYPE_COLOR[card.leave_type] ?? 'default'}
          style={{ marginLeft: 8, fontSize: 11 }}
        >
          {card.leave_type_label}
        </Tag>
      </div>
      <div style={{ fontSize: 12, color: '#666' }}>
        {card.start_time} ~ {card.end_time}
      </div>
      <div style={{ fontSize: 12, color: '#666', marginTop: 2 }}>
        时长：{card.duration_hours.toFixed(1)}h
      </div>
    </Card>
  );
}

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export default function LeaveApprovalBoard() {
  const [storeId, setStoreId] = useState<string>('');
  const [stores, setStores] = useState<{ store_id: string; store_name: string }[]>([]);
  const [boardData, setBoardData] = useState<Record<string, LeaveCard[]>>({
    pending: [],
    approved: [],
    rejected: [],
  });
  const [loading, setLoading] = useState(false);
  const [actionTarget, setActionTarget] = useState<LeaveCard | null>(null);
  const [dragOverCol, setDragOverCol] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await txFetch<{ store_id: string; store_name: string }[]>('/api/v1/org/stores');
        const list = res.data ?? [];
        setStores(list);
        if (list.length > 0) setStoreId(list[0].store_id);
      } catch {
        message.error('加载门店列表失败');
      }
    })();
  }, []);

  const loadBoard = useCallback(async () => {
    if (!storeId) return;
    setLoading(true);
    try {
      const [pendingRes, approvedRes, rejectedRes] = await Promise.all([
        txFetch<{ items: LeaveCard[] }>(`/api/v1/leave-requests?store_id=${storeId}&status=pending&size=50`),
        txFetch<{ items: LeaveCard[] }>(`/api/v1/leave-requests?store_id=${storeId}&status=approved&size=50`),
        txFetch<{ items: LeaveCard[] }>(`/api/v1/leave-requests?store_id=${storeId}&status=rejected&size=50`),
      ]);
      setBoardData({
        pending: pendingRes.data?.items ?? [],
        approved: approvedRes.data?.items ?? [],
        rejected: rejectedRes.data?.items ?? [],
      });
    } catch {
      message.error('加载看板数据失败');
    } finally {
      setLoading(false);
    }
  }, [storeId]);

  useEffect(() => {
    loadBoard();
  }, [loadBoard]);

  // 拖拽处理
  const handleDragStart = (e: DragEvent<HTMLDivElement>, card: LeaveCard) => {
    e.dataTransfer.setData('text/plain', card.id);
  };

  const handleDragOver = (e: DragEvent<HTMLDivElement>, colKey: string) => {
    e.preventDefault();
    setDragOverCol(colKey);
  };

  const handleDragLeave = () => {
    setDragOverCol(null);
  };

  const handleDrop = async (e: DragEvent<HTMLDivElement>, targetCol: string) => {
    e.preventDefault();
    setDragOverCol(null);
    const cardId = e.dataTransfer.getData('text/plain');

    // 只能从pending拖到approved或rejected
    const card = boardData.pending.find((c) => c.id === cardId);
    if (!card) return;

    if (targetCol === 'approved') {
      try {
        await txFetch(`/api/v1/leave-requests/${cardId}/approve`, {
          method: 'POST',
          body: JSON.stringify({ comment: '看板拖拽审批通过' }),
        });
        message.success(`${card.employee_name} 的请假已通过`);
        loadBoard();
      } catch {
        message.error('审批失败');
      }
    } else if (targetCol === 'rejected') {
      try {
        await txFetch(`/api/v1/leave-requests/${cardId}/reject`, {
          method: 'POST',
          body: JSON.stringify({ comment: '看板拖拽拒绝' }),
        });
        message.success(`${card.employee_name} 的请假已拒绝`);
        loadBoard();
      } catch {
        message.error('拒绝失败');
      }
    }
  };

  // 点击卡片弹窗审批
  const handleCardClick = (card: LeaveCard) => {
    if (card.status === 'pending') {
      setActionTarget(card);
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <CalendarOutlined style={{ color: TX_PRIMARY, marginRight: 8 }} />
            请假审批看板
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
            <Button icon={<ReloadOutlined />} onClick={loadBoard} loading={loading}>
              刷新
            </Button>
          </Space>
        </Col>
      </Row>

      <Row gutter={16}>
        {BOARD_COLUMNS.map((col) => (
          <Col span={8} key={col.key}>
            <Card
              title={
                <Space>
                  {col.icon}
                  <Badge
                    count={boardData[col.key]?.length ?? 0}
                    size="small"
                    style={{ backgroundColor: col.color }}
                  >
                    <span style={{ paddingRight: 12 }}>{col.title}</span>
                  </Badge>
                </Space>
              }
              style={{
                minHeight: 500,
                border: dragOverCol === col.key ? `2px dashed ${col.color}` : undefined,
                background: dragOverCol === col.key ? '#FAFAFA' : undefined,
              }}
              bodyStyle={{ padding: 12 }}
              onDragOver={(e) => handleDragOver(e, col.key)}
              onDragLeave={handleDragLeave}
              onDrop={(e) => handleDrop(e, col.key)}
            >
              {(boardData[col.key] ?? []).length === 0 ? (
                <Empty description="暂无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              ) : (
                (boardData[col.key] ?? []).map((card) => (
                  <BoardCard
                    key={card.id}
                    card={card}
                    onDragStart={handleDragStart}
                    onClick={handleCardClick}
                  />
                ))
              )}
            </Card>
          </Col>
        ))}
      </Row>

      {/* 审批弹窗 */}
      <ModalForm
        title={`审批 — ${actionTarget?.employee_name} · ${actionTarget?.leave_type_label}`}
        open={!!actionTarget}
        onOpenChange={(open) => {
          if (!open) setActionTarget(null);
        }}
        submitter={{
          render: (_, dom) => [
            <Button key="reject" danger onClick={async () => {
              if (!actionTarget) return;
              try {
                await txFetch(`/api/v1/leave-requests/${actionTarget.id}/reject`, {
                  method: 'POST',
                  body: JSON.stringify({ comment: '' }),
                });
                message.success('已拒绝');
                setActionTarget(null);
                loadBoard();
              } catch {
                message.error('拒绝失败');
              }
            }}>
              拒绝
            </Button>,
            ...dom,
          ],
        }}
        onFinish={async (values) => {
          if (!actionTarget) return false;
          try {
            await txFetch(`/api/v1/leave-requests/${actionTarget.id}/approve`, {
              method: 'POST',
              body: JSON.stringify({ comment: values.comment }),
            });
            message.success('审批通过');
            setActionTarget(null);
            loadBoard();
            return true;
          } catch {
            message.error('审批失败');
            return false;
          }
        }}
        width={420}
      >
        <Card size="small" style={{ marginBottom: 16, background: '#FAFAFA' }}>
          <div><Text type="secondary">员工：</Text>{actionTarget?.employee_name}</div>
          <div><Text type="secondary">类型：</Text>{actionTarget?.leave_type_label}</div>
          <div><Text type="secondary">时间：</Text>{actionTarget?.start_time} ~ {actionTarget?.end_time}</div>
          <div><Text type="secondary">时长：</Text>{actionTarget?.duration_hours.toFixed(1)}h</div>
        </Card>
        <ProFormTextArea name="comment" label="审批意见" placeholder="可选填写审批意见" />
      </ModalForm>
    </div>
  );
}
