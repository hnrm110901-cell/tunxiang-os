import React, { useState, useCallback } from 'react';
import { message } from 'antd';
import MemberSearchBar from '../../components/MemberSearchBar';
import MemberProfileCard, { type MemberProfile as MemberProfileType } from '../../components/MemberProfileCard';
import { apiClient } from '../../services/api';
import styles from './MemberProfile.module.css';

export default function MemberProfile() {
  const [profile, setProfile] = useState<MemberProfileType | null>(null);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  // TODO: 从用户上下文获取 store_id
  const storeId = 'STORE001';

  const handleSearch = useCallback(async (phone: string) => {
    setLoading(true);
    setSearched(true);
    try {
      const data = await apiClient.get<MemberProfileType>(
        `/api/v1/bff/member-profile/${storeId}/${phone}`,
      );
      setProfile(data);
    } catch (err) {
      message.error('查询失败，请稍后重试');
      setProfile(null);
    } finally {
      setLoading(false);
    }
  }, [storeId]);

  const handleIssueCoupon = useCallback((_consumerId: string) => {
    // P2 阶段实现
    message.info('发券功能即将上线');
  }, []);

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div className={styles.title}>会员识客</div>
      </div>
      <MemberSearchBar onSearch={handleSearch} loading={loading} />
      <div className={styles.content}>
        {searched && (
          <MemberProfileCard
            profile={profile}
            loading={loading}
            onIssueCoupon={handleIssueCoupon}
          />
        )}
      </div>
    </div>
  );
}
