/**
 * MenuSchemePreview — 菜谱方案预览卡片（admin/管理端使用）
 *
 * 展示一个菜谱方案的基本信息：名称、适用门店/业态、
 * 包含菜品数量、发布状态、版本号等。
 * 常用于方案列表页和方案下发流程中。
 */
import styles from './MenuSchemePreview.module.css';
import { cn } from '../../utils/cn';

export interface MenuSchemeData {
  id: string;
  name: string;
  description?: string;
  /** 适用业态标签，如"大店Pro"/"小店Lite" */
  formatTags?: string[];
  /** 包含菜品数量 */
  dishCount: number;
  /** 包含分类数量 */
  categoryCount: number;
  /** 方案版本号 */
  version: number;
  /** 发布状态 */
  status: 'draft' | 'published' | 'archived';
  /** 已下发门店数 */
  appliedStoreCount?: number;
  /** 总目标门店数 */
  totalStoreCount?: number;
  /** 最后更新时间 ISO string */
  updatedAt?: string;
  /** 创建者姓名 */
  createdBy?: string;
}

export interface MenuSchemePreviewProps {
  scheme: MenuSchemeData;
  selected?: boolean;
  onView?: (scheme: MenuSchemeData) => void;
  onPublish?: (scheme: MenuSchemeData) => void;
  onEdit?: (scheme: MenuSchemeData) => void;
  onClick?: (scheme: MenuSchemeData) => void;
}

const STATUS_META: Record<string, { label: string; className: string }> = {
  draft:     { label: '草稿', className: 'statusDraft' },
  published: { label: '已发布', className: 'statusPublished' },
  archived:  { label: '已归档', className: 'statusArchived' },
};

export default function MenuSchemePreview({
  scheme,
  selected,
  onView,
  onPublish,
  onEdit,
  onClick,
}: MenuSchemePreviewProps) {
  const statusMeta = STATUS_META[scheme.status] || STATUS_META.draft;

  const appliedPct =
    scheme.totalStoreCount && scheme.totalStoreCount > 0
      ? Math.round(((scheme.appliedStoreCount ?? 0) / scheme.totalStoreCount) * 100)
      : null;

  return (
    <div
      className={cn(
        styles.card,
        selected && styles.selected,
        scheme.status === 'archived' && styles.archived,
      )}
      onClick={() => onClick?.(scheme)}
    >
      {/* Header */}
      <div className={styles.header}>
        <span className={styles.name}>{scheme.name}</span>
        <span className={cn(styles.statusBadge, styles[statusMeta.className])}>
          {statusMeta.label}
        </span>
      </div>

      {/* Description */}
      {scheme.description && (
        <div className={styles.description}>{scheme.description}</div>
      )}

      {/* Format tags */}
      {scheme.formatTags && scheme.formatTags.length > 0 && (
        <div className={styles.tags}>
          {scheme.formatTags.map((tag) => (
            <span key={tag} className={styles.tag}>{tag}</span>
          ))}
        </div>
      )}

      {/* Stats row */}
      <div className={styles.statsRow}>
        <span className={styles.stat}>
          <span className={styles.statValue}>{scheme.dishCount}</span>
          <span className={styles.statLabel}>菜品</span>
        </span>
        <span className={styles.stat}>
          <span className={styles.statValue}>{scheme.categoryCount}</span>
          <span className={styles.statLabel}>分类</span>
        </span>
        <span className={styles.stat}>
          <span className={styles.statValue}>v{scheme.version}</span>
          <span className={styles.statLabel}>版本</span>
        </span>
      </div>

      {/* Store coverage */}
      {appliedPct !== null && (
        <div className={styles.coverageRow}>
          <div className={styles.coverageBar}>
            <div
              className={styles.coverageFill}
              style={{ width: `${appliedPct}%` }}
            />
          </div>
          <span className={styles.coverageText}>
            {scheme.appliedStoreCount}/{scheme.totalStoreCount} 门店 ({appliedPct}%)
          </span>
        </div>
      )}

      {/* Meta info */}
      <div className={styles.meta}>
        {scheme.createdBy && (
          <span className={styles.metaItem}>{scheme.createdBy}</span>
        )}
        {scheme.updatedAt && (
          <span className={styles.metaItem}>
            {new Date(scheme.updatedAt).toLocaleDateString('zh-CN')}
          </span>
        )}
      </div>

      {/* Actions */}
      <div className={styles.actions}>
        {onView && (
          <button
            type="button"
            className={cn(styles.actionBtn, styles.viewBtn)}
            onClick={(e) => { e.stopPropagation(); onView(scheme); }}
          >
            查看
          </button>
        )}
        {onEdit && scheme.status !== 'archived' && (
          <button
            type="button"
            className={cn(styles.actionBtn, styles.editBtn)}
            onClick={(e) => { e.stopPropagation(); onEdit(scheme); }}
          >
            编辑
          </button>
        )}
        {onPublish && scheme.status === 'draft' && (
          <button
            type="button"
            className={cn(styles.actionBtn, styles.publishBtn)}
            onClick={(e) => { e.stopPropagation(); onPublish(scheme); }}
          >
            发布
          </button>
        )}
      </div>
    </div>
  );
}
