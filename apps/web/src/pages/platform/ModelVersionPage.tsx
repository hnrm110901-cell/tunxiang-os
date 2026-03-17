import React from 'react';
import { Card, Empty } from 'antd';
import { BranchesOutlined } from '@ant-design/icons';

const ModelVersionPage: React.FC = () => (
  <div style={{ padding: 0 }}>
    <Card>
      <Empty
        image={<BranchesOutlined style={{ fontSize: 48, color: 'rgba(255,255,255,0.15)' }} />}
        description={
          <div>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8, color: 'var(--text-primary)' }}>模型版本</div>
            <div style={{ color: 'var(--text-tertiary)', fontSize: 13 }}>LLM 模型版本管理，灰度发布与回滚控制</div>
          </div>
        }
      />
    </Card>
  </div>
);

export default ModelVersionPage;
