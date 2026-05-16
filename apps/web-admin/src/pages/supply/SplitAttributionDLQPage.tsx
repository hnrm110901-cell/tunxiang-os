/**
 * Split Attribution 死信看板 — 域D 供应链（PRD-11 sub-C / Phase 2 W12 / T2 normal）
 * 路由：/supply/dlq/split-attribution
 *
 * 功能：
 *   1. 未确认死信红点展示 + 顶部 Statistic 卡（unack_count）
 *   2. 状态筛选（unack 默认 / ack / all）+ 死信列表（occurred_at desc）
 *   3. 详情 Drawer 展示完整 payload + 字段全集
 *   4. 确认 ModalForm 提交备注 + 可选 UUID 确认人，POST acknowledge
 *
 * 业务场景：Ops 早起看 DLQ 视角。tx-supply IndexSplitProjector 处理
 *   INVENTORY.split_attributed 事件失败时写 dlq_split_attribution_failed
 *   表 (v437)，运维需要逐条 review + 备注 + 确认。
 *
 * 调用接口（PRD-11 sub-C 经 gateway 直透到 tx-analytics）：
 *   GET  /api/v1/dlq/split-attribution?status=unack|ack|all&limit=&offset=
 *   GET  /api/v1/dlq/split-attribution/{dlq_id}
 *   POST /api/v1/dlq/split-attribution/{dlq_id}/acknowledge
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Drawer,
  Radio,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ReloadOutlined } from '@ant-design/icons';
import { ModalForm, ProFormText, ProFormTextArea } from '@ant-design/pro-components';
import dayjs from 'dayjs';
import { TxApiError, txFetchData } from '../../api/client';

const { Title, Text, Paragraph } = Typography;

type DLQStatus = 'unack' | 'ack' | 'all';

interface DLQItem {
  id: string;
  event_id: string;
  event_type: string;
  order_id: string | null;
  order_item_id: string | null;
  dish_id: string | null;
  error_class: string;
  error_msg: string;
  payload: Record<string, unknown>;
  occurred_at: string | null;
  created_at: string | null;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  ack_notes: string | null;
}

interface DLQListResponse {
  items: DLQItem[];
  page: { limit: number; offset: number; count: number };
  summary: { unack_count: number };
  generated_at: string;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PAGE_SIZE = 50;

const shortenId = (id: string | null): string => (id ? `${id.slice(0, 8)}…` : '-');
const fmtTime = (iso: string | null): string => (iso ? dayjs(iso).format('YYYY-MM-DD HH:mm:ss') : '-');

export function SplitAttributionDLQPage() {
  const [status, setStatus] = useState<DLQStatus>('unack');
  const [items, setItems] = useState<DLQItem[]>([]);
  const [unackCount, setUnackCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);

  const [detailOpen, setDetailOpen] = useState(false);
  const [detailItem, setDetailItem] = useState<DLQItem | null>(null);

  const [ackTarget, setAckTarget] = useState<DLQItem | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        status,
        limit: String(PAGE_SIZE),
        offset: String((page - 1) * PAGE_SIZE),
      });
      const data = await txFetchData<DLQListResponse>(
        `/api/v1/dlq/split-attribution?${params.toString()}`,
      );
      setItems(data.items);
      setUnackCount(data.summary.unack_count);
    } catch (e) {
      message.error('加载死信列表失败：' + (e instanceof Error ? e.message : String(e)));
    } finally {
      setLoading(false);
    }
  }, [status, page]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleViewDetail = async (row: DLQItem) => {
    try {
      const data = await txFetchData<DLQItem>(`/api/v1/dlq/split-attribution/${row.id}`);
      setDetailItem(data);
      setDetailOpen(true);
    } catch (e) {
      message.error('加载死信详情失败：' + (e instanceof Error ? e.message : String(e)));
    }
  };

  const handleAcknowledge = async (values: { notes: string; acknowledged_by_user_id?: string }) => {
    if (!ackTarget) return false;
    try {
      await txFetchData(`/api/v1/dlq/split-attribution/${ackTarget.id}/acknowledge`, {
        method: 'POST',
        body: JSON.stringify({
          notes: values.notes,
          acknowledged_by_user_id: values.acknowledged_by_user_id || null,
        }),
      });
      message.success('已确认');
      setAckTarget(null);
      await refresh();
      return true;
    } catch (e) {
      // P1-1 修法：用 TxApiError.statusCode 区分 404 / 422 / 其他；
      // 旧 msg.includes('404') 因 client.ts 把非 envelope 响应统一抛 message='API Error' 永不命中
      if (e instanceof TxApiError && e.statusCode === 404) {
        message.error('该死信已被他人确认或不存在');
      } else if (e instanceof TxApiError && e.statusCode === 422) {
        message.error('输入校验失败：' + e.message);
      } else {
        const msg = e instanceof Error ? e.message : String(e);
        message.error('确认失败：' + msg);
      }
      return false;
    }
  };

  const columns: ColumnsType<DLQItem> = [
    {
      title: '发生时间',
      dataIndex: 'occurred_at',
      key: 'occurred_at',
      width: 170,
      sorter: (a, b) => (a.occurred_at ?? '').localeCompare(b.occurred_at ?? ''),
      defaultSortOrder: 'descend',
      render: (v: string | null) => fmtTime(v),
    },
    { title: '事件类型', dataIndex: 'event_type', key: 'event_type', width: 200 },
    { title: 'error_class', dataIndex: 'error_class', key: 'error_class', width: 180 },
    {
      title: 'error_msg',
      dataIndex: 'error_msg',
      key: 'error_msg',
      ellipsis: true,
    },
    {
      title: 'order_id',
      dataIndex: 'order_id',
      key: 'order_id',
      width: 110,
      render: (v: string | null) =>
        v ? (
          <Tooltip title={v}>
            <span>{shortenId(v)}</span>
          </Tooltip>
        ) : (
          '-'
        ),
    },
    {
      title: 'dish_id',
      dataIndex: 'dish_id',
      key: 'dish_id',
      width: 110,
      render: (v: string | null) =>
        v ? (
          <Tooltip title={v}>
            <span>{shortenId(v)}</span>
          </Tooltip>
        ) : (
          '-'
        ),
    },
    {
      title: '确认时间',
      dataIndex: 'acknowledged_at',
      key: 'acknowledged_at',
      width: 170,
      render: (v: string | null) =>
        v ? fmtTime(v) : <Tag color="red">未确认</Tag>,
    },
    {
      title: '操作',
      key: 'ops',
      width: 160,
      fixed: 'right',
      render: (_, row) => (
        <Space>
          <Button type="link" size="small" onClick={() => handleViewDetail(row)}>
            查看详情
          </Button>
          {!row.acknowledged_at && (
            <Button type="link" size="small" onClick={() => setAckTarget(row)}>
              确认
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card>
        <Title level={3}>Split Attribution 死信看板 / PRD-11 sub-C 数据流死信</Title>
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          <Text>
            数据源：dlq_split_attribution_failed 表 (v437)，由 tx-supply
            IndexSplitProjector 写入。
          </Text>
          <br />
          <Text type="secondary">
            Ops 早起按 occurred_at desc 排查 → 查看详情 → 备注确认。
          </Text>
        </Paragraph>
      </Card>

      <Card>
        <Space size="large" align="center">
          <Badge count={unackCount} showZero={false} offset={[8, 4]}>
            <Statistic
              title="未确认死信"
              value={unackCount}
              valueStyle={{ fontSize: 32, color: unackCount > 0 ? '#A32D2D' : undefined }}
            />
          </Badge>
          <Button icon={<ReloadOutlined />} onClick={refresh} loading={loading}>
            刷新
          </Button>
        </Space>
      </Card>

      <Card
        title="死信列表"
        extra={
          <Radio.Group
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
            optionType="button"
            buttonStyle="solid"
          >
            <Radio.Button value="unack">未确认</Radio.Button>
            <Radio.Button value="ack">已确认</Radio.Button>
            <Radio.Button value="all">全部</Radio.Button>
          </Radio.Group>
        }
      >
        <Table<DLQItem>
          rowKey="id"
          dataSource={items}
          columns={columns}
          loading={loading}
          scroll={{ x: 1280 }}
          rowClassName={(row) => (row.acknowledged_at ? 'tx-dlq-ack-row' : '')}
          pagination={{
            current: page,
            pageSize: PAGE_SIZE,
            // P0 修法：backend list 响应未提供 page.total, antd 默认按 dataSource.length 推总页 → Next 灰掉。
            // 用乐观推断: 满页假设至少还有 1 条; 不满页时 (page-1)*size + items.length 精确。
            // TODO(follow-up): backend 加 page.total 字段后改为精确分页
            total:
              items.length >= PAGE_SIZE
                ? page * PAGE_SIZE + 1
                : (page - 1) * PAGE_SIZE + items.length,
            onChange: (p) => setPage(p),
            showSizeChanger: false,
          }}
          locale={{ emptyText: '当前 status 下无死信记录' }}
        />
      </Card>

      <Drawer
        open={detailOpen}
        title={detailItem ? `死信详情：${detailItem.id}` : '死信详情'}
        width={720}
        onClose={() => setDetailOpen(false)}
      >
        {detailItem ? (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Alert
              message={detailItem.error_class}
              description={detailItem.error_msg}
              type="error"
              showIcon
            />
            <div>
              <Text strong>事件 ID：</Text>
              <Text code>{detailItem.event_id}</Text>
            </div>
            <div>
              <Text strong>事件类型：</Text>
              <Text>{detailItem.event_type}</Text>
            </div>
            <div>
              <Text strong>order_id：</Text>
              <Text code>{detailItem.order_id ?? '-'}</Text>
            </div>
            <div>
              <Text strong>order_item_id：</Text>
              <Text code>{detailItem.order_item_id ?? '-'}</Text>
            </div>
            <div>
              <Text strong>dish_id：</Text>
              <Text code>{detailItem.dish_id ?? '-'}</Text>
            </div>
            <div>
              <Text strong>发生时间：</Text>
              <Text>{fmtTime(detailItem.occurred_at)}</Text>
            </div>
            <div>
              <Text strong>记录时间：</Text>
              <Text>{fmtTime(detailItem.created_at)}</Text>
            </div>
            <div>
              <Text strong>确认时间：</Text>
              <Text>{detailItem.acknowledged_at ? fmtTime(detailItem.acknowledged_at) : '未确认'}</Text>
            </div>
            {detailItem.acknowledged_by ? (
              <div>
                <Text strong>确认人：</Text>
                <Text code>{detailItem.acknowledged_by}</Text>
              </div>
            ) : null}
            {detailItem.ack_notes ? (
              <div>
                <Text strong>确认备注：</Text>
                <Paragraph>{detailItem.ack_notes}</Paragraph>
              </div>
            ) : null}
            <div>
              <Text strong>payload：</Text>
              <pre
                style={{
                  background: '#F8F7F5',
                  padding: 12,
                  borderRadius: 4,
                  maxHeight: 400,
                  overflow: 'auto',
                }}
              >
                {JSON.stringify(detailItem.payload, null, 2)}
              </pre>
            </div>
          </Space>
        ) : null}
      </Drawer>

      <ModalForm
        title="确认死信"
        open={!!ackTarget}
        onOpenChange={(open) => {
          if (!open) setAckTarget(null);
        }}
        onFinish={handleAcknowledge}
        modalProps={{ destroyOnClose: true }}
      >
        {ackTarget ? (
          <Alert
            message={`确认死信 ID：${ackTarget.id}`}
            description={ackTarget.error_msg}
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
          />
        ) : null}
        <ProFormTextArea
          name="notes"
          label="确认备注"
          fieldProps={{ maxLength: 4000, rows: 4, showCount: true }}
          rules={[{ required: true, message: '请填写确认备注' }]}
          placeholder="说明根因 / 是否需要补偿动作 / 跟进 issue 链接"
        />
        <ProFormText
          name="acknowledged_by_user_id"
          label="确认人 UUID（可选）"
          placeholder="留空则由后端从 JWT 推断 / 或填合规审计 UUID"
          rules={[
            {
              validator: (_, value) => {
                if (!value) return Promise.resolve();
                return UUID_RE.test(value)
                  ? Promise.resolve()
                  : Promise.reject(new Error('UUID 格式不正确'));
              },
            },
          ]}
        />
      </ModalForm>

      <style>{`.tx-dlq-ack-row { opacity: 0.6; }`}</style>
    </Space>
  );
}

export default SplitAttributionDLQPage;
