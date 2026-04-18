/**
 * 月度账单页 — 应用明细 + 总额 + 下载 PDF
 */
import React, { useEffect, useState } from 'react';
import { DatePicker, Table, Card, Button, message, Statistic } from 'antd';
import dayjs, { Dayjs } from 'dayjs';
import { apiClient, handleApiError } from '../../services/api';

interface LineItem {
  app_code: string;
  app_name: string;
  tier: string;
  amount_yuan: number;
  usage: Record<string, number>;
}

const Billing: React.FC = () => {
  const [period, setPeriod] = useState<Dayjs>(dayjs());
  const [items, setItems] = useState<LineItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const tenantId = localStorage.getItem('tenant_id') || 'demo-tenant';

  const load = async (p: Dayjs) => {
    setLoading(true);
    try {
      const period_str = p.format('YYYY-MM');
      const resp = await apiClient.get('/api/v1/marketplace/billing/my', {
        params: { tenant_id: tenantId, period: period_str },
      });
      setItems(resp.data.line_items || []);
      setTotal(resp.data.total_yuan || 0);
    } catch (e) {
      message.error(handleApiError(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(period);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period]);

  const downloadPdf = () => {
    const period_str = period.format('YYYY-MM');
    window.open(
      `/api/v1/marketplace/billing/my.pdf?tenant_id=${tenantId}&period=${period_str}`,
      '_blank',
    );
  };

  return (
    <div style={{ padding: 24 }}>
      <h2>月度账单</h2>
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, alignItems: 'center' }}>
        <DatePicker
          picker="month"
          value={period}
          onChange={(v) => v && setPeriod(v)}
        />
        <Button onClick={() => load(period)}>刷新</Button>
        <Button type="primary" onClick={downloadPdf}>
          下载发票 PDF
        </Button>
      </div>
      <Card style={{ marginBottom: 16 }}>
        <Statistic
          title={`${period.format('YYYY-MM')} 应付总额`}
          value={total}
          precision={2}
          prefix="¥"
          valueStyle={{ color: '#FF6B2C' }}
        />
      </Card>
      <Table
        loading={loading}
        dataSource={items}
        rowKey={(r) => r.app_code + r.tier}
        columns={[
          { title: '应用', dataIndex: 'app_name' },
          { title: '档位', dataIndex: 'tier' },
          {
            title: '金额',
            dataIndex: 'amount_yuan',
            render: (v) => `¥${(v || 0).toFixed(2)}`,
            align: 'right' as const,
          },
          {
            title: '用量',
            dataIndex: 'usage',
            render: (u: Record<string, number>) =>
              Object.entries(u || {})
                .map(([k, v]) => `${k}:${v}`)
                .join(' / ') || '-',
          },
        ]}
      />
    </div>
  );
};

export default Billing;
