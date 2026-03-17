import React from 'react';
import { Card, Typography, Tag, Space, Empty } from 'antd';
import { SettingOutlined } from '@ant-design/icons';

const { Title, Paragraph } = Typography;

const BusinessRulesPage: React.FC = () => {
  return (
    <div style={{ maxWidth: 800, margin: '0 auto' }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <div>
          <Space align="center" size="middle">
            <Title level={3} style={{ margin: 0 }}>业务规则</Title>
            <Tag color="blue">开发中</Tag>
          </Space>
          <Paragraph type="secondary" style={{ marginTop: 8 }}>
            业务规则配置中心，定义损耗阈值、告警条件与自动化策略
          </Paragraph>
        </div>
        <Card>
          <Empty description="功能开发中，敬请期待" />
        </Card>
      </Space>
    </div>
  );
};

export default BusinessRulesPage;
