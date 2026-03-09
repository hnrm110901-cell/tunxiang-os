/**
 * SM 执行任务总览页
 * 路由：/sm/banquet-tasks
 * 数据：GET /api/v1/banquet-agent/stores/{id}/tasks?status=&owner_role=
 *      PATCH /api/v1/banquet-agent/stores/{id}/orders/{order_id}/tasks/{task_id}
 */
import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import dayjs from 'dayjs';
import {
  ZCard, ZBadge, ZButton, ZSkeleton, ZEmpty,
} from '../../design-system/components';
import apiClient from '../../services/api';
import { handleApiError } from '../../utils/message';
import styles from './BanquetTasks.module.css';

const STORE_ID = localStorage.getItem('store_id') || 'S001';

const STATUS_FILTERS = [
  { value: '',            label: '全部' },
  { value: 'pending',     label: '待处理' },
  { value: 'in_progress', label: '进行中' },
  { value: 'done',        label: '已完成' },
  { value: 'overdue',     label: '已逾期' },
];

const ROLE_FILTERS = [
  { value: '',         label: '全部角色' },
  { value: 'kitchen',  label: '厨房' },
  { value: 'service',  label: '服务' },
  { value: 'decor',    label: '布置' },
  { value: 'purchase', label: '采购' },
  { value: 'manager',  label: '店长' },
];

const TASK_STATUS_BADGE: Record<string, { text: string; type: 'success' | 'info' | 'warning' | 'default' }> = {
  pending:     { text: '待处理', type: 'warning' },
  in_progress: { text: '进行中', type: 'info'    },
  done:        { text: '已完成', type: 'success' },
  verified:    { text: '已核验', type: 'success' },
  overdue:     { text: '已逾期', type: 'default' },
  closed:      { text: '已关闭', type: 'default' },
};

const ROLE_LABELS: Record<string, string> = {
  kitchen:  '厨房',
  service:  '服务',
  decor:    '布置',
  purchase: '采购',
  manager:  '店长',
};

interface TaskItem {
  task_id:      string;
  task_name:    string;
  task_type:    string;
  owner_role:   string;
  due_time:     string | null;
  status:       string;
  completed_at: string | null;
  order_id:     string;
  banquet_date: string | null;
  banquet_type: string | null;
}

export default function SmBanquetTasks() {
  const navigate = useNavigate();

  const [statusFilter, setStatusFilter] = useState('pending');
  const [roleFilter,   setRoleFilter]   = useState('');
  const [tasks,        setTasks]        = useState<TaskItem[]>([]);
  const [loading,      setLoading]      = useState(true);
  const [completing,   setCompleting]   = useState<string | null>(null);

  const loadTasks = useCallback(async (status: string, role: string) => {
    setLoading(true);
    try {
      const params: Record<string, string> = {};
      if (status) params.status = status;
      if (role)   params.owner_role = role;
      const resp = await apiClient.get(
        `/api/v1/banquet-agent/stores/${STORE_ID}/tasks`,
        { params },
      );
      const raw = resp.data;
      setTasks(Array.isArray(raw) ? raw : []);
    } catch {
      setTasks([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadTasks(statusFilter, roleFilter); }, [loadTasks, statusFilter, roleFilter]);

  const completeTask = async (task: TaskItem) => {
    const newStatus = task.status === 'done' ? 'pending' : 'done';
    setCompleting(task.task_id);
    try {
      await apiClient.patch(
        `/api/v1/banquet-agent/stores/${STORE_ID}/orders/${task.order_id}/tasks/${task.task_id}`,
        { status: newStatus },
      );
      await loadTasks(statusFilter, roleFilter);
    } catch (e) {
      handleApiError(e, '更新任务失败');
    } finally {
      setCompleting(null);
    }
  };

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <button className={styles.back} onClick={() => navigate('/sm/banquet')}>← 返回</button>
        <div className={styles.title}>执行任务</div>
      </div>

      {/* 状态 Chip */}
      <div className={styles.chipBar}>
        {STATUS_FILTERS.map(f => (
          <button
            key={f.value}
            className={`${styles.chip} ${statusFilter === f.value ? styles.chipActive : ''}`}
            onClick={() => setStatusFilter(f.value)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* 角色 Chip */}
      <div className={`${styles.chipBar} ${styles.chipBarSecondary}`}>
        {ROLE_FILTERS.map(f => (
          <button
            key={f.value}
            className={`${styles.chip} ${styles.chipSm} ${roleFilter === f.value ? styles.chipActive : ''}`}
            onClick={() => setRoleFilter(f.value)}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className={styles.body}>
        <ZCard>
          {loading ? (
            <ZSkeleton rows={5} />
          ) : !tasks.length ? (
            <ZEmpty title="暂无任务" description="当前筛选条件下没有执行任务" />
          ) : (
            <div className={styles.list}>
              {tasks.map(task => {
                const tb = TASK_STATUS_BADGE[task.status] ?? { text: task.status, type: 'default' as const };
                const isDone = task.status === 'done' || task.status === 'verified';
                const isOverdue = !isDone && task.due_time && dayjs(task.due_time).isBefore(dayjs());
                return (
                  <div key={task.task_id} className={`${styles.row} ${isDone ? styles.rowDone : ''}`}>
                    <div className={styles.info}>
                      <div className={styles.taskName}>{task.task_name}</div>
                      <div className={styles.meta}>
                        {task.banquet_date ? dayjs(task.banquet_date).format('MM-DD') : ''}
                        {task.banquet_type ? ` · ${task.banquet_type}` : ''}
                        {task.due_time ? ` · 截止${dayjs(task.due_time).format('MM-DD HH:mm')}` : ''}
                        {isOverdue ? ' ⚠️' : ''}
                      </div>
                    </div>
                    <div className={styles.right}>
                      <ZBadge type="default" text={ROLE_LABELS[task.owner_role] ?? task.owner_role} />
                      <ZBadge type={tb.type} text={tb.text} />
                      {!isDone && (
                        <ZButton
                          variant="ghost"
                          size="sm"
                          onClick={() => completeTask(task)}
                          disabled={completing === task.task_id}
                        >
                          {completing === task.task_id ? '…' : '完成'}
                        </ZButton>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </ZCard>
      </div>
    </div>
  );
}
