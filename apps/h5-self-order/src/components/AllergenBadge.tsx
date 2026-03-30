import type { Allergen } from '@/api/menuApi';
import styles from './AllergenBadge.module.css';

interface AllergenBadgeProps {
  allergen: Allergen;
}

/** 过敏原图标映射（无图标时用文字首字母） */
const ICON_MAP: Record<string, string> = {
  gluten: 'G',
  shellfish: 'S',
  peanut: 'P',
  treenut: 'T',
  dairy: 'D',
  egg: 'E',
  soy: 'Y',
  fish: 'F',
  sesame: 'Se',
};

export default function AllergenBadge({ allergen }: AllergenBadgeProps) {
  return (
    <span className={styles.badge} title={allergen.name}>
      <span className={styles.icon}>
        {allergen.icon || ICON_MAP[allergen.code] || allergen.code[0].toUpperCase()}
      </span>
      <span className={styles.name}>{allergen.name}</span>
    </span>
  );
}
