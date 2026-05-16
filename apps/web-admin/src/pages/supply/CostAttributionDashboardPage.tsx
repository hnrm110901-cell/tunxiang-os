/**
 * 成本分摊看板 — 域D 供应链（PRD-11 sub-C / Phase 2 W12 / T2 normal）
 * 路由：/supply/cost-attribution
 *
 * 功能：
 *   1. 时段总览 6 个 Statistic 卡（事件数 / 拆单事件 / 拆单比例 / 总 BOM 摊销 /
 *      平均 share_count / 覆盖订单与菜品数）
 *   2. 单订单分摊明细应急查询（输入 order_id UUID → Modal 展示 attributions 列表）
 *   3. 单菜 share_count 分布查询（输入 dish_id UUID + 复用时段筛选 → Column 图）
 *
 * 业务场景：店长 / 产品 / 运营周报视角，一站式查看徐记海鲜 200 桌场景下多人合点
 *   成本分摊情况。数据来源：SplitAttributionProjector（PR #698 + #718）消费
 *   INVENTORY.split_attributed 事件投影出 cost_attribution_summary 表。
 *
 * 调用接口（PRD-11 sub-C 经 gateway 直透到 tx-analytics）：
 *   GET /api/v1/cost-attribution/summary?from=YYYY-MM-DD&to=YYYY-MM-DD
 *   GET /api/v1/cost-attribution/dishes/{dish_id}/summary?from=&to=
 *   GET /api/v1/cost-attribution/orders/{order_id}
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Input,
  Modal,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import { Column } from '@ant-design/charts';
import dayjs, { type Dayjs } from 'dayjs';
import { txFetchData } from '../../api/client';

const { Title, Text, Paragraph } = Typography;
const { RangePicker } = DatePicker;

interface SummaryResponse {
  from: string;
  to: string;
  summary: {
    total_events: number;
    share_split_events: number;
    share_split_ratio: number;
    total_bom_fen: number;
    avg_share_count: number;
    distinct_orders: number;
    distinct_dishes: number;
  };
  generated_at: string;
}

interface DishDistributionBucket {
  share_count: number;
  event_count: number;
  total_bom_fen: number;
  avg_bom_fen: number;
}

interface DishSummaryResponse {
  dish_id: string;
  from: string | null;
  to: string | null;
  distribution: DishDistributionBucket[];
  summary: {
    total_events: number;
    total_bom_fen: number;
    avg_bom_fen: number;
  };
  generated_at: string;
}

interface OrderAttribution {
  id: string;
  source_event_id: string;
  order_id: string | null;
  order_item_id: string | null;
  dish_id: string | null;
  method: string;
  share_count: number;
  bom_cost_total_fen: number;
  shares: unknown[];
  occurred_at: string | null;
  created_at: string | null;
}

interface OrderResponse {
  order_id: string;
  attributions: OrderAttribution[];
  summary: { item_count: number; total_bom_cost_fen: number };
  generated_at: string;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const fenToYuan = (fen: number): string => `¥${(fen / 100).toFixed(2)}`;
const shortenId = (id: string | null): string => (id ? `${id.slice(0, 8)}…` : '-');
const fmtTime = (iso: string | null): string => (iso ? dayjs(iso).format('YYYY-MM-DD HH:mm:ss') : '-');

export function CostAttributionDashboardPage() {
  const [range, setRange] = useState<[Dayjs, Dayjs]>([dayjs().subtract(30, 'day'), dayjs()]);
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  const [orderId, setOrderId] = useState('');
  const [orderResult, setOrderResult] = useState<OrderResponse | null>(null);
  const [orderModalOpen, setOrderModalOpen] = useState(false);
  const [orderLoading, setOrderLoading] = useState(false);

  const [dishId, setDishId] = useState('');
  const [dishResult, setDishResult] = useState<DishSummaryResponse | null>(null);
  const [dishLoading, setDishLoading] = useState(false);

  const fromStr = range[0].format('YYYY-MM-DD');
  const toStr = range[1].format('YYYY-MM-DD');

  const refreshSummary = useCallback(async () => {
    setSummaryLoading(true);
    try {
      const params = new URLSearchParams({ from: fromStr, to: toStr });
      const data = await txFetchData<SummaryResponse>(
        `/api/v1/cost-attribution/summary?${params.toString()}`,
      );
      setSummary(data);
    } catch (e) {
      message.error('加载成本分摊总览失败：' + (e instanceof Error ? e.message : String(e)));
    } finally {
      setSummaryLoading(false);
    }
  }, [fromStr, toStr]);

  useEffect(() => {
    refreshSummary();
  }, [refreshSummary]);

  const handleQueryOrder = async () => {
    const trimmed = orderId.trim();
    if (!trimmed) {
      message.warning('请输入订单 ID（UUID）');
      return;
    }
    if (!UUID_RE.test(trimmed)) {
      message.warning('订单 ID 格式不正确（需 UUID 格式，例 33333333-0001-0001-0001-333333333333）');
      return;
    }
    setOrderLoading(true);
    try {
      const data = await txFetchData<OrderResponse>(
        `/api/v1/cost-attribution/orders/${encodeURIComponent(trimmed)}`,
      );
      setOrderResult(data);
      setOrderModalOpen(true);
    } catch (e) {
      message.error('查询订单分摊明细失败：' + (e instanceof Error ? e.message : String(e)));
    } finally {
      setOrderLoading(false);
    }
  };

  const handleQueryDish = async () => {
    const trimmed = dishId.trim();
    if (!trimmed) {
      message.warning('请输入菜品 ID（UUID）');
      return;
    }
    if (!UUID_RE.test(trimmed)) {
      message.warning('菜品 ID 格式不正确（需 UUID 格式，例 22222222-0001-0001-0001-222222222222）');
      return;
    }
    setDishLoading(true);
    try {
      const params = new URLSearchParams({ from: fromStr, to: toStr });
      const data = await txFetchData<DishSummaryResponse>(
        `/api/v1/cost-attribution/dishes/${encodeURIComponent(trimmed)}/summary?${params.toString()}`,
      );
      setDishResult(data);
    } catch (e) {
      message.error('查询菜品分布失败：' + (e instanceof Error ? e.message : String(e)));
    } finally {
      setDishLoading(false);
    }
  };

  const ratio = summary?.summary.share_split_ratio ?? 0;
  const ratioPct = (ratio * 100).toFixed(1);
  const ratioTagColor = ratio > 0.3 ? 'warning' : 'default';

  const orderColumns: ColumnsType<OrderAttribution> = [
    {
      title: 'order_item_id',
      dataIndex: 'order_item_id',
      key: 'order_item_id',
      width: 110,
      render: (v: string | null) => shortenId(v),
    },
    {
      title: 'dish_id',
      dataIndex: 'dish_id',
      key: 'dish_id',
      width: 110,
      render: (v: string | null) => shortenId(v),
    },
    { title: 'method', dataIndex: 'method', key: 'method', width: 90 },
    { title: 'share_count', dataIndex: 'share_count', key: 'share_count', width: 100 },
    {
      title: 'BOM 摊销',
      dataIndex: 'bom_cost_total_fen',
      key: 'bom_cost_total_fen',
      width: 120,
      render: (v: number) => fenToYuan(v),
    },
    {
      title: '发生时间',
      dataIndex: 'occurred_at',
      key: 'occurred_at',
      width: 170,
      render: (v: string | null) => fmtTime(v),
    },
  ];

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card>
        <Title level={3}>成本分摊看板 / PRD-11 多人合点</Title>
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          <Text>
            数据来源：SplitAttributionProjector 消费 INVENTORY.split_attributed 事件投影
          </Text>
          <br />
          <Text type="secondary">
            cost_attribution_summary 表 (v437)。BOM 物理消耗不变，仅 cost 在多 share 间分摊。
          </Text>
        </Paragraph>
      </Card>

      <Card
        title="时段总览"
        extra={
          <Space>
            <RangePicker
              value={range}
              onChange={(values) => {
                if (values && values[0] && values[1]) {
                  setRange([values[0], values[1]]);
                }
              }}
              allowClear={false}
            />
            <Button icon={<ReloadOutlined />} onClick={refreshSummary} loading={summaryLoading}>
              刷新
            </Button>
          </Space>
        }
        loading={summaryLoading}
      >
        {summary ? (
          <>
            <Row gutter={[16, 16]}>
              <Col span={8}>
                <Statistic title="总分摊事件数" value={summary.summary.total_events} />
              </Col>
              <Col span={8}>
                <Statistic
                  title={
                    <Space>
                      <span>触发拆单事件</span>
                      <Tag color={ratioTagColor}>占比 {ratioPct}%</Tag>
                    </Space>
                  }
                  value={summary.summary.share_split_events}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="总 BOM 摊销金额"
                  value={(summary.summary.total_bom_fen / 100).toFixed(2)}
                  prefix="¥"
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="平均 share_count"
                  value={summary.summary.avg_share_count}
                  precision={2}
                />
              </Col>
              <Col span={8}>
                <Statistic title="覆盖订单数" value={summary.summary.distinct_orders} />
              </Col>
              <Col span={8}>
                <Statistic title="覆盖菜品数" value={summary.summary.distinct_dishes} />
              </Col>
            </Row>
            <Paragraph type="secondary" style={{ marginTop: 16, marginBottom: 0 }}>
              数据范围：{summary.from} ~ {summary.to}（生成于 {fmtTime(summary.generated_at)}）
            </Paragraph>
          </>
        ) : (
          <Alert message="暂无数据" type="info" />
        )}
      </Card>

      <Card title="单订单分摊明细查询（应急用）">
        <Paragraph type="secondary">
          输入订单 UUID 查询该订单全部 order_item 的分摊明细，用于排查"账单成本对不上"类工单。
        </Paragraph>
        <Space.Compact style={{ width: '100%' }}>
          <Input
            placeholder="订单 ID（UUID）例如：33333333-0001-0001-0001-333333333333"
            value={orderId}
            onChange={(e) => setOrderId(e.target.value)}
            onPressEnter={handleQueryOrder}
            allowClear
          />
          <Button
            type="primary"
            icon={<SearchOutlined />}
            loading={orderLoading}
            onClick={handleQueryOrder}
          >
            查询
          </Button>
        </Space.Compact>
      </Card>

      <Card title="单菜 share_count 分布查询">
        <Paragraph type="secondary">
          输入菜品 UUID 查询其在筛选时段内的分布柱状图（横轴 share_count，纵轴 event_count）。
        </Paragraph>
        <Space.Compact style={{ width: '100%', marginBottom: 16 }}>
          <Input
            placeholder="菜品 ID（UUID）例如：22222222-0001-0001-0001-222222222222"
            value={dishId}
            onChange={(e) => setDishId(e.target.value)}
            onPressEnter={handleQueryDish}
            allowClear
          />
          <Button
            type="primary"
            icon={<SearchOutlined />}
            loading={dishLoading}
            onClick={handleQueryDish}
          >
            查询
          </Button>
        </Space.Compact>
        {dishResult ? (
          <>
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={8}>
                <Statistic title="总事件" value={dishResult.summary.total_events} />
              </Col>
              <Col span={8}>
                <Statistic
                  title="总 BOM 摊销"
                  value={(dishResult.summary.total_bom_fen / 100).toFixed(2)}
                  prefix="¥"
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="平均 BOM / 事件"
                  value={(dishResult.summary.avg_bom_fen / 100).toFixed(2)}
                  prefix="¥"
                />
              </Col>
            </Row>
            {dishResult.distribution.length > 0 ? (
              <Column
                data={dishResult.distribution}
                xField="share_count"
                yField="event_count"
                height={300}
                label={{ position: 'top' }}
                axis={{
                  x: { title: 'share_count（合点人数）' },
                  y: { title: 'event_count（事件数）' },
                }}
              />
            ) : (
              <Alert message="该菜品在所选时段内无分摊事件" type="info" />
            )}
          </>
        ) : null}
      </Card>

      <Modal
        open={orderModalOpen}
        title={`订单分摊明细：${orderResult?.order_id ?? ''}`}
        width={960}
        footer={null}
        onCancel={() => setOrderModalOpen(false)}
      >
        {orderResult ? (
          <>
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={12}>
                <Statistic title="order_item 行数" value={orderResult.summary.item_count} />
              </Col>
              <Col span={12}>
                <Statistic
                  title="总 BOM 成本"
                  value={(orderResult.summary.total_bom_cost_fen / 100).toFixed(2)}
                  prefix="¥"
                />
              </Col>
            </Row>
            <Table<OrderAttribution>
              rowKey="id"
              dataSource={orderResult.attributions}
              columns={orderColumns}
              pagination={{ pageSize: 20 }}
              size="small"
              scroll={{ x: 800 }}
              locale={{ emptyText: '该订单无分摊记录' }}
            />
          </>
        ) : null}
      </Modal>
    </Space>
  );
}

export default CostAttributionDashboardPage;
