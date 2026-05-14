/**
 * 供应商门户 — RFQ 报价页（PRD-04 sub-C / Phase 2 W9-W10 / T2 normal）
 * 路由：/supplier-portal/rfqs/:rfqId/quote?supplier_id=<uuid>
 *
 * Sub-C scope：
 *   - 本页位于 web-admin 内，供 buyer 预览供应商 UX 或做内部 e2e 联调
 *   - 通过 URL query supplier_id 模拟供应商身份；POST 时透传 X-Supplier-ID header
 *   - 生产部署：sub-D follow-up 移到独立 supplier-portal app，
 *     由 supplier_portal_v2 (/auth/login) JWT 鉴权得 supplier_id
 *
 * 调用接口：
 *   GET   /api/v1/supply/rfqs/{id}/comparison        加载本 RFQ items
 *   POST  /api/v1/supply/supplier-portal/rfqs/{id}/quote  提交单 SKU 报价
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Space,
  Tag,
  Typography,
  message,
} from 'antd';
import { useParams, useSearchParams } from 'react-router-dom';
import dayjs from 'dayjs';
import { txFetchData } from '../../api/client';

const { Title, Text, Paragraph } = Typography;

interface RFQItem {
  id: string;
  ingredient_id: string;
  qty_required: string;
  qty_unit: string | null;
  spec_notes: string | null;
  quotes: Array<{ quote_id: string; supplier_id: string; unit_price_fen: number }>;
}

interface RFQ {
  id: string;
  rfq_number: string | null;
  deadline: string;
  status: string;
  notes: string | null;
}

interface RFQComparison {
  rfq: RFQ;
  items: RFQItem[];
}

interface QuoteItemRowProps {
  rfqId: string;
  supplierId: string;
  item: RFQItem;
  existingPriceFen: number | undefined;
  canQuote: boolean;
  onSuccess: () => void;
}

function QuoteItemRow({
  rfqId,
  supplierId,
  item,
  existingPriceFen,
  canQuote,
  onSuccess,
}: QuoteItemRowProps) {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (existingPriceFen != null) {
      form.setFieldsValue({ unit_price_yuan: existingPriceFen / 100 });
    }
  }, [existingPriceFen, form]);

  const handleSubmit = async () => {
    let values: {
      unit_price_yuan: number;
      qty_offered?: number;
      valid_until?: dayjs.Dayjs;
      notes?: string;
    };
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setSubmitting(true);
    try {
      const unit_price_fen = Math.round(values.unit_price_yuan * 100);
      const body = {
        ingredient_id: item.ingredient_id,
        unit_price_fen,
        qty_offered: values.qty_offered != null ? String(values.qty_offered) : null,
        // P1-1: API 期望 DATE (YYYY-MM-DD)，对齐 ORM 列类型
        valid_until: values.valid_until ? values.valid_until.format('YYYY-MM-DD') : null,
        notes: values.notes ?? null,
      };
      await txFetchData(`/api/v1/supply/supplier-portal/rfqs/${rfqId}/quote`, {
        method: 'POST',
        body: JSON.stringify(body),
        headers: { 'X-Supplier-ID': supplierId },
      });
      message.success(existingPriceFen != null ? '报价已更新' : '报价已提交');
      onSuccess();
    } catch (err) {
      const msg = err instanceof Error ? err.message : '提交失败';
      message.error(`提交失败：${msg}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card
      title={
        <Space>
          <Text strong>食材 {item.ingredient_id.slice(0, 8)}…</Text>
          <Tag>需求 {item.qty_required} {item.qty_unit ?? ''}</Tag>
          {existingPriceFen != null && (
            <Tag color="cyan">您已报价 ¥{(existingPriceFen / 100).toFixed(2)}（可覆盖）</Tag>
          )}
        </Space>
      }
      size="small"
    >
      {item.spec_notes && (
        <Paragraph type="secondary" style={{ marginBottom: 8 }}>
          规格备注：{item.spec_notes}
        </Paragraph>
      )}
      <Form
        form={form}
        layout="inline"
        onFinish={() => void handleSubmit()}
        disabled={!canQuote}
      >
        <Form.Item
          name="unit_price_yuan"
          label="单价 (元)"
          rules={[{ required: true, message: '请输入单价' }, { type: 'number', min: 0.01 }]}
        >
          <InputNumber min={0.01} step={0.01} precision={2} style={{ width: 140 }} />
        </Form.Item>
        <Form.Item name="qty_offered" label="承诺供货量">
          <InputNumber min={0.01} step={1} style={{ width: 140 }} placeholder="可选" />
        </Form.Item>
        <Form.Item name="valid_until" label="报价有效期">
          <DatePicker style={{ width: 160 }} format="YYYY-MM-DD" />
        </Form.Item>
        <Form.Item name="notes" style={{ flex: 1, minWidth: 200 }}>
          <Input placeholder="备注（可选）" maxLength={500} />
        </Form.Item>
        <Form.Item>
          <Button type="primary" htmlType="submit" loading={submitting}>
            {existingPriceFen != null ? '覆盖报价' : '提交报价'}
          </Button>
        </Form.Item>
      </Form>
    </Card>
  );
}

export function RFQSupplierQuotePage() {
  const { rfqId = '' } = useParams<{ rfqId: string }>();
  const [searchParams] = useSearchParams();
  const supplierId = searchParams.get('supplier_id') ?? '';

  const [comparison, setComparison] = useState<RFQComparison | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchData = useCallback(async () => {
    if (!rfqId) return;
    setLoading(true);
    try {
      const data = await txFetchData<RFQComparison>(
        `/api/v1/supply/rfqs/${rfqId}/comparison`,
      );
      setComparison(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '加载失败';
      message.error(`加载询价单失败：${msg}`);
    } finally {
      setLoading(false);
    }
  }, [rfqId]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const myExistingQuotes = useMemo(() => {
    if (!comparison || !supplierId) return new Map<string, number>();
    const map = new Map<string, number>();
    for (const it of comparison.items) {
      const mine = it.quotes.find((q) => q.supplier_id === supplierId);
      if (mine) map.set(it.ingredient_id, mine.unit_price_fen);
    }
    return map;
  }, [comparison, supplierId]);

  if (!supplierId) {
    return (
      <div style={{ padding: 24 }}>
        <Alert
          type="error"
          showIcon
          message="缺少 supplier_id"
          description="URL 必须包含 ?supplier_id=<uuid>。生产环境由供应商门户登录 JWT 自动注入。"
        />
      </div>
    );
  }

  const canQuote =
    comparison?.rfq.status === 'published' || comparison?.rfq.status === 'quoting';

  return (
    <div style={{ padding: 24, maxWidth: 1000, margin: '0 auto' }}>
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <Title level={3} style={{ margin: 0 }}>
          供应商报价提交 {comparison?.rfq.rfq_number ? `（${comparison.rfq.rfq_number}）` : ''}
        </Title>

        <Alert
          type="info"
          showIcon
          message={
            <Space>
              <Text>当前身份 (supplier_id):</Text>
              <code>{supplierId.slice(0, 8)}…</code>
              {comparison && (
                <>
                  <Text>询价单状态:</Text>
                  <Tag>{comparison.rfq.status}</Tag>
                </>
              )}
              {comparison && (
                <>
                  <Text>截止:</Text>
                  <Text strong>{dayjs(comparison.rfq.deadline).format('YYYY-MM-DD HH:mm')}</Text>
                </>
              )}
            </Space>
          }
          description={comparison?.rfq.notes ?? undefined}
        />

        {!canQuote && comparison && (
          <Alert
            type="warning"
            showIcon
            message={`询价单当前状态 "${comparison.rfq.status}" 不接收报价`}
            description="仅 published / quoting 状态可提交报价。"
          />
        )}

        {loading && <Card loading />}

        {comparison?.items.map((item) => (
          <QuoteItemRow
            key={item.id}
            rfqId={rfqId}
            supplierId={supplierId}
            item={item}
            existingPriceFen={myExistingQuotes.get(item.ingredient_id)}
            canQuote={!!canQuote}
            onSuccess={() => void fetchData()}
          />
        ))}
      </Space>
    </div>
  );
}

export default RFQSupplierQuotePage;
