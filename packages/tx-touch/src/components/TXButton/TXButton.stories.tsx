import type { Meta, StoryObj } from '@storybook/react';
import { TXButton } from './TXButton';

const meta: Meta<typeof TXButton> = {
  title: 'TXTouch/TXButton',
  component: TXButton,
  tags: ['autodocs'],
  parameters: {
    docs: {
      description: {
        component:
          'Store 终端主按钮。宪法 §3.2 触控基线 ≥ 48px / 关键操作 ≥ 72px。' +
          'AntD Button 的 Store 端等价物，禁用 hover-only 反馈，强化 :active 缩放。',
      },
    },
  },
  argTypes: {
    variant: { control: 'select', options: ['primary', 'secondary', 'danger', 'ghost'] },
    size: { control: 'select', options: ['normal', 'large', 'fullwidth'] },
    disabled: { control: 'boolean' },
    loading: { control: 'boolean' },
    badge: { control: { type: 'number', min: 0, max: 99 } },
  },
};
export default meta;

type Story = StoryObj<typeof TXButton>;

export const Primary: Story = {
  args: {
    variant: 'primary',
    size: 'normal',
    children: '结账',
    onPress: () => alert('press'),
  },
};

export const Large72px: Story = {
  args: {
    variant: 'primary',
    size: 'large',
    children: '关键操作（≥72px）',
    onPress: () => {},
  },
  parameters: {
    docs: {
      description: { story: '宪法 §3.2 关键操作触控基线 — 收银/支付/出餐确认。' },
    },
  },
};

export const Fullwidth: Story = {
  args: {
    variant: 'primary',
    size: 'fullwidth',
    children: '立即支付',
    onPress: () => {},
  },
};

export const Secondary: Story = {
  args: {
    variant: 'secondary',
    children: '取消',
    onPress: () => {},
  },
};

export const Danger: Story = {
  args: {
    variant: 'danger',
    children: '退单',
    onPress: () => {},
  },
};

export const WithBadge: Story = {
  args: {
    variant: 'primary',
    children: '购物车',
    badge: 5,
    onPress: () => {},
  },
};

export const Disabled: Story = {
  args: {
    variant: 'primary',
    children: '不可用',
    disabled: true,
    onPress: () => {},
  },
};

export const Loading: Story = {
  args: {
    variant: 'primary',
    children: '处理中',
    loading: true,
    onPress: () => {},
  },
};
