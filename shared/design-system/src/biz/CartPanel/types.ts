export interface CartItem {
  id: string;
  dishId: string;
  name: string;
  quantity: number;
  priceFen: number;
  notes?: string;
  kitchenStation?: string;
}

export interface CartPanelProps {
  mode: 'sidebar' | 'bottom-bar';
  items: CartItem[];
  totalFen: number;
  discountFen?: number;
  tableNo?: string;
  onUpdateQuantity: (itemId: string, quantity: number) => void;
  onRemoveItem: (itemId: string) => void;
  onClear?: () => void;
  onSettle: () => void;
  onHold?: () => void;          // 挂单（POS only）
  className?: string;
}
