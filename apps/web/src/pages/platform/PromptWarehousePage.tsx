import React from 'react';
import { Card, Empty } from 'antd';
import { FileTextOutlined } from '@ant-design/icons';

const PromptWarehousePage: React.FC = () => (
  <div style={{ padding: 0 }}>
    <Card>
      <Empty
        image={<FileTextOutlined style={{ fontSize: 48, color: 'rgba(255,255,255,0.15)' }} />}
        description={
          <div>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8, color: 'var(--text-primary)' }}>提示词仓库</div>
            <div style={{ color: 'var(--text-tertiary)', fontSize: 13 }}>Agent 提示词模板管理，版本控制与效果评估</div>
          </div>
        }
      />
    </Card>
  </div>
);

export default PromptWarehousePage;
