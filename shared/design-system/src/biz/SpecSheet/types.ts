export interface SpecOption {
  id: string;
  label: string;
  extraPriceFen?: number;
}

export interface SpecGroup {
  id: string;
  name: string;
  type: 'single' | 'multi';     // single = radio, multi = checkbox
  required?: boolean;
  options: SpecOption[];
}

export interface SpecSheetProps {
  visible: boolean;
  dishName: string;
  dishPriceFen: number;
  dishImage?: string;
  specGroups: SpecGroup[];
  initialQuantity?: number;
  onConfirm: (selections: Record<string, string[]>, quantity: number) => void;
  onClose: () => void;
}
