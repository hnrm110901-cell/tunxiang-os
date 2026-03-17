import React from 'react';
import { Card, Empty } from 'antd';
import { RocketOutlined } from '@ant-design/icons';

const DeliveryTrackingPage: React.FC = () => (
  <div style={{ padding: 0 }}>
    <Card>
      <Empty
        image={<RocketOutlined style={{ fontSize: 48, color: 'rgba(255,255,255,0.15)' }} />}
        description={
          <div>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8, color: 'var(--text-primary)' }}>实施跟踪</div>
            <div style={{ color: 'var(--text-tertiary)', fontSize: 13 }}>客户交付进度与 SLA 达成情况追踪</div>
          </div>
        }
      />
    </Card>
  </div>
);

export default DeliveryTrackingPage;
