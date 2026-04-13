/**
 * PointsRewardsPage -- 积分兑换商品管理+兑换记录
 * 域F . 组织人事 . HR Admin
 *
 * 功能：
 *  - 兑换商品ProTable（名称/类型/积分价格/库存/状态/操作）
 *  - 创建商品ModalForm
 *  - 上下架切换Switch
 *  - 底部兑换统计卡片
 *
 * API: GET  /api/v1/points/rewards
 *      POST /api/v1/points/rewards
 *      PUT  /api/v1/points/rewards/{id}/toggle
 *      GET  /api/v1/points/stats
 */

import { useEffect, useRef, useState } from 'react';
import { Button, Card, Col, message, Row, Statistic, Switch, Tag, Typography } from 'antd';
import {
  GiftOutlined,
  PlusOutlined,
  ShoppingOutlined,
  StarOutlined,
} from '@ant-design/icons';
import {
  ActionType,
  ModalForm,
  ProColumns,
  ProFormDigit,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
  ProTable,
} from '@ant-design/pro-components';
import { txFetchData } from '../../../api';

const { Title } = Typography;
const TX_PRIMARY = '#FF6B35';

// -- Types -------------------------------------------------------------------

interface RewardItem {
  id: string;
  reward_name: string;
  reward_type: string;
  points_cost: number;
  stock: number;
  description: string;
  is_active: boolean;
  created_at: string;
}

interface Stats {
  total_redemptions: number;
  total_redeemed_points: number;
  net_balance: number;
  active_employees: number;
}

const TYPE_MAP: Record<string, { label: string; color: string }> = {
  leave: { label: '调休', color: 'blue' },
  bonus: { label: '奖金', color: 'green' },
  gift: { label: '礼品', color: 'purple' },
  voucher: { label: '优惠券', color: 'orange' },
};

// -- Component ---------------------------------------------------------------

export default function PointsRewardsPage() {
  const actionRef = useRef<ActionType>(null);
  const [messageApi, contextHolder] = message.useMessage();
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = (await txFetchData('/api/v1/points/stats')) as {
          ok: boolean;
          data: Stats;
        };
        if (res.ok) setStats(res.data);
      } catch {
        /* empty */
      }
    })();
  }, []);

  const handleToggle = async (rewardId: string) => {
    try {
      const res = (await txFetchData(`/api/v1/points/rewards/${rewardId}/toggle`, {
        method: 'PUT',
      })) as { ok: boolean; data: { is_active: boolean } };
      if (res.ok) {
        messageApi.success(res.data.is_active ? '商品已上架' : '商品已下架');
        actionRef.current?.reload();
      }
    } catch {
      messageApi.error('操作失败');
    }
  };

  const columns: ProColumns<RewardItem>[] = [
    {
      title: '商品名称',
      dataIndex: 'reward_name',
      width: 160,
      render: (_, r) => (
        <span style={{ fontWeight: 'bold' }}>
          <GiftOutlined style={{ color: TX_PRIMARY, marginRight: 4 }} />
          {r.reward_name}
        </span>
      ),
    },
    {
      title: '类型',
      dataIndex: 'reward_type',
      width: 80,
      valueEnum: {
        leave: { text: '调休' },
        bonus: { text: '奖金' },
        gift: { text: '礼品' },
        voucher: { text: '优惠券' },
      },
      render: (_, r) => {
        const t = TYPE_MAP[r.reward_type] ?? { label: r.reward_type, color: 'default' };
        return <Tag color={t.color}>{t.label}</Tag>;
      },
    },
    {
      title: '积分价格',
      dataIndex: 'points_cost',
      width: 100,
      hideInSearch: true,
      sorter: true,
      render: (_, r) => (
        <span style={{ color: TX_PRIMARY, fontWeight: 'bold' }}>
          <StarOutlined /> {r.points_cost}
        </span>
      ),
    },
    {
      title: '库存',
      dataIndex: 'stock',
      width: 80,
      hideInSearch: true,
      render: (_, r) => (r.stock < 0 ? <Tag color="green">不限</Tag> : r.stock),
    },
    {
      title: '描述',
      dataIndex: 'description',
      width: 200,
      hideInSearch: true,
      ellipsis: true,
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 80,
      hideInSearch: true,
      render: (_, r) => (
        <Switch
          checked={r.is_active}
          checkedChildren="上架"
          unCheckedChildren="下架"
          onChange={() => handleToggle(r.id)}
        />
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 140,
      hideInSearch: true,
      render: (_, r) => r.created_at?.slice(0, 10),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      {contextHolder}
      <Title level={4}>
        <ShoppingOutlined style={{ color: TX_PRIMARY }} /> 积分兑换商品
      </Title>

      {/* -- 统计 -- */}
      {stats && (
        <Row gutter={16} style={{ marginBottom: 24 }}>
          <Col span={6}>
            <Card>
              <Statistic title="累计兑换次数" value={stats.total_redemptions} prefix={<GiftOutlined />} />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="累计兑换积分"
                value={stats.total_redeemed_points}
                valueStyle={{ color: TX_PRIMARY }}
                prefix={<StarOutlined />}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic title="全员积分池" value={stats.net_balance} />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic title="积分活跃人数" value={stats.active_employees} />
            </Card>
          </Col>
        </Row>
      )}

      {/* -- 商品表 -- */}
      <ProTable<RewardItem>
        headerTitle="兑换商品列表"
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        search={{ labelWidth: 80 }}
        toolBarRender={() => [
          <ModalForm
            key="create"
            title="创建兑换商品"
            trigger={
              <Button
                type="primary"
                icon={<PlusOutlined />}
                style={{ backgroundColor: TX_PRIMARY, borderColor: TX_PRIMARY }}
              >
                新建商品
              </Button>
            }
            onFinish={async (values) => {
              try {
                const res = (await txFetchData('/api/v1/points/rewards', {
                  method: 'POST',
                  body: JSON.stringify(values),
                })) as { ok: boolean };
                if (res.ok) {
                  messageApi.success('商品创建成功');
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
            <ProFormText name="reward_name" label="商品名称" rules={[{ required: true }]} placeholder="如：半天调休" />
            <ProFormSelect
              name="reward_type"
              label="类型"
              rules={[{ required: true }]}
              options={[
                { label: '调休', value: 'leave' },
                { label: '奖金', value: 'bonus' },
                { label: '礼品', value: 'gift' },
                { label: '优惠券', value: 'voucher' },
              ]}
            />
            <ProFormDigit name="points_cost" label="积分价格" min={1} rules={[{ required: true }]} />
            <ProFormDigit name="stock" label="库存" min={-1} initialValue={-1} tooltip="-1表示不限库存" />
            <ProFormTextArea name="description" label="描述" />
          </ModalForm>,
        ]}
        request={async (params) => {
          try {
            const q = new URLSearchParams();
            q.set('active_only', 'false');
            const res = (await txFetchData(`/api/v1/points/rewards?${q}`)) as {
              ok: boolean;
              data: { items: RewardItem[]; total: number };
            };
            if (res.ok) {
              // Client-side filter by type if specified
              let items = res.data.items;
              if (params.reward_type) {
                items = items.filter((i) => i.reward_type === params.reward_type);
              }
              return { data: items, total: items.length, success: true };
            }
          } catch {
            /* fallback */
          }
          return { data: [], total: 0, success: true };
        }}
        pagination={{ defaultPageSize: 10 }}
      />
    </div>
  );
}
