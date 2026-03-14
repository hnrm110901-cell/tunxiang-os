/**
 * 巡店检查 — 店长移动端
 * 门店日常巡检记录、整改跟踪
 */
import React, { useState, useEffect } from 'react';
import { Card, List, Tag, Button, Progress, Empty } from 'antd';
import { apiClient } from '../../services/api';
import styles from './Patrol.module.css';

interface PatrolItem {
  id: string;
  category: string;
  title: string;
  status: 'pending' | 'pass' | 'fail' | 'rectified';
  score: number;
  inspector?: string;
  created_at: string;
}

const STATUS_MAP: Record<string, { color: string; label: string }> = {
  pending:    { color: 'default',    label: '待检' },
  pass:       { color: 'success',    label: '合格' },
  fail:       { color: 'error',      label: '不合格' },
  rectified:  { color: 'processing', label: '已整改' },
};

export default function Patrol() {
  const [items, setItems] = useState<PatrolItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const storeId = localStorage.getItem('store_id') || 'STORE001';
    apiClient.get<{ items: PatrolItem[] }>(`/api/v1/bff/sm/${storeId}?section=patrol`)
      .then((data) => setItems(data.items || []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, []);

  const passCount = items.filter(i => i.status === 'pass' || i.status === 'rectified').length;
  const score = items.length > 0 ? Math.round((passCount / items.length) * 100) : 0;

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h2 className={styles.title}>巡店检查</h2>
        <Button type="primary" size="small">新建巡检</Button>
      </div>

      <Card className={styles.scoreCard} size="small">
        <div className={styles.scoreRow}>
          <Progress
            type="circle"
            percent={score}
            size={64}
            strokeColor={score >= 80 ? '#27AE60' : score >= 60 ? '#F2994A' : '#EB5757'}
          />
          <div className={styles.scoreMeta}>
            <div className={styles.scoreLabel}>今日巡检得分</div>
            <div className={styles.scoreDetail}>{passCount}/{items.length} 项合格</div>
          </div>
        </div>
      </Card>

      <List
        loading={loading}
        dataSource={items}
        locale={{ emptyText: <Empty description="暂无巡检记录" /> }}
        renderItem={(item) => {
          const st = STATUS_MAP[item.status] || STATUS_MAP.pending;
          return (
            <Card className={styles.itemCard} size="small" key={item.id}>
              <div className={styles.itemRow}>
                <div>
                  <Tag color="blue">{item.category}</Tag>
                  <span className={styles.itemTitle}>{item.title}</span>
                </div>
                <Tag color={st.color}>{st.label}</Tag>
              </div>
            </Card>
          );
        }}
      />
    </div>
  );
}
