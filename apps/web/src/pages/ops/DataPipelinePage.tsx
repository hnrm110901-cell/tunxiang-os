import React from 'react';
import { Card, Typography, Tag, Space, Empty } from 'antd';
import { ApiOutlined } from '@ant-design/icons';

const { Title, Paragraph } = Typography;

const DataPipelinePage: React.FC = () => {
  return (
    <div style={{ maxWidth: 800, margin: '0 auto' }}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <div>
          <Space align="center" size="middle">
            <Title level={3} style={{ margin: 0 }}>POS对接</Title>
            <Tag color="blue">开发中</Tag>
          </Space>
          <Paragraph type="secondary" style={{ marginTop: 8 }}>
            POS系统数据管道管理，监控数据同步状态与ETL任务
          </Paragraph>
        </div>
        <Card>
          <Empty description="功能开发中，敬请期待" />
        </Card>
      </Space>
    </div>
  );
};

export default DataPipelinePage;
