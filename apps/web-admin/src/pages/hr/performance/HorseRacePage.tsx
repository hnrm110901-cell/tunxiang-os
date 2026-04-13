/**
 * HorseRacePage -- 赛马管理
 * 域F . 组织人事 . HR Admin
 *
 * 功能：
 *  - 赛季列表（状态Tag+起止日期+维度）
 *  - 创建赛季ModalForm
 *  - 赛季实时排名Drawer（点击行展开）
 *  - 赛季状态操作（启动/完成）
 *
 * API: GET  /api/v1/points/horse-race
 *      POST /api/v1/points/horse-race
 *      GET  /api/v1/points/horse-race/{id}/ranking
 *      PUT  /api/v1/points/horse-race/{id}/status
 */

import { useRef, useState } from 'react';
import { Button, Drawer, message, Space, Table, Tag, Typography } from 'antd';
import {
  PlusOutlined,
  PlayCircleOutlined,
  CheckCircleOutlined,
  CrownOutlined,
  TrophyOutlined,
} from '@ant-design/icons';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormDateRangePicker,
  ProFormSelect,
  ProFormText,
  ProTable,
} from '@ant-design/pro-components';
import { txFetchData } from '../../../api';

const { Title } = Typography;
const TX_PRIMARY = '#FF6B35';

// -- Types -------------------------------------------------------------------

interface SeasonItem {
  id: string;
  season_name: string;
  scope_type: string;
  scope_id: string | null;
  start_date: string;
  end_date: string;
  ranking_dimension: string;
  status: string;
}

interface RankingItem {
  employee_id: string;
  emp_name: string;
  store_id: string | null;
  season_points: number;
  rank: number;
}

const STATUS_MAP: Record<string, { text: string; color: string }> = {
  upcoming: { text: '即将开始', color: 'default' },
  active: { text: '进行中', color: 'processing' },
  completed: { text: '已结束', color: 'success' },
};

const DIMENSION_MAP: Record<string, string> = {
  points: '积分',
  revenue: '营收',
  service_score: '服务评分',
};

// -- Component ---------------------------------------------------------------

