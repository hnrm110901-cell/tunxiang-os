/**
 * StoreOpsFillGaps — 缺岗补位台
 * 域F · 组织人事 · 门店作战台
 *
 * 功能：
 *  1. 左侧：当前缺岗列表（ProTable，筛选urgency/position/status）
 *  2. 右侧：选中缺岗后展示候选人（卡片列表，姓名/技能/匹配度/当前状态）
 *  3. 点击候选人弹出ModalForm确认补位（fill_type选择）
 *
 * API:
 *  GET  /api/v1/store-ops/fill-suggestions?gap_id=xxx
 *  POST /api/v1/store-ops/fill-gap
 */

import { useEffect, useState } from 'react';
import {
  Avatar,
  Button,
  Card,
  Col,
  Empty,
  message,
  Progress,
  Row,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd';
import {
  ModalForm,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProTable,
} from '@ant-design/pro-components';
import type { ProColumns } from '@ant-design/pro-components';
import { UserOutlined, SwapOutlined } from '@ant-design/icons';
import { txFetchData } from '../../../api';

const { Title, Text } = Typography;

// ─── Design Token ────────────────────────────────────────────────────────────
const TX_PRIMARY = '#FF6B35';
const TX_SUCCESS = '#0F6E56';
const TX_DANGER  = '#A32D2D';

// ─── Types ───────────────────────────────────────────────────────────────────

interface GapItem {
  id: string;
  position: string;
  position_label: string;
  time_slot: string;
  urgency: 'high' | 'medium' | 'low';
  status: 'open' | 'filling' | 'filled';
  store_id: string;
  store_name: string;
}

interface Candidate {
  employee_id: string;
  employee_name: string;
  avatar_url?: string;
  skills: string[];
  match_score: number;
  current_status: string;
  store_name: string;
}

// ─── 枚举 ────────────────────────────────────────────────────────────────────

const URGENCY_MAP: Record<string, { label: string; color: string }> = {
  high:   { label: '紧急', color: 'red' },
  medium: { label: '一般', color: 'orange' },
  low:    { label: '低',   color: 'blue' },
};

const GAP_STATUS_MAP: Record<string, { label: string; color: string }> = {
  open:    { label: '待补位', color: 'red' },
  filling: { label: '补位中', color: 'orange' },
  filled:  { label: '已补位', color: 'green' },
};

const FILL_TYPE_OPTIONS = [
  { label: '内部调岗', value: 'internal_transfer' },
  { label: '跨店借调', value: 'cross_store' },
  { label: '临时加班', value: 'overtime' },
];

// ─── 候选人卡片子组件 ────────────────────────────────────────────────────────

function CandidateCard({
  candidate,
  onSelect,
}: {
  candidate: Candidate;
  onSelect: (c: Candidate) => void;
}) {
  return (
    <Card
      hoverable
      size="small"
      style={{ marginBottom: 12 }}
      onClick={() => onSelect(candidate)}
    >
      <Row align="middle" gutter={12}>
        <Col>
          <Avatar icon={<UserOutlined />} src={candidate.avatar_url} size={40} />
        </Col>
        <Col flex="auto">
          <div>
            <Text strong>{candidate.employee_name}</Text>
            <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
              {candidate.store_name}
            </Text>
          </div>
          <div style={{ marginTop: 4 }}>
            {candidate.skills.map((s) => (
              <Tag key={s} style={{ fontSize: 11 }}>
                {s}
              </Tag>
            ))}
          </div>
          <div style={{ marginTop: 4 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              状态：{candidate.current_status}
            </Text>
          </div>
        </Col>
        <Col>
          <Progress
            type="circle"
            percent={Math.round(candidate.match_score * 100)}
            size={48}
            strokeColor={candidate.match_score > 0.8 ? TX_SUCCESS : TX_PRIMARY}
            format={(p) => `${p}%`}
          />
        </Col>
      </Row>
    </Card>
  );
}

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export default function StoreOpsFillGaps() {
  const [storeId, setStoreId] = useState<string>('');
  const [stores, setStores] = useState<{ store_id: string; store_name: string }[]>([]);
  const [selectedGap, setSelectedGap] = useState<GapItem | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [candidatesLoading, setCandidatesLoading] = useState(false);
  const [fillTarget, setFillTarget] = useState<Candidate | null>(null);

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

  // 选中缺岗后加载候选人
  const loadCandidates = async (gapId: string) => {
    setCandidatesLoading(true);
    try {
      const res = await txFetchData<Candidate[]>(
        `/api/v1/store-ops/fill-suggestions?gap_id=${gapId}`,
      );
      setCandidates(res ?? []);
    } catch {
      message.error('加载候选人失败');
    } finally {
      setCandidatesLoading(false);
    }
  };

  const handleGapSelect = (gap: GapItem) => {
    setSelectedGap(gap);
    loadCandidates(gap.id);
  };

  // 提交补位
  const handleFillGap = async (values: Record<string, unknown>) => {
    if (!selectedGap || !fillTarget) return false;
    try {
      await txFetchData('/api/v1/store-ops/fill-gap', {
        method: 'POST',
        body: JSON.stringify({
          gap_id: selectedGap.id,
          employee_id: fillTarget.employee_id,
          fill_type: values.fill_type,
          remark: values.remark,
        }),
      });
      message.success('补位成功');
      setFillTarget(null);
      loadCandidates(selectedGap.id);
      return true;
    } catch {
      message.error('补位失败');
      return false;
    }
  };

  const gapColumns: ProColumns<GapItem>[] = [
    { title: '岗位', dataIndex: 'position_label', width: 90 },
    { title: '时段', dataIndex: 'time_slot', width: 110 },
    {
      title: '紧急程度',
      dataIndex: 'urgency',
      width: 90,
      valueEnum: {
        high:   { text: '紧急', status: 'Error' },
        medium: { text: '一般', status: 'Warning' },
        low:    { text: '低',   status: 'Processing' },
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 80,
      render: (_, r) => {
        const s = GAP_STATUS_MAP[r.status];
        return <Tag color={s?.color}>{s?.label}</Tag>;
      },
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <SwapOutlined style={{ color: TX_PRIMARY, marginRight: 8 }} />
            缺岗补位台
          </Title>
        </Col>
        <Col>
          <Select
            value={storeId}
            onChange={setStoreId}
            style={{ width: 200 }}
            placeholder="选择门店"
            options={stores.map((s) => ({ label: s.store_name, value: s.store_id }))}
          />
        </Col>
      </Row>

      <Row gutter={16}>
        {/* 左侧：缺岗列表 */}
        <Col span={12}>
          <Card title="当前缺岗">
            <ProTable<GapItem>
              columns={gapColumns}
              request={async (params) => {
                const query = new URLSearchParams({
                  store_id: storeId,
                  ...(params.urgency ? { urgency: params.urgency } : {}),
                  ...(params.status ? { status: params.status } : {}),
                });
                const res = await txFetchData<{ items: GapItem[]; total: number }>(
                  `/api/v1/store-ops/gaps?${query.toString()}`,
                );
                return { data: res?.items ?? [], total: res?.total ?? 0, success: true };
              }}
              rowKey="id"
              search={{ labelWidth: 'auto' }}
              options={false}
              pagination={{ pageSize: 10 }}
              size="small"
              onRow={(record) => ({
                onClick: () => handleGapSelect(record),
                style: {
                  cursor: 'pointer',
                  background: selectedGap?.id === record.id ? '#FFF7F0' : undefined,
                },
              })}
            />
          </Card>
        </Col>

        {/* 右侧：候选人 */}
        <Col span={12}>
          <Card
            title={
              selectedGap
                ? `候选人 — ${selectedGap.position_label} · ${selectedGap.time_slot}`
                : '候选人'
            }
            loading={candidatesLoading}
          >
            {!selectedGap ? (
              <Empty description="请在左侧选择一个缺岗" />
            ) : candidates.length === 0 ? (
              <Empty description="暂无候选人" />
            ) : (
              candidates.map((c) => (
                <CandidateCard
                  key={c.employee_id}
                  candidate={c}
                  onSelect={(c) => setFillTarget(c)}
                />
              ))
            )}
          </Card>
        </Col>
      </Row>

      {/* 补位确认弹窗 */}
      <ModalForm
        title="确认补位"
        open={!!fillTarget}
        onOpenChange={(open) => {
          if (!open) setFillTarget(null);
        }}
        onFinish={handleFillGap}
        width={480}
      >
        <ProFormText
          label="补位员工"
          initialValue={fillTarget?.employee_name}
          disabled
          name="employee_display"
        />
        <ProFormText
          label="目标岗位"
          initialValue={selectedGap?.position_label}
          disabled
          name="position_display"
        />
        <ProFormSelect
          name="fill_type"
          label="补位方式"
          options={FILL_TYPE_OPTIONS}
          rules={[{ required: true, message: '请选择补位方式' }]}
        />
        <ProFormTextArea name="remark" label="备注" placeholder="可选备注说明" />
      </ModalForm>
    </div>
  );
}
