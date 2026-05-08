import type { Meta, StoryObj } from '@storybook/react';
import { TXKDSTicket } from './TXKDSTicket';

const meta: Meta<typeof TXKDSTicket> = {
  title: 'TXTouch/TXKDSTicket',
  component: TXKDSTicket,
  tags: ['autodocs'],
  parameters: {
    docs: {
      description: {
        component:
          'KDS 出餐工单卡片。宪法 §3.3 KDS 字号铁律：' +
          '订单号 32px / 区域 28px / 菜品行 20px / 徽标 16px。' +
          '左滑完成（threshold 72px）+ 加急按钮（≥72×72px）+ 倒计时颜色编码。',
      },
    },
  },
  argTypes: {
    timeLimit: { control: { type: 'number', min: 1, max: 60 } },
    isVip: { control: 'boolean' },
  },
};
export default meta;
type Story = StoryObj<typeof TXKDSTicket>;

const SAMPLE_ITEMS = [
  { name: '霸王蟹（清蒸）', qty: 1, spec: '不要葱', priority: 'normal' as const },
  { name: '皮香小菜花', qty: 2, priority: 'normal' as const },
  { name: '剁椒鱼头', qty: 1, priority: 'rush' as const },
];

export const Normal: Story = {
  args: {
    orderId: 'O-2026050810001',
    tableNo: 'A03',
    items: SAMPLE_ITEMS,
    createdAt: Date.now() - 3 * 60 * 1000, // 3 分钟前
    timeLimit: 10,
    onComplete: () => alert('左滑完成出餐'),
    onRush: () => alert('加急'),
  },
};

export const Urgent: Story = {
  args: {
    orderId: 'O-2026050810002',
    tableNo: 'B05',
    items: SAMPLE_ITEMS,
    createdAt: Date.now() - 7 * 60 * 1000, // 7 分钟前（剩 30%）
    timeLimit: 10,
    onComplete: () => {},
    onRush: () => {},
  },
  parameters: {
    docs: {
      description: { story: '剩余时间 ≤50% — 倒计时变橙色。' },
    },
  },
};

export const Overdue: Story = {
  args: {
    orderId: 'O-2026050810003',
    tableNo: 'C02',
    items: SAMPLE_ITEMS,
    createdAt: Date.now() - 12 * 60 * 1000, // 超时 2 分钟
    timeLimit: 10,
    onComplete: () => {},
    onRush: () => {},
  },
  parameters: {
    docs: {
      description: { story: '已超时 — 倒计时变红色 + 闪烁边框（@keyframes border-flash）。' },
    },
  },
};

export const VIP: Story = {
  args: {
    orderId: 'O-2026050810004',
    tableNo: '包间 1',
    items: SAMPLE_ITEMS,
    createdAt: Date.now() - 1 * 60 * 1000,
    timeLimit: 10,
    isVip: true,
    onComplete: () => {},
    onRush: () => {},
  },
  parameters: {
    docs: {
      description: { story: 'VIP 工单 — 顶部金色 VIP 徽标，优先出餐顺序。' },
    },
  },
};
