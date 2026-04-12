export interface DishData {
  id: string;
  name: string;
  priceFen: number;
  memberPriceFen?: number;
  category: string;
  images?: string[];
  tags?: Array<{ type: string; label: string }>;
  allergens?: Array<{ code: string; name: string }>;
  description?: string;
  soldOut?: boolean;
  pricingMethod?: 'normal' | 'weight' | 'count';
  comboType?: 'fixed' | 'flexible';
  kitchenStation?: string;
}

export interface DishCardProps {
  dish: DishData;
  variant: 'grid' | 'horizontal' | 'compact';
  quantity?: number;
  showMemberPrice?: boolean;
  showTags?: boolean;
  showAllergens?: boolean;
  showImage?: boolean;
  onAdd: () => void;
  onTap?: () => void;
  className?: string;
}
