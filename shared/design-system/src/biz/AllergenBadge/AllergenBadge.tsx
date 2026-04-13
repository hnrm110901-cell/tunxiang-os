import styles from './AllergenBadge.module.css';
import { cn } from '../../utils/cn';

export interface Allergen {
  code: string;
  name: string;
  icon?: string;
}

export interface AllergenBadgeProps {
  allergen: Allergen;
  size?: 'sm' | 'md';
  className?: string;
}

const ICON_MAP: Record<string, string> = {
  gluten: 'G', shellfish: 'S', peanut: 'P', treenut: 'T',
  dairy: 'D', egg: 'E', soy: 'Y', fish: 'F', sesame: 'Se',
  wheat: 'W', celery: 'Ce', mustard: 'M', lupin: 'L',
  molluscs: 'Mo', sulfites: 'Su', crustacean: 'Cr',
};

const CN_NAME_MAP: Record<string, string> = {
  gluten: '麸质', shellfish: '贝类', peanut: '花生', treenut: '坚果',
  dairy: '乳制品', egg: '蛋', soy: '大豆', fish: '鱼', sesame: '芝麻',
  wheat: '小麦', celery: '芹菜', mustard: '芥末', lupin: '羽扇豆',
  molluscs: '软体类', sulfites: '亚硫酸盐', crustacean: '甲壳类',
};

export default function AllergenBadge({ allergen, size = 'sm', className }: AllergenBadgeProps) {
  const icon = allergen.icon || ICON_MAP[allergen.code] || allergen.code[0].toUpperCase();
  const displayName = allergen.name || CN_NAME_MAP[allergen.code] || allergen.code;

  return (
    <span
      className={cn(styles.badge, size === 'md' && styles.md, className)}
      title={displayName}
    >
      <span className={styles.icon}>{icon}</span>
      <span className={styles.name}>{displayName}</span>
    </span>
  );
}
