import React from 'react';
import { Card, Typography, Tag, Space, Empty } from 'antd';
import { AlertOutlined } from '@ant-design/icons';

const { Title, Paragraph } = Typography;

const RenewalAlertPage: React.FC = () => {
  return (
    <div style={{ maxWidth: 800, margin: '0 auto' }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <div>
          <Space align="center" size="middle">
            <AlertOutlined style={{ fontSize: 24, color: '#0AAF9A' }} />
            <Title level={3} style={{ margin: 0 }}>续费预警</Title>
            <Tag color="cyan">new</Tag>
          </Space>
          <Paragraph type="secondary" style={{ marginTop: 8 }}>
            商户合同到期提醒、续费跟踪、流失预警分析。帮助客户成功团队提前介入，提升续费率。
          </Paragraph>
        </div>
        <Card>
          <Empty description="功能开发中，敬请期待" />
        </Card>
      </Space>
    </div>
  );
};

export default RenewalAlertPage;
