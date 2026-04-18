/**
 * 桌台管理主页面
 * 整合汇总栏、视图切换和各视图组件
 * @module pages/TableManagement
 */

import React, { useEffect, useMemo } from 'react';
import { Segmented, Button, message } from 'antd';
import {
  BgColorsOutlined,
  UnorderedListOutlined,
  EnvironmentOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { TXButton } from '@tx/touch';
import { useTableStore } from '../../stores/tableStore';
import { ViewMode } from '../../types/table-card';
import StatusSummaryBar from './components/StatusSummaryBar';
import TableCardView from './TableCardView';
import TableListView from './TableListView';
import TableMapView from './TableMapView';
import styles from './TableManagement.module.css';

/**
 * 页面Props
 */
export interface TableManagementPageProps {
  /** 门店ID，通常从路由参数或上下文获取 */
  storeId?: string;
}

/**
 * 视图配置
 */
const VIEW_CONFIG: Record<ViewMode, { icon: string; label: string }> = {
  card: { icon: '⊞', label: '卡片' },
  list: { icon: '≡', label: '列表' },
  map: { icon: '⊙', label: '地图' },
};

/**
 * 桌台管理主页面
 * 提供卡片、列表、地图三种视图查看和管理桌台
 */
export const TableManagementPage: React.FC<TableManagementPageProps> = ({
  storeId = 'store-001', // 默认门店ID，实际应从路由或上下文获取
}) => {
  const {
    summary,
    viewMode,
    loading,
    error,
    statusFilter,
    fetchTables,
    setViewMode,
    setStatusFilter,
    getFilteredTables,
  } = useTableStore();

  // 初始化时获取数据
  useEffect(() => {
    fetchTables(storeId, viewMode);
  }, [storeId, viewMode, fetchTables]);

  // 获取按筛选条件过滤的桌台列表
  const filteredTables = useMemo(() => getFilteredTables(), [getFilteredTables]);

  // 处理视图切换
  const handleViewModeChange = (value: string | number) => {
    setViewMode(value as ViewMode);
  };

  // 手动刷新数据
  const handleRefresh = async () => {
    try {
      await fetchTables(storeId, viewMode);
    } catch (err) {
      // 刷新失败：静默处理（toast 由 store 的 error 字段驱动）
    }
  };

  // 渲染对应视图的组件
  const renderViewContent = () => {
    switch (viewMode) {
      case 'card':
        return (
          <TableCardView
            tables={filteredTables}
            storeId={storeId}
            loading={loading}
          />
        );
      case 'list':
        return (
          <TableListView
            tables={filteredTables}
            storeId={storeId}
            loading={loading}
          />
        );
      case 'map':
        return (
          <TableMapView
            tables={filteredTables}
            storeId={storeId}
            loading={loading}
          />
        );
      default:
        return null;
    }
  };

  return (
    <div className={styles.container}>
      {/* 顶部工具栏 */}
      <div className={styles.toolbar}>
        <StatusSummaryBar
          summary={summary}
          activeStatus={statusFilter}
          onStatusChange={setStatusFilter}
          loading={loading}
        />

        <div className={styles.viewModeSelector}>
          {/* 视图切换 — 用原生按钮组替代 antd Segmented */}
          <div style={{ display: 'flex', gap: 4, background: 'rgba(255,255,255,0.06)', borderRadius: 8, padding: 4 }}>
            {(['card', 'list', 'map'] as ViewMode[]).map((mode) => (
              <button
                key={mode}
                type="button"
                disabled={loading}
                onClick={() => handleViewModeChange(mode)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                  padding: '8px 14px',
                  minHeight: 40,
                  border: 'none',
                  borderRadius: 6,
                  background: viewMode === mode ? '#FF6B35' : 'transparent',
                  color: viewMode === mode ? '#fff' : 'rgba(255,255,255,0.65)',
                  fontSize: 16,
                  fontWeight: viewMode === mode ? 600 : 400,
                  cursor: loading ? 'not-allowed' : 'pointer',
                  transition: 'background 200ms ease',
                  fontFamily: 'inherit',
                }}
              >
                <span>{VIEW_CONFIG[mode].icon}</span>
                <span>{VIEW_CONFIG[mode].label}</span>
              </button>
            ))}
          </div>

          <TXButton
            variant="secondary"
            size="normal"
            onPress={handleRefresh}
            disabled={loading}
          >
            {loading ? '刷新中...' : '↻ 刷新'}
          </TXButton>
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <div
          style={{
            padding: '16px',
            background: '#fff2f0',
            borderLeft: '4px solid #ff4d4f',
            borderRadius: '4px',
            color: '#ff4d4f',
            fontSize: '14px',
          }}
        >
          <strong>加载错误:</strong> {error}
        </div>
      )}

      {/* 内容区域 */}
      <div className={styles.content}>
        {renderViewContent()}
      </div>

      {/* 悬浮刷新按钮 (可选) */}
      {/* <Affix style={{ bottom: 24, right: 24 }}>
        <Button
          type="primary"
          shape="circle"
          size="large"
          icon={<ReloadOutlined />}
          onClick={handleRefresh}
          loading={loading}
        />
      </Affix> */}
    </div>
  );
};

export default TableManagementPage;
