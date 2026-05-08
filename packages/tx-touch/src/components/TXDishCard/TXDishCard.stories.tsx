import type { Meta, StoryObj } from '@storybook/react';
import { TXDishCard } from './TXDishCard';

const meta: Meta<typeof TXDishCard> = {
  title: 'TXTouch/TXDishCard',
  component: TXDishCard,
  tags: ['autodocs'],
  parameters: {
    docs: {
      description: {
        component:
          '点餐场景菜品卡片。价格单位 **分**（整数），渲染时通过 fenToYuan 转换。' +
          '支持长按（500ms）触发口味/规格选择 / 沽清态 / 已点数量角标。',
      },
    },
  },
  argTypes: {
    price: { control: { type: 'number', min: 0, step: 100 }, description: '单位：分' },
    soldOut: { control: 'boolean' },
    quantity: { control: { type: 'number', min: 0, max: 99 } },
  },
};
export default meta;
type Story = StoryObj<typeof TXDishCard>;

export const Default: Story = {
  args: {
    name: '霸王蟹',
    price: 28800,
    tags: ['活鲜', '招牌'],
    onPress: () => alert('加入购物车'),
    onLongPress: () => alert('打开规格选择'),
  },
};

export const SoldOut: Story = {
  args: {
    name: '清蒸石斑鱼',
    price: 19800,
    soldOut: true,
    onPress: () => {},
  },
  parameters: {
    docs: {
      description: { story: '沽清菜品 — 不可点击，灰阶遮罩。' },
    },
  },
};

export const WithQuantity: Story = {
  args: {
    name: '皮香小菜花',
    price: 1800,
    quantity: 3,
    onPress: () => {},
  },
  parameters: {
    docs: {
      description: { story: '右上角橙色角标显示已点数量（>0 时）。' },
    },
  },
};

export const NoImage: Story = {
  args: {
    name: '招牌酱卤鹅',
    price: 8800,
    tags: ['新菜'],
    onPress: () => {},
  },
};