export default function HorseRacePage() {
  const actionRef = useRef<ActionType>(null);
  const [messageApi, contextHolder] = message.useMessage();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [ranking, setRanking] = useState<RankingItem[]>([]);
  const [currentSeason, setCurrentSeason] = useState<SeasonItem | null>(null);

  const handleViewRanking = async (season: SeasonItem) => {
    setCurrentSeason(season);
    try {
      const res = (await txFetchData(
        `/api/v1/points/horse-race/${season.id}/ranking?limit=50`,
      )) as {
        ok: boolean;
        data: { ranking: RankingItem[] };
      };
      if (res.ok) {
        setRanking(res.data.ranking ?? []);
      }
    } catch {
      messageApi.error('获取排名失败');
    }
    setDrawerOpen(true);
  };

  const handleStatusChange = async (seasonId: string, newStatus: string) => {
    try {
      const res = (await txFetchData(`/api/v1/points/horse-race/${seasonId}/status`, {
        method: 'PUT',
        body: JSON.stringify({ status: newStatus }),
      })) as { ok: boolean };
      if (res.ok) {
        messageApi.success('状态更新成功');
        actionRef.current?.reload();
      }
    } catch {
      messageApi.error('操作失败');
    }
  };

  const columns: ProColumns<SeasonItem>[] = [
    {
      title: '赛季名称',
      dataIndex: 'season_name',
      width: 180,
      render: (_, r) => (
        <a onClick={() => handleViewRanking(r)} style={{ fontWeight: 'bold' }}>
          <TrophyOutlined style={{ color: TX_PRIMARY, marginRight: 4 }} />
          {r.season_name}
        </a>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      valueEnum: {
        upcoming: { text: '即将开始', status: 'Default' },
        active: { text: '进行中', status: 'Processing' },
        completed: { text: '已结束', status: 'Success' },
      },
      render: (_, r) => {
        const s = STATUS_MAP[r.status] ?? { text: r.status, color: 'default' };
        return <Tag color={s.color}>{s.text}</Tag>;
      },
    },
    {
      title: '范围',
      dataIndex: 'scope_type',
      width: 80,
      hideInSearch: true,
      render: (_, r) => r.scope_type === 'store' ? '门店' : r.scope_type === 'region' ? '区域' : '品牌',
    },
    {
      title: '排名维度',
      dataIndex: 'ranking_dimension',
      width: 100,
      hideInSearch: true,
      render: (_, r) => DIMENSION_MAP[r.ranking_dimension] ?? r.ranking_dimension,
    },
    {
      title: '开始日期',
      dataIndex: 'start_date',
      width: 120,
      hideInSearch: true,
    },
    {
      title: '结束日期',
      dataIndex: 'end_date',
      width: 120,
      hideInSearch: true,
    },
    {
      title: '操作',
      width: 200,
      hideInSearch: true,
      render: (_, r) => (
        <Space>
          <Button size="small" onClick={() => handleViewRanking(r)}>
            查看排名
          </Button>
          {r.status === 'upcoming' && (
            <Button
              size="small"
              type="primary"
              icon={<PlayCircleOutlined />}
              style={{ backgroundColor: TX_PRIMARY, borderColor: TX_PRIMARY }}
              onClick={() => handleStatusChange(r.id, 'active')}
            >
              启动
            </Button>
          )}
          {r.status === 'active' && (
            <Button
              size="small"
              icon={<CheckCircleOutlined />}
              onClick={() => handleStatusChange(r.id, 'completed')}
            >
              结束
            </Button>
          )}
        </Space>
      ),
    },
  ];

  const rankColumns = [
    {
      title: '排名',
      dataIndex: 'rank',
      width: 70,
      render: (_: unknown, r: RankingItem) => {
        if (r.rank === 1) return <Tag color="#FFD700"><CrownOutlined /> 1</Tag>;
        if (r.rank <= 3) return <Tag color="#CD7F32">{r.rank}</Tag>;
        return r.rank;
      },
    },
    {
      title: '姓名',
      dataIndex: 'emp_name',
      width: 100,
      render: (_: unknown, r: RankingItem) => (
        <span style={r.rank <= 3 ? { fontWeight: 'bold', color: TX_PRIMARY } : undefined}>
          {r.emp_name}
        </span>
      ),
    },
    {
      title: '赛季积分',
      dataIndex: 'season_points',
      width: 100,
      render: (_: unknown, r: RankingItem) => (
        <span style={{ fontWeight: 'bold', fontSize: r.rank <= 3 ? 16 : 14 }}>
          {r.season_points}
        </span>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      {contextHolder}
      <Title level={4}>
        <TrophyOutlined style={{ color: TX_PRIMARY }} /> 赛马管理
      </Title>

      <ProTable<SeasonItem>
        headerTitle="赛马赛季"
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        search={{ labelWidth: 80 }}
        toolBarRender={() => [
          <ModalForm
            key="create"
            title="创建赛季"
            trigger={
              <Button
                type="primary"
                icon={<PlusOutlined />}
                style={{ backgroundColor: TX_PRIMARY, borderColor: TX_PRIMARY }}
              >
                新建赛季
              </Button>
            }
            onFinish={async (values) => {
              try {
                const [startDate, endDate] = values.dateRange ?? [];
                const res = (await txFetchData('/api/v1/points/horse-race', {
                  method: 'POST',
                  body: JSON.stringify({
                    season_name: values.season_name,
                    start_date: startDate,
                    end_date: endDate,
                    scope_type: values.scope_type ?? 'store',
                    ranking_dimension: values.ranking_dimension ?? 'points',
                  }),
                })) as { ok: boolean };
                if (res.ok) {
                  messageApi.success('赛季创建成功');
                  actionRef.current?.reload();
                  return true;
                }
              } catch {
                messageApi.error('创建失败');
              }
              return false;
            }}
            modalProps={{ destroyOnClose: true }}
          >
            <ProFormText name="season_name" label="赛季名称" rules={[{ required: true }]} placeholder="如：2026年4月销售冲刺赛" />
            <ProFormDateRangePicker name="dateRange" label="起止日期" rules={[{ required: true }]} />
            <ProFormSelect
              name="scope_type"
              label="范围类型"
              initialValue="store"
              options={[
                { label: '门店', value: 'store' },
                { label: '区域', value: 'region' },
                { label: '品牌', value: 'brand' },
              ]}
            />
            <ProFormSelect
              name="ranking_dimension"
              label="排名维度"
              initialValue="points"
              options={[
                { label: '积分', value: 'points' },
                { label: '营收', value: 'revenue' },
                { label: '服务评分', value: 'service_score' },
              ]}
            />
          </ModalForm>,
        ]}
        request={async (params) => {
          const q = new URLSearchParams();
          if (params.status) q.set('status', params.status);
          try {
            const res = (await txFetchData(`/api/v1/points/horse-race?${q}`)) as {
              ok: boolean;
              data: { items: SeasonItem[]; total: number };
            };
            if (res.ok) {
              return { data: res.data.items, total: res.data.total, success: true };
            }
          } catch {
            /* fallback */
          }
          return { data: [], total: 0, success: true };
        }}
        pagination={{ defaultPageSize: 10 }}
      />

      {/* -- 排名 Drawer -- */}
      <Drawer
        title={currentSeason ? `${currentSeason.season_name} - 实时排名` : '赛季排名'}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={480}
      >
        <Table<RankingItem>
          dataSource={ranking}
          rowKey="employee_id"
          columns={rankColumns}
          pagination={false}
          size="small"
        />
      </Drawer>
    </div>
  );
}
