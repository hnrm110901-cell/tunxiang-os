import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ZButton } from '../design-system/components';
import styles from './NotFoundPage.module.css';

const UnauthorizedPage: React.FC = () => {
  const navigate = useNavigate();
  return (
    <div className={styles.wrap}>
      <div className={styles.code}>403</div>
      <div className={styles.title}>抱歉，您没有权限访问此页面。</div>
      <ZButton variant="primary" onClick={() => navigate('/')}>返回首页</ZButton>
    </div>
  );
};

export default UnauthorizedPage;
