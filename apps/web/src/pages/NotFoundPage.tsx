import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ZButton } from '../design-system/components';
import styles from './NotFoundPage.module.css';

const NotFoundPage: React.FC = () => {
  const navigate = useNavigate();
  return (
    <div className={styles.wrap}>
      <div className={styles.code}>404</div>
      <div className={styles.title}>页面不存在</div>
      <ZButton variant="primary" onClick={() => navigate('/')}>返回首页</ZButton>
    </div>
  );
};

export default NotFoundPage;
