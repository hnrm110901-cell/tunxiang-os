import type { Meta, StoryObj } from '@storybook/react';
import { TXCard } from './TXCard';

const meta: Meta<typeof TXCard> = {
  title: 'TXTouch/TXCard',
  component: TXCard,
  tags: ['autodocs'],
  parameters: {
    docs: {
      description: {
        component:
          'Store 终端通用卡片容器。AntD Card 的 Store 端等价物。' +
          '可点击（onPress）/ 选中态 / status warning|danger 三种状态。',
      },
    },
  },
  argTypes: {
    selected: { control: 'boolean' },
    status: { control: 'select', options: ['normal', 'warning', 'danger'] },
  },
};
export default meta;
type Story = StoryObj<typeof TXCard>;

export const Plain: Story = {
  args: {
    children: (
      <div style={{ padding: 16 }}>
        <h3 style={{ margin: 0, fontSize: 18, color: 'var(--tx-text-1)' }}>桌台 A03</h3>
        <p style={{ margin: '8px 0 0', fontSize: 16, color: 'var(--tx-text-2)' }}>4 座 · 用餐中</p>
      </div>
    ),
  },
};

export const Pressable: Story = {
  args: {
    onPress: () => alert('press'),
    children: (
      <div style={{ padding: 16 }}>
        <h3 style={{ margin: 0, fontSize: 18, color: 'var(--tx-text-1)' }}>点我</h3>
        <p style={{ margin: '8px 0 0', fontSize: 14, color: 'var(--tx-text-2)' }}>onPress 触发</p>
      </div>
    ),
  },
};

export const Selected: Story = {
  args: {
    selected: true,
    onPress: () => {},
    children: <div style={{ padding: 16, color: 'var(--tx-text-1)' }}>选中态（焦点框 + 主色边框）</div>,
  },
};

export const Warning: Story = {
  args: {
    status: 'warning',
    children: <div style={{ padding: 16, color: 'var(--tx-text-1)' }}>临期食材警告卡片</div>,
  },
};

export const Danger: Story = {
  args: {
    status: 'danger',
    children: <div style={{ padding: 16, color: 'var(--tx-text-1)' }}>毛利底线异常卡片</div>,
  },
};
